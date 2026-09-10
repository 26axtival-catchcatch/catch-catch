"""Streaming exploration reader and run-scoped cursor/materialization contracts."""

from __future__ import annotations

import os
import stat
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import duckdb

import customer_signal.exploration.materialization as materialization_module
from customer_signal.data.source_registry import SourceRegistry
from customer_signal.domain.models import SyntheticDataset
from customer_signal.data.repository import DuckDBRepository
from customer_signal.exploration.contracts import EventSortKey, ExplorationSourceScope
from customer_signal.exploration.cursor import CursorCodec, CursorPayload, CursorValidationError
from customer_signal.exploration.materialization import (
    ForeignRunReferenceError,
    RunMaterializationStore,
    StaleSnapshotReferenceError,
)
from customer_signal.exploration.reader import (
    DataSpaceReader,
    RetryablePageError,
    ScanInterruptedError,
    SnapshotChangedDuringScanError,
)
from customer_signal.onboarding.adapter import CompositeEvidenceProvider, load_onboarded_adapters
from customer_signal.synthetic.adapter import SyntheticDuckDBAdapter
from customer_signal.synthetic.manifest import synthetic_source_manifest


SEED_ROOT = Path("data/seeding/hackathon-2week/onboarded-sources")
SOURCE_IDS = (
    "hackathon_app_behavior",
    "hackathon_billing_profile",
    "hackathon_search_feedback",
    "hackathon_search_history",
    "hackathon_vas_subscription",
    "hackathon_voc",
    "hackathon_roaming_usage",
)


class _MutatingPagedAdapter:
    def __init__(self, base: SyntheticDuckDBAdapter, *, mutate_after_page: int) -> None:
        self._base = base
        self._mutate_after_page = mutate_after_page
        self._event_page_calls = 0
        self._version = 0

    def describe(self):
        return self._base.describe()

    def snapshot_token(self) -> str:
        return f"{self._base.snapshot_token()}:{self._version}"

    def load_event_page(self, request):
        page = self._base.load_event_page(request)
        self._event_page_calls += 1
        if self._event_page_calls == self._mutate_after_page:
            self._version += 1
        return page

    def load_identity_page(self, request):
        return self._base.load_identity_page(request)

    def load_events(self, scope):
        return self._base.load_events(scope)

    def load_identities(self, scope):
        return self._base.load_identities(scope)

    def get_evidence(self, allowed_evidence_ids: Sequence[str]):
        return self._base.get_evidence(allowed_evidence_ids)


class _RetryingEventAdapter:
    def __init__(self, base: SyntheticDuckDBAdapter, *, fail_on_page: int) -> None:
        self._base = base
        self._fail_on_page = fail_on_page
        self._page_calls = 0

    def describe(self):
        return self._base.describe()

    def snapshot_token(self) -> str:
        return self._base.snapshot_token()

    def load_event_page(self, request):
        self._page_calls += 1
        if self._page_calls == self._fail_on_page:
            raise RetryablePageError("temporary page failure")
        return self._base.load_event_page(request)

    def load_identity_page(self, request):
        return self._base.load_identity_page(request)

    def load_events(self, scope):
        return self._base.load_events(scope)

    def load_identities(self, scope):
        return self._base.load_identities(scope)

    def get_evidence(self, allowed_evidence_ids: Sequence[str]):
        return self._base.get_evidence(allowed_evidence_ids)


class _RetryingSnapshotAdapter:
    def __init__(self, base: SyntheticDuckDBAdapter) -> None:
        self._base = base
        self._snapshot_calls = 0
        self._fail_on_snapshot_call: int | None = None

    def arm_snapshot_failure_after(self, call_count: int) -> None:
        self._fail_on_snapshot_call = self._snapshot_calls + call_count

    def describe(self):
        return self._base.describe()

    def snapshot_token(self) -> str:
        self._snapshot_calls += 1
        if self._snapshot_calls == self._fail_on_snapshot_call:
            raise RetryablePageError("temporary snapshot barrier failure")
        return self._base.snapshot_token()

    def load_event_page(self, request):
        return self._base.load_event_page(request)

    def load_identity_page(self, request):
        return self._base.load_identity_page(request)

    def load_events(self, scope):
        return self._base.load_events(scope)

    def load_identities(self, scope):
        return self._base.load_identities(scope)

    def get_evidence(self, allowed_evidence_ids: Sequence[str]):
        return self._base.get_evidence(allowed_evidence_ids)


def _scope(*, page_size: int = 200) -> ExplorationSourceScope:
    return ExplorationSourceScope(
        source_ids=SOURCE_IDS,
        start_at=datetime.fromisoformat("2026-09-04T00:00:00+09:00"),
        end_at=datetime.fromisoformat("2026-09-18T00:00:00+09:00"),
        native_page_size=page_size,
    )


@pytest.fixture(scope="module")
def seeded_registry() -> SourceRegistry:
    adapters = load_onboarded_adapters(SEED_ROOT)
    return SourceRegistry(adapters, CompositeEvidenceProvider(None, adapters))


def test_reader_streams_every_seeded_event_without_duplicates(
    seeded_registry: SourceRegistry,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    scope = _scope(page_size=37)
    prepared = seeded_registry.prepare_paged_sources(scope)
    store = RunMaterializationStore(tmp_path_factory.mktemp("reader"), run_id="scan")
    reader = DataSpaceReader(
        registry=seeded_registry,
        prepared_sources=prepared,
        authorized_scope=scope,
        cursor_codec=CursorCodec(b"test-secret" * 4),
        materializations=store,
    )
    keys: list[tuple[datetime, str, str]] = []
    reader.scan_events(
        scope,
        consumer=lambda event: keys.append(EventSortKey.from_event(event).as_tuple()),
    )

    assert len(keys) == 15_377
    assert keys == sorted(keys)
    assert len(keys) == len(set(keys))
    store.dispose()


def test_equal_timestamp_cross_source_events_survive_one_row_page_boundaries(
    tmp_path: Path,
    repository: DuckDBRepository,
    synthetic_dataset: SyntheticDataset,
) -> None:
    source_ids = tuple(sorted({event.source_id for event in synthetic_dataset.events}))
    adapters = [
        SyntheticDuckDBAdapter(
            repository,
            synthetic_source_manifest(source_id, synthetic_dataset.events),
        )
        for source_id in source_ids
    ]
    registry = SourceRegistry(adapters, evidence=adapters[0])
    scope = ExplorationSourceScope(
        source_ids=source_ids,
        start_at=min(event.occurred_at for event in synthetic_dataset.events),
        end_at=max(event.occurred_at for event in synthetic_dataset.events)
        + timedelta(microseconds=1),
        native_page_size=1,
    )
    store = RunMaterializationStore(tmp_path / "equal-time", run_id="equal-time")
    reader = DataSpaceReader(
        registry=registry,
        prepared_sources=registry.prepare_paged_sources(scope),
        authorized_scope=scope,
        cursor_codec=CursorCodec(b"equal-time-cursor-secret" * 2),
        materializations=store,
    )
    keys: list[tuple[datetime, str, str]] = []

    reader.scan_events(
        scope,
        consumer=lambda event: keys.append(EventSortKey.from_event(event).as_tuple()),
    )

    assert len(keys) == len(synthetic_dataset.events) == 199
    assert keys == sorted(keys)
    assert len(keys) == len(set(keys))
    assert any(
        previous[0] == current[0] and previous[1] != current[1]
        for previous, current in zip(keys, keys[1:], strict=False)
    )
    assert reader.last_scan_peak_buffered_events <= len(source_ids)
    store.dispose()


@pytest.mark.parametrize(
    ("snapshot_call_offset", "expected_prefix_count"),
    ((1, 0), (2, 0), (3, 0), (4, 54)),
    ids=("scan-start", "before-fetch", "after-fetch", "final-barrier"),
)
def test_retryable_snapshot_barriers_return_only_a_certified_stable_prefix(
    tmp_path: Path,
    repository: DuckDBRepository,
    synthetic_dataset: SyntheticDataset,
    snapshot_call_offset: int,
    expected_prefix_count: int,
) -> None:
    source_id = "search_history"
    events = [event for event in synthetic_dataset.events if event.source_id == source_id]
    base = SyntheticDuckDBAdapter(
        repository, synthetic_source_manifest(source_id, synthetic_dataset.events)
    )
    adapter = _RetryingSnapshotAdapter(base)
    registry = SourceRegistry([adapter], evidence=adapter)
    scope = ExplorationSourceScope(
        source_ids=(source_id,),
        start_at=min(event.occurred_at for event in events),
        end_at=max(event.occurred_at for event in events) + timedelta(microseconds=1),
        native_page_size=200,
    )
    store = RunMaterializationStore(
        tmp_path / f"barrier-{snapshot_call_offset}",
        run_id=f"barrier-{snapshot_call_offset}",
    )
    reader = DataSpaceReader(
        registry=registry,
        prepared_sources=registry.prepare_paged_sources(scope),
        authorized_scope=scope,
        cursor_codec=CursorCodec(b"snapshot-barrier-cursor-secret" * 2),
        materializations=store,
    )
    adapter.arm_snapshot_failure_after(snapshot_call_offset)
    acquired = []

    with pytest.raises(ScanInterruptedError) as caught:
        reader.scan_events(scope, consumer=acquired.append)

    assert len(acquired) == expected_prefix_count
    assert caught.value.remaining_branches == (source_id,)
    assert store.generation == 0
    store.dispose()


def test_interruption_reports_only_sources_with_unread_or_buffered_events(
    tmp_path: Path,
    repository: DuckDBRepository,
    synthetic_dataset: SyntheticDataset,
) -> None:
    source_ids = ("search_history", "voc")
    search = _RetryingEventAdapter(
        SyntheticDuckDBAdapter(
            repository,
            synthetic_source_manifest("search_history", synthetic_dataset.events),
        ),
        fail_on_page=2,
    )
    voc = SyntheticDuckDBAdapter(
        repository, synthetic_source_manifest("voc", synthetic_dataset.events)
    )
    registry = SourceRegistry([search, voc], evidence=search)
    scope = ExplorationSourceScope(
        source_ids=source_ids,
        start_at=datetime.fromisoformat("2026-07-20T00:00:00+09:00"),
        end_at=datetime.fromisoformat("2026-07-21T22:00:00+09:00"),
        native_page_size=5,
    )
    store = RunMaterializationStore(
        tmp_path / "actual-unfinished", run_id="actual-unfinished"
    )
    reader = DataSpaceReader(
        registry=registry,
        prepared_sources=registry.prepare_paged_sources(scope),
        authorized_scope=scope,
        cursor_codec=CursorCodec(b"actual-unfinished-cursor-secret" * 2),
        materializations=store,
    )

    with pytest.raises(ScanInterruptedError) as caught:
        reader.scan_events(scope, consumer=lambda event: None)

    assert caught.value.remaining_branches == ("search_history",)
    store.dispose()


def test_cursor_signature_and_bindings_are_enforced() -> None:
    codec = CursorCodec(b"test-secret" * 4)
    payload = CursorPayload(
        run_id="run-a",
        generation=0,
        query_fingerprint="query-fingerprint",
        snapshot_id="snapshot-id-value",
        source_ids=("source-a",),
        result_kind="summary",
        query_ref="query-ref",
        result_ref="result-ref",
        page_index=1,
        page_size=50,
        last_sort_key="[\"row-1\"]",
    )
    token = codec.encode(payload)

    assert codec.decode(token) == payload
    with pytest.raises(CursorValidationError, match="signature"):
        codec.decode(token + "x")
    with pytest.raises(CursorValidationError, match="query fingerprint"):
        codec.decode_and_validate(
            token,
            run_id="run-a",
            generation=0,
            query_fingerprint="another-query",
            snapshot_id="snapshot-id-value",
            source_ids=("source-a",),
            result_kind="summary",
            page_size=50,
        )
    binding_cases = (
        ({"run_id": "run-b"}, "foreign run"),
        ({"generation": 1}, "generation"),
        ({"snapshot_id": "another-snapshot-id"}, "snapshot"),
        ({"source_ids": ("source-b",)}, "source selection"),
        ({"result_kind": "sequence"}, "result kind"),
        ({"page_size": 51}, "page size"),
    )
    expected = {
        "run_id": "run-a",
        "generation": 0,
        "query_fingerprint": "query-fingerprint",
        "snapshot_id": "snapshot-id-value",
        "source_ids": ("source-a",),
        "result_kind": "summary",
        "page_size": 50,
    }
    for overrides, message in binding_cases:
        with pytest.raises(CursorValidationError, match=message):
            codec.decode_and_validate(token, **{**expected, **overrides})


def test_materialization_is_run_scoped_invalidated_and_disposed(tmp_path: Path) -> None:
    first = RunMaterializationStore(tmp_path, run_id="run-a")
    second = RunMaterializationStore(tmp_path, run_id="run-b")
    result_ref = first.store_result(
        query_ref=first.make_ref("query"),
        result_kind="summary",
        query_fingerprint="fingerprint",
        snapshot_id="snapshot",
        source_ids=("source-a",),
        rows=[(("row", 1), {"name": "one"})],
        matched_count=1,
        scan_complete=True,
    )

    with pytest.raises(ForeignRunReferenceError):
        second.read_result(result_ref)

    first.invalidate_snapshot()
    with pytest.raises(StaleSnapshotReferenceError):
        first.read_result(result_ref)
    first.dispose()
    second.dispose()
    assert not first.database_path.exists()
    assert not second.database_path.exists()


def test_run_database_permissions_and_work_projection_are_private(
    tmp_path: Path,
    synthetic_dataset: SyntheticDataset,
) -> None:
    previous_umask = os.umask(0)
    try:
        store = RunMaterializationStore(tmp_path / "public-parent", run_id="private-run")
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(store.run_directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.database_path.stat().st_mode) == 0o600
    assert store.database_path.stat().st_mode & 0o077 == 0

    raw_customer = "customer-raw-secret"
    event = synthetic_dataset.events[0].model_copy(
        update={
            "canonical_customer_id": raw_customer,
            "text": "private-note-secret",
            "attributes": {"credit_score": 999},
            "dimensions": {
                "required_dimension": "safe-projected-value",
                "session_id": "session-secret",
                "private_note": "private-note-secret",
            },
            "measures": {"credit_score": 999},
        }
    )
    work_ref = store.begin_work()
    store.append_work_event(
        work_ref,
        event,
        dimensions={"required_dimension": "safe-projected-value"},
        measures={},
    )

    connection = duckdb.connect(str(store.database_path))
    try:
        schema = connection.execute("DESCRIBE exploration_work_events").fetchall()
        rows = connection.execute("SELECT * FROM exploration_work_events").fetchall()
    finally:
        connection.close()
    serialized = repr((schema, rows))
    persisted_bytes = b"".join(
        path.read_bytes()
        for path in (store.database_path, Path(f"{store.database_path}.wal"))
        if path.is_file()
    )
    assert "customer_key" in serialized
    for prohibited in (
        "canonical_customer_id",
        raw_customer,
        "session-secret",
        "private-note-secret",
        "credit_score",
    ):
        assert prohibited not in serialized
        assert prohibited.encode() not in persisted_bytes
    assert "safe-projected-value" in serialized
    assert store.last_work_projection_field_count == 1
    store.dispose()


def test_dispose_removes_directory_spill_and_remains_idempotent(tmp_path: Path) -> None:
    store = RunMaterializationStore(tmp_path / "spill", run_id="spill-run")
    spill_directory = Path(f"{store.database_path}.tmp")
    spill_directory.mkdir()
    (spill_directory / "spill.bin").write_bytes(b"temporary")
    run_directory = store.run_directory

    store.dispose()
    store.dispose()

    assert not spill_directory.exists()
    assert not store.database_path.exists()
    assert not run_directory.exists()


def test_dispose_retries_cleanup_after_a_transient_spill_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RunMaterializationStore(tmp_path / "retry-spill", run_id="retry-spill-run")
    spill_directory = Path(f"{store.database_path}.tmp")
    spill_directory.mkdir()
    (spill_directory / "spill.bin").write_bytes(b"temporary")
    real_rmtree = materialization_module.shutil.rmtree
    attempts = 0

    def fail_once(path, *args, **kwargs):
        nonlocal attempts
        if Path(path) == spill_directory:
            attempts += 1
            if attempts == 1:
                raise OSError("temporary cleanup failure")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(materialization_module.shutil, "rmtree", fail_once)
    with pytest.raises(OSError, match="temporary cleanup failure"):
        store.dispose()
    assert spill_directory.exists()

    store.dispose()
    assert attempts == 2
    assert not store.run_directory.exists()


def test_mid_scan_snapshot_change_invalidates_every_materialized_reference(
    tmp_path: Path,
    repository: DuckDBRepository,
    synthetic_dataset: SyntheticDataset,
) -> None:
    source_id = "search_history"
    source_events = [
        event for event in synthetic_dataset.events if event.source_id == source_id
    ]
    base = SyntheticDuckDBAdapter(
        repository, synthetic_source_manifest(source_id, synthetic_dataset.events)
    )
    adapter = _MutatingPagedAdapter(base, mutate_after_page=2)
    registry = SourceRegistry([adapter], evidence=adapter)
    scope = ExplorationSourceScope(
        source_ids=(source_id,),
        start_at=min(event.occurred_at for event in source_events),
        end_at=max(event.occurred_at for event in source_events) + timedelta(microseconds=1),
        native_page_size=1,
    )
    store = RunMaterializationStore(tmp_path / "snapshot", run_id="snapshot-run")
    reader = DataSpaceReader(
        registry=registry,
        prepared_sources=registry.prepare_paged_sources(scope),
        authorized_scope=scope,
        cursor_codec=CursorCodec(b"snapshot-secret" * 3),
        materializations=store,
    )
    prior_ref = store.store_result(
        query_ref=store.make_ref("query"),
        result_kind="summary",
        query_fingerprint="f" * 64,
        snapshot_id=reader.snapshot_id,
        source_ids=(source_id,),
        rows=[(("before",), {"item_kind": "value"})],
        matched_count=1,
        scan_complete=True,
    )

    with pytest.raises(SnapshotChangedDuringScanError, match="snapshot changed"):
        reader.scan_events(scope, consumer=lambda event: None)

    assert store.result_count == 0
    with pytest.raises(StaleSnapshotReferenceError):
        store.read_result(prior_ref)
    store.dispose()
