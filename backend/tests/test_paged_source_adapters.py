"""Native pagination and snapshot validation across source implementations."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from customer_signal.data.source_registry import SourceRegistry
from customer_signal.domain.models import CustomerEvent, IdentityEdge, IdentityRef
from customer_signal.domain.sources import EventScope
from customer_signal.exploration.contracts import (
    EventSortKey,
    ExplorationSourceScope,
    IdentityEdgeSortKey,
    IdentityPage,
    IdentityPageRequest,
    SourceEventPage,
    SourcePageRequest,
)
from customer_signal.exploration.source_adapter import (
    EventValidationSession,
    SnapshotChangedError,
    UnsupportedPaginationError,
    validate_event_page,
)
from customer_signal.onboarding.adapter import MappedTableAdapter
from customer_signal.onboarding.draft import heuristic_spec
from customer_signal.onboarding.profiler import MAX_ROWS, profile_table
from customer_signal.onboarding.spec import (
    DimensionSpec,
    FieldRule,
    IdentitySpec,
    MeasureSpec,
    SourceMappingSpec,
)
from customer_signal.synthetic.adapter import SyntheticDuckDBAdapter
from customer_signal.synthetic.manifest import synthetic_source_manifest
from customer_signal.onboarding.table_pages import open_table_page_reader
from support.in_memory_adapter import InMemorySourceAdapter


START = datetime(2026, 8, 1, tzinfo=UTC)


class _NoEvidence:
    def get_evidence(self, allowed_evidence_ids: Sequence[str]):
        del allowed_evidence_ids
        return []


def _scope(source_ids: list[str], *, page_size: int = 37) -> ExplorationSourceScope:
    return ExplorationSourceScope(
        source_ids=source_ids,
        start_at=START - timedelta(days=1),
        end_at=START + timedelta(days=400),
        native_page_size=page_size,
    )


def _spec(source_id: str) -> SourceMappingSpec:
    return SourceMappingSpec(
        source_id=source_id,
        label=f"{source_id} events",
        description="Mapped native-page contract fixture.",
        timestamp_column="occurred_at",
        timezone="UTC",
        event_type=FieldRule(const="table_event"),
        action=FieldRule(column="action"),
        topic=FieldRule(column="topic"),
        outcome=FieldRule(column="outcome"),
        text=FieldRule(const=""),
        identity=IdentitySpec(namespace="shared_identity", customer_column="customer_id"),
        dimensions={
            "optional": DimensionSpec(
                column="optional",
                semantic_type="category",
                description="Optional category.",
            ),
            "active": DimensionSpec(
                column="active",
                semantic_type="boolean",
                description="Boolean flag.",
            ),
        },
        measures={
            "signed_count": MeasureSpec(
                column="signed_count",
                semantic_type="integer",
                description="Signed count.",
                unit="count",
            ),
            "decimal_amount": MeasureSpec(
                column="decimal_amount",
                semantic_type="number",
                description="Decimal amount.",
                unit="currency",
            ),
        },
        status="approved",
    )


def _write_csv(path: Path, *, row_count: int) -> Path:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "occurred_at",
                "customer_id",
                "action",
                "topic",
                "outcome",
                "optional",
                "signed_count",
                "decimal_amount",
                "active",
            ],
        )
        writer.writeheader()
        for ordinal in range(row_count):
            # Reverse pairs to ensure physical order differs from keyset order and has ties.
            second = (row_count - ordinal - 1) // 2
            writer.writerow(
                {
                    "occurred_at": (START + timedelta(seconds=second)).isoformat(),
                    "customer_id": f"customer-{ordinal % 137:03d}",
                    "action": "opened" if ordinal % 2 else "closed",
                    "topic": "billing",
                    "outcome": "ok",
                    "optional": "" if ordinal % 3 == 0 else "present",
                    "signed_count": str(-ordinal),
                    "decimal_amount": f"{ordinal}.25",
                    "active": "true" if ordinal % 2 else "false",
                }
            )
    return path


def _as_parquet(csv_path: Path, parquet_path: Path) -> Path:
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "COPY (SELECT * FROM read_csv_auto(?)) TO ? (FORMAT PARQUET)",
            # DuckDB binds the COPY destination before parameters in its SELECT body.
            [str(parquet_path), str(csv_path)],
        )
    return parquet_path


def _table_file(tmp_path: Path, suffix: str, *, row_count: int) -> Path:
    csv_path = _write_csv(tmp_path / f"events-{suffix}.csv", row_count=row_count)
    if suffix == "csv":
        return csv_path
    return _as_parquet(csv_path, tmp_path / f"events.{suffix}")


def _event_pages(
    adapter: MappedTableAdapter, *, page_size: int
) -> list[CustomerEvent]:
    interval = adapter.describe().data_interval
    scope = ExplorationSourceScope(
        source_ids=[adapter.describe().source_id],
        start_at=interval.start_at,
        end_at=interval.end_at,
        native_page_size=page_size,
    )
    after = None
    events: list[CustomerEvent] = []
    while True:
        page = adapter.load_event_page(
            SourcePageRequest(scope=scope, after=after, page_size=page_size)
        )
        events.extend(page.items)
        if not page.has_more:
            return events
        after = page.next_key


def _identity_pages(adapter: MappedTableAdapter, *, page_size: int) -> list[IdentityEdge]:
    interval = adapter.describe().data_interval
    scope = ExplorationSourceScope(
        source_ids=[adapter.describe().source_id],
        start_at=interval.start_at,
        end_at=interval.end_at,
        native_page_size=page_size,
    )
    after = None
    edges: list[IdentityEdge] = []
    while True:
        page = adapter.load_identity_page(
            IdentityPageRequest(scope=scope, after=after, page_size=page_size)
        )
        edges.extend(page.items)
        if not page.has_more:
            return edges
        after = page.next_key


def test_registry_rejects_legacy_adapter_for_exploration(synthetic_dataset) -> None:
    source_id = "search_history"
    adapter = InMemorySourceAdapter(
        synthetic_source_manifest(source_id, synthetic_dataset.events),
        [event for event in synthetic_dataset.events if event.source_id == source_id],
        synthetic_dataset.identity_edges,
        [],
    )
    registry = SourceRegistry([adapter], evidence=_NoEvidence())

    with pytest.raises(UnsupportedPaginationError, match="unsupported_pagination"):
        registry.prepare_paged_sources(
            ExplorationSourceScope(
                source_ids=[source_id],
                start_at=synthetic_dataset.events[0].occurred_at,
                end_at=synthetic_dataset.events[-1].occurred_at + timedelta(seconds=1),
                native_page_size=17,
            )
        )


@pytest.mark.parametrize("suffix", ["csv", "parquet"])
def test_large_tables_profile_and_page_every_physical_row(
    tmp_path: Path, suffix: str
) -> None:
    source = _table_file(tmp_path, suffix, row_count=MAX_ROWS + 1)

    profile = profile_table(source)
    adapter = MappedTableAdapter.from_file(_spec("large_table"), source)
    events = _event_pages(adapter, page_size=137)
    edges = _identity_pages(adapter, page_size=31)

    assert profile.row_count == MAX_ROWS + 1
    assert profile.sampled_row_count == MAX_ROWS
    assert profile.is_sampled is True
    assert len(events) == MAX_ROWS + 1
    assert len({event.event_id for event in events}) == MAX_ROWS + 1
    assert [EventSortKey.from_event(event).as_tuple() for event in events] == sorted(
        EventSortKey.from_event(event).as_tuple() for event in events
    )
    assert len(edges) == 137
    assert [IdentityEdgeSortKey.from_edge(edge).as_tuple() for edge in edges] == sorted(
        {IdentityEdgeSortKey.from_edge(edge).as_tuple() for edge in edges}
    )
    assert events[0].dimensions["optional"] in {None, "present"}
    assert isinstance(events[0].dimensions["active"], bool)
    assert isinstance(events[0].measures["signed_count"], int)
    assert isinstance(events[0].measures["decimal_amount"], float)


def test_csv_reader_preserves_lexical_strings_until_semantic_mapping(tmp_path: Path) -> None:
    source = tmp_path / "semantic.csv"
    source.write_text(
        "occurred_at,customer_id,status,category,integer_value,number_value,"
        "bool_value,empty_category\n"
        "2026-08-01T00:00:00+00:00,000123,001,true,-7,+12.50,true,\n",
        encoding="utf-8",
    )

    _, row = next(open_table_page_reader(source).iter_rows())

    assert row["customer_id"] == "000123"
    assert row["status"] == "001"
    assert row["category"] == "true"
    assert row["integer_value"] == "-7"
    assert row["number_value"] == "+12.50"
    assert row["bool_value"] == "true"
    assert row["empty_category"] is None


def test_csv_profile_recovers_semantic_types_without_coercing_lexical_rows(
    tmp_path: Path,
) -> None:
    source = tmp_path / "profile-semantics.csv"
    source.write_text(
        "observed,customer_id,signed_count,score,category\n"
        "2026-08-01T00:00:00Z,000123,+7,1,true\n"
        "2026-08-02T00:00:00+00:00,000124,-2,1.5,false\n",
        encoding="utf-8",
    )

    profile = profile_table(source)
    columns = {column.name: column for column in profile.columns}
    _, lexical_row = next(open_table_page_reader(source).iter_rows())
    spec = heuristic_spec(
        profile,
        source_id="profile_semantics",
        label="Profile semantics",
        description="Semantic inference from lexical CSV values.",
    )

    assert lexical_row == {
        "observed": "2026-08-01T00:00:00Z",
        "customer_id": "000123",
        "signed_count": "+7",
        "score": "1",
        "category": "true",
    }
    assert columns["observed"].dtype == "datetime"
    assert columns["customer_id"].dtype == "int"
    assert columns["signed_count"].dtype == "int"
    assert columns["score"].dtype == "float"
    assert columns["category"].dtype == "bool"
    assert spec.timestamp_column == "observed"
    assert spec.identity.customer_column == "customer_id"
    assert set(spec.measures) == {"signed_count", "score"}
    assert spec.dimensions["category"].semantic_type == "boolean"


def test_csv_adapter_coerces_only_fields_with_declared_semantics(tmp_path: Path) -> None:
    source = tmp_path / "semantic.csv"
    source.write_text(
        "occurred_at,customer_id,status,category,integer_value,number_value,"
        "bool_value,empty_category\n"
        "2026-08-01T00:00:00+00:00,000123,001,true,-7,+12.50,true,\n",
        encoding="utf-8",
    )
    spec = SourceMappingSpec(
        source_id="semantic_csv",
        label="Semantic CSV",
        description="Semantic coercion contract fixture.",
        timestamp_column="occurred_at",
        timezone="UTC",
        event_type=FieldRule(const="semantic_event"),
        action=FieldRule(column="status", value_map={"001": "mapped_action"}),
        topic=FieldRule(column="category"),
        outcome=FieldRule(const="ok"),
        text=FieldRule(const=""),
        identity=IdentitySpec(
            namespace="semantic_identity",
            customer_column="customer_id",
        ),
        dimensions={
            "category": DimensionSpec(
                column="category",
                semantic_type="category",
                description="Lexical category.",
            ),
            "active": DimensionSpec(
                column="bool_value",
                semantic_type="boolean",
                description="Boolean value.",
            ),
            "optional": DimensionSpec(
                column="empty_category",
                semantic_type="category",
                description="Nullable category.",
            ),
        },
        measures={
            "count": MeasureSpec(
                column="integer_value",
                semantic_type="integer",
                description="Signed integer.",
                unit="count",
            ),
            "amount": MeasureSpec(
                column="number_value",
                semantic_type="number",
                description="Decimal number.",
                unit="currency",
            ),
        },
        status="approved",
    )

    adapter = MappedTableAdapter.from_file(spec, source)
    event = _event_pages(adapter, page_size=1)[0]

    assert event.canonical_customer_id == "000123"
    assert event.identities[0].value == "000123"
    assert event.action == "mapped_action"
    assert event.topic == "true"
    assert event.dimensions == {"category": "true", "active": True, "optional": None}
    assert event.measures == {"count": -7, "amount": 12.5}


def test_legacy_mapped_adapter_events_support_pydantic_deep_copy(tmp_path: Path) -> None:
    source = _table_file(tmp_path, "csv", row_count=2)
    adapter = MappedTableAdapter.from_file(_spec("legacy_copy"), source)
    interval = adapter.describe().data_interval

    events = adapter.load_events(
        EventScope(
            source_ids=["legacy_copy"],
            start_at=interval.start_at,
            end_at=interval.end_at,
            max_events=2,
        )
    )
    copied = events[0].model_copy(deep=True)

    assert copied == events[0]
    assert copied.model_dump(mode="json") == events[0].model_dump(mode="json")
    with pytest.raises(TypeError):
        copied.dimensions["optional"] = "mutated"


@pytest.mark.parametrize("suffix", ["csv", "parquet", "pq"])
def test_event_ids_follow_physical_ordinals_not_sorted_positions(
    tmp_path: Path, suffix: str
) -> None:
    source = _table_file(tmp_path, suffix, row_count=8)
    adapter = MappedTableAdapter.from_file(_spec("stable_ids"), source)

    first = {event.event_id: event.occurred_at for event in _event_pages(adapter, page_size=3)}
    second = {event.event_id: event.occurred_at for event in _event_pages(adapter, page_size=5)}

    assert first == second


def test_duckdb_event_and_identity_pages_use_stable_keysets(
    repository, synthetic_dataset
) -> None:
    after_event = None
    events: list[CustomerEvent] = []
    while True:
        page = repository.list_event_page(
            source_ids=["search_history", "digital_behavior"],
            start_at=synthetic_dataset.events[0].occurred_at,
            end_at=synthetic_dataset.events[-1].occurred_at + timedelta(seconds=1),
            after=after_event,
            page_size=7,
        )
        events.extend(page.items)
        if not page.has_more:
            break
        after_event = page.next_key

    after_edge = None
    edges: list[IdentityEdge] = []
    while True:
        page = repository.list_identity_page(
            source_ids=["search_history", "digital_behavior"],
            start_at=synthetic_dataset.events[0].occurred_at,
            end_at=synthetic_dataset.events[-1].occurred_at + timedelta(seconds=1),
            after=after_edge,
            page_size=5,
        )
        edges.extend(page.items)
        if not page.has_more:
            break
        after_edge = page.next_key

    event_keys = [EventSortKey.from_event(event).as_tuple() for event in events]
    edge_keys = [IdentityEdgeSortKey.from_edge(edge).as_tuple() for edge in edges]
    assert event_keys == sorted(event_keys)
    assert len(event_keys) == len(set(event_keys))
    assert edge_keys == sorted(set(edge_keys))


def test_synthetic_overlapping_identity_closures_merge_provenance(
    repository, synthetic_dataset
) -> None:
    source_ids = ["search_history", "digital_behavior"]
    adapters = [
        SyntheticDuckDBAdapter(
            repository,
            synthetic_source_manifest(source_id, synthetic_dataset.events),
        )
        for source_id in source_ids
    ]
    registry = SourceRegistry(adapters, evidence=adapters[0])
    prepared = registry.prepare_paged_sources(
        ExplorationSourceScope(
            source_ids=source_ids,
            start_at=synthetic_dataset.events[0].occurred_at,
            end_at=synthetic_dataset.events[-1].occurred_at + timedelta(seconds=1),
            native_page_size=3,
        )
    )

    assert set(prepared.snapshot_tokens) == set(source_ids)
    assert any(
        len(source_provenance) == 2
        for source_provenance in prepared.identity_resolver.provenance_sources.values()
    )


def test_six_onboarded_sources_dedupe_the_same_raw_edge(tmp_path: Path) -> None:
    source = _table_file(tmp_path, "csv", row_count=1)
    source_ids = [f"source_{index}" for index in range(6)]
    adapters = [MappedTableAdapter.from_file(_spec(source_id), source) for source_id in source_ids]
    registry = SourceRegistry(adapters, evidence=_NoEvidence())
    prepared = registry.prepare_paged_sources(_scope(source_ids, page_size=1))

    assert len(prepared.identity_resolver.edges) == 1
    assert next(iter(prepared.identity_resolver.provenance_sources.values())) == frozenset(
        source_ids
    )


class _IdentityChainAdapter:
    """Small real protocol implementation for invalid page-chain contract cases."""

    def __init__(
        self,
        base: MappedTableAdapter,
        pages: list[IdentityPage],
        *,
        mutate_after_page: int | None = None,
    ) -> None:
        self._base = base
        self._pages = pages
        self._identity_calls = 0
        self._mutate_after_page = mutate_after_page

    def describe(self):
        return self._base.describe()

    def load_events(self, scope):
        return self._base.load_events(scope)

    def load_identities(self, scope):
        return self._base.load_identities(scope)

    def snapshot_token(self) -> str:
        if (
            self._mutate_after_page is not None
            and self._identity_calls >= self._mutate_after_page
        ):
            return "mutated"
        return "original"

    def load_event_page(self, request: SourcePageRequest) -> SourceEventPage:
        return self._base.load_event_page(request)

    def load_identity_page(self, request: IdentityPageRequest) -> IdentityPage:
        del request
        page = self._pages[min(self._identity_calls, len(self._pages) - 1)]
        self._identity_calls += 1
        return page


class _SelectionBarrierAdapter:
    """Mutate another selected source while this source's identities are scanned."""

    def __init__(
        self,
        base: MappedTableAdapter,
        tokens: dict[str, str],
        *,
        mutate_source: str | None = None,
    ) -> None:
        self._base = base
        self._tokens = tokens
        self._source_id = base.describe().source_id
        self._mutate_source = mutate_source

    def describe(self):
        return self._base.describe()

    def load_events(self, scope):
        return self._base.load_events(scope)

    def load_identities(self, scope):
        return self._base.load_identities(scope)

    def snapshot_token(self) -> str:
        return self._tokens[self._source_id]

    def load_event_page(self, request: SourcePageRequest) -> SourceEventPage:
        return self._base.load_event_page(request)

    def load_identity_page(self, request: IdentityPageRequest) -> IdentityPage:
        if self._mutate_source is not None:
            self._tokens[self._mutate_source] = "mutated-during-other-source-scan"
            self._mutate_source = None
        return self._base.load_identity_page(request)


def _identity_edge(right: IdentityRef, *, left_value: str = "customer-000") -> IdentityEdge:
    return IdentityEdge(
        left=IdentityRef(namespace="shared_identity", value=left_value),
        right=right,
        link_type="EXACT",
        confidence=1.0,
        provenance="test",
    )


@pytest.mark.parametrize(
    "edges",
    [
        [
            _identity_edge(
                IdentityRef(namespace="intermediate", value="orphan"),
            )
        ],
        [
            _identity_edge(IdentityRef(namespace="canonical_customer", value="customer-000")),
            _identity_edge(IdentityRef(namespace="canonical_customer", value="customer-999")),
        ],
    ],
)
def test_prepare_rejects_zero_or_two_canonical_resolutions(
    tmp_path: Path, edges: list[IdentityEdge]
) -> None:
    base = MappedTableAdapter.from_file(
        _spec("invalid_identity"), _table_file(tmp_path, "csv", row_count=1)
    )
    adapter = _IdentityChainAdapter(
        base,
        [IdentityPage(items=edges, has_more=False, next_key=None)],
    )

    with pytest.raises(ValueError, match="exactly one canonical"):
        SourceRegistry([adapter], evidence=_NoEvidence()).prepare_paged_sources(
            _scope(["invalid_identity"])
        )


def test_prepare_rejects_duplicate_raw_edge_across_page_boundary(tmp_path: Path) -> None:
    base = MappedTableAdapter.from_file(
        _spec("duplicate_edge"), _table_file(tmp_path, "csv", row_count=1)
    )
    edge = _identity_edge(IdentityRef(namespace="canonical_customer", value="customer-000"))
    adapter = _IdentityChainAdapter(
        base,
        [
            IdentityPage(
                items=[edge],
                has_more=True,
                next_key=IdentityEdgeSortKey.from_edge(edge),
            ),
            IdentityPage(items=[edge], has_more=False, next_key=None),
        ],
    )

    with pytest.raises(ValueError, match="duplicate identity edge"):
        SourceRegistry([adapter], evidence=_NoEvidence()).prepare_paged_sources(
            _scope(["duplicate_edge"], page_size=1)
        )


def test_prepare_rejects_snapshot_mutation_after_second_identity_page(tmp_path: Path) -> None:
    base = MappedTableAdapter.from_file(
        _spec("mutated_source"), _table_file(tmp_path, "csv", row_count=2)
    )
    edges = _identity_pages(base, page_size=1)
    adapter = _IdentityChainAdapter(
        base,
        [
            IdentityPage(
                items=[edges[0]],
                has_more=True,
                next_key=IdentityEdgeSortKey.from_edge(edges[0]),
            ),
            IdentityPage(items=[edges[1]], has_more=False, next_key=None),
        ],
        mutate_after_page=2,
    )

    with pytest.raises(SnapshotChangedError, match="snapshot"):
        SourceRegistry([adapter], evidence=_NoEvidence()).prepare_paged_sources(
            _scope(["mutated_source"], page_size=1)
        )


def test_prepare_uses_a_selection_wide_snapshot_barrier(tmp_path: Path) -> None:
    source = _table_file(tmp_path, "csv", row_count=2)
    tokens = {"barrier_a": "initial", "barrier_b": "initial"}
    first = _SelectionBarrierAdapter(
        MappedTableAdapter.from_file(_spec("barrier_a"), source),
        tokens,
    )
    second = _SelectionBarrierAdapter(
        MappedTableAdapter.from_file(_spec("barrier_b"), source),
        tokens,
        mutate_source="barrier_a",
    )

    with pytest.raises(SnapshotChangedError, match="snapshot"):
        SourceRegistry([first, second], evidence=_NoEvidence()).prepare_paged_sources(
            _scope(["barrier_a", "barrier_b"], page_size=1)
        )


def test_prepare_rechecks_identity_page_state_when_model_validation_is_bypassed(
    tmp_path: Path,
) -> None:
    base = MappedTableAdapter.from_file(
        _spec("invalid_identity_state"), _table_file(tmp_path, "csv", row_count=1)
    )
    edge = _identity_pages(base, page_size=1)[0]
    invalid_page = IdentityPage.model_construct(
        items=(edge,),
        has_more=False,
        next_key=IdentityEdgeSortKey.from_edge(edge),
    )
    adapter = _IdentityChainAdapter(base, [invalid_page])

    with pytest.raises(ValueError, match="next_key"):
        SourceRegistry([adapter], evidence=_NoEvidence()).prepare_paged_sources(
            _scope(["invalid_identity_state"], page_size=1)
        )


def test_prepare_fully_revalidates_identity_items_after_model_construct_bypass(
    tmp_path: Path,
) -> None:
    base = MappedTableAdapter.from_file(
        _spec("invalid_identity_fields"), _table_file(tmp_path, "csv", row_count=1)
    )
    edge = _identity_pages(base, page_size=1)[0]
    invalid_edges = (
        edge.model_copy(update={"confidence": 1.5}),
        edge.model_copy(update={"provenance": ""}),
    )

    for invalid_edge in invalid_edges:
        invalid_page = IdentityPage.model_construct(
            items=(invalid_edge,),
            has_more=False,
            next_key=None,
        )
        adapter = _IdentityChainAdapter(base, [invalid_page])
        with pytest.raises(ValueError, match="valid identity snapshot"):
            SourceRegistry([adapter], evidence=_NoEvidence()).prepare_paged_sources(
                _scope(["invalid_identity_fields"], page_size=1)
            )


def test_independent_event_validation_sessions_can_scan_the_same_snapshot(
    tmp_path: Path,
) -> None:
    adapter = MappedTableAdapter.from_file(
        _spec("repeatable_scan"), _table_file(tmp_path, "csv", row_count=8)
    )
    registry = SourceRegistry([adapter], evidence=adapter)
    scope = ExplorationSourceScope(
        source_ids=["repeatable_scan"],
        start_at=adapter.describe().data_interval.start_at,
        end_at=adapter.describe().data_interval.end_at,
        native_page_size=3,
    )
    prepared = registry.prepare_paged_sources(scope)
    request = SourcePageRequest(scope=scope, after=None, page_size=3)
    page = adapter.load_event_page(request)

    validate_event_page(
        page, request, "repeatable_scan", prepared, EventValidationSession()
    )
    validate_event_page(
        page, request, "repeatable_scan", prepared, EventValidationSession()
    )


def test_validated_source_set_copies_manifest_context_from_the_adapter(
    tmp_path: Path,
) -> None:
    adapter = MappedTableAdapter.from_file(
        _spec("manifest_snapshot"), _table_file(tmp_path, "csv", row_count=1)
    )
    registry = SourceRegistry([adapter], evidence=adapter)
    interval = adapter.describe().data_interval
    scope = ExplorationSourceScope(
        source_ids=["manifest_snapshot"],
        start_at=interval.start_at,
        end_at=interval.end_at,
        native_page_size=1,
    )
    prepared = registry.prepare_paged_sources(scope)
    request = SourcePageRequest(scope=scope, after=None, page_size=1)
    page = adapter.load_event_page(request)

    adapter.describe().supported_topics = frozenset({"mutated_after_prepare"})

    validate_event_page(
        page, request, "manifest_snapshot", prepared, EventValidationSession()
    )


def test_event_validation_rechecks_page_state_and_order_after_validation_bypass(
    tmp_path: Path,
) -> None:
    adapter = MappedTableAdapter.from_file(
        _spec("invalid_event_state"), _table_file(tmp_path, "csv", row_count=2)
    )
    registry = SourceRegistry([adapter], evidence=adapter)
    scope = ExplorationSourceScope(
        source_ids=["invalid_event_state"],
        start_at=adapter.describe().data_interval.start_at,
        end_at=adapter.describe().data_interval.end_at,
        native_page_size=2,
    )
    prepared = registry.prepare_paged_sources(scope)
    request = SourcePageRequest(scope=scope, after=None, page_size=2)
    valid_page = adapter.load_event_page(request)
    stale_state = SourceEventPage.model_construct(
        items=valid_page.items,
        has_more=False,
        next_key=EventSortKey.from_event(valid_page.items[-1]),
    )
    unsorted = SourceEventPage.model_construct(
        items=tuple(reversed(valid_page.items)),
        has_more=False,
        next_key=None,
    )
    mutable_event = valid_page.items[0].model_copy(
        update={"dimensions": dict(valid_page.items[0].dimensions)}
    )
    mutable_nested_mapping = SourceEventPage.model_construct(
        items=(mutable_event,),
        has_more=False,
        next_key=None,
    )
    invalid_field_pages = (
        SourceEventPage.model_construct(
            items=(valid_page.items[0].model_copy(update={"evidence_id": ""}),),
            has_more=False,
            next_key=None,
        ),
        SourceEventPage.model_construct(
            items=(valid_page.items[0].model_copy(update={"action": 123}),),
            has_more=False,
            next_key=None,
        ),
        SourceEventPage.model_construct(
            items=(
                valid_page.items[0].model_copy(
                    update={"occurred_at": valid_page.items[0].occurred_at.isoformat()}
                ),
            ),
            has_more=False,
            next_key=None,
        ),
    )

    with pytest.raises(ValueError, match="next_key"):
        validate_event_page(
            stale_state,
            request,
            "invalid_event_state",
            prepared,
            EventValidationSession(),
        )
    with pytest.raises(ValueError, match="sorted"):
        validate_event_page(
            unsorted,
            request,
            "invalid_event_state",
            prepared,
            EventValidationSession(),
        )
    with pytest.raises(ValueError, match="immutable"):
        validate_event_page(
            mutable_nested_mapping,
            request,
            "invalid_event_state",
            prepared,
            EventValidationSession(),
        )
    for invalid_field_page in invalid_field_pages:
        with pytest.raises(ValueError, match="valid event snapshot"):
            validate_event_page(
                invalid_field_page,
                request,
                "invalid_event_state",
                prepared,
                EventValidationSession(),
            )


def test_event_validation_binds_page_to_source_request_size_and_after_key(
    tmp_path: Path,
) -> None:
    adapter = MappedTableAdapter.from_file(
        _spec("request_binding"), _table_file(tmp_path, "csv", row_count=3)
    )
    registry = SourceRegistry([adapter], evidence=adapter)
    interval = adapter.describe().data_interval
    scope = ExplorationSourceScope(
        source_ids=["request_binding"],
        start_at=interval.start_at,
        end_at=interval.end_at,
        native_page_size=3,
    )
    prepared = registry.prepare_paged_sources(scope)
    request = SourcePageRequest(scope=scope, after=None, page_size=3)
    page = adapter.load_event_page(request)
    wrong_source_event = page.items[0].model_copy(update={"source_id": "other_source"})
    wrong_source_page = SourceEventPage.model_construct(
        items=(wrong_source_event,),
        has_more=False,
        next_key=None,
    )
    empty_page = SourceEventPage(items=[], has_more=False, next_key=None)
    invalid_requests = (
        SourcePageRequest.model_construct(scope=scope, after=None, page_size=0),
        SourcePageRequest.model_construct(
            scope=scope.model_copy(update={"native_page_size": 0}),
            after=None,
            page_size=1,
        ),
    )

    for invalid_request in invalid_requests:
        with pytest.raises(ValueError, match="valid SourcePageRequest"):
            validate_event_page(
                empty_page,
                invalid_request,
                "request_binding",
                prepared,
                EventValidationSession(),
            )
    with pytest.raises(ValueError, match="expected source"):
        validate_event_page(
            wrong_source_page,
            request,
            "request_binding",
            prepared,
            EventValidationSession(),
        )
    with pytest.raises(ValueError, match="page_size"):
        validate_event_page(
            page,
            request.model_copy(update={"page_size": 1}),
            "request_binding",
            prepared,
            EventValidationSession(),
        )
    with pytest.raises(ValueError, match="after"):
        validate_event_page(
            page,
            request.model_copy(update={"after": EventSortKey.from_event(page.items[0])}),
            "request_binding",
            prepared,
            EventValidationSession(),
        )


def test_event_validation_requires_exact_session_cursor_continuity(
    tmp_path: Path,
) -> None:
    adapter = MappedTableAdapter.from_file(
        _spec("cursor_continuity"), _table_file(tmp_path, "csv", row_count=4)
    )
    registry = SourceRegistry([adapter], evidence=adapter)
    interval = adapter.describe().data_interval
    scope = ExplorationSourceScope(
        source_ids=["cursor_continuity"],
        start_at=interval.start_at,
        end_at=interval.end_at,
        native_page_size=1,
    )
    prepared = registry.prepare_paged_sources(scope)
    first_request = SourcePageRequest(scope=scope, after=None, page_size=1)
    first_page = adapter.load_event_page(first_request)
    assert first_page.next_key is not None
    second_request = SourcePageRequest(
        scope=scope,
        after=first_page.next_key,
        page_size=1,
    )
    second_page = adapter.load_event_page(second_request)
    assert second_page.next_key is not None
    forward_skip_request = SourcePageRequest(
        scope=scope,
        after=second_page.next_key,
        page_size=1,
    )
    forward_skip_page = adapter.load_event_page(forward_skip_request)
    backtrack_request = SourcePageRequest(
        scope=scope,
        after=EventSortKey(
            occurred_at=first_page.items[0].occurred_at - timedelta(microseconds=1),
            source_id="cursor_continuity",
            event_id=first_page.items[0].event_id,
        ),
        page_size=1,
    )
    reset_request = SourcePageRequest(scope=scope, after=None, page_size=1)

    valid_session = EventValidationSession()
    validate_event_page(
        first_page,
        first_request,
        "cursor_continuity",
        prepared,
        valid_session,
    )
    validate_event_page(
        second_page,
        second_request,
        "cursor_continuity",
        prepared,
        valid_session,
    )

    with pytest.raises(ValueError, match="first page.*after"):
        validate_event_page(
            second_page,
            second_request,
            "cursor_continuity",
            prepared,
            EventValidationSession(),
        )

    for invalid_request, invalid_page in (
        (reset_request, second_page),
        (forward_skip_request, forward_skip_page),
        (backtrack_request, second_page),
    ):
        session = EventValidationSession()
        validate_event_page(
            first_page,
            first_request,
            "cursor_continuity",
            prepared,
            session,
        )
        with pytest.raises(ValueError, match="previous page"):
            validate_event_page(
                invalid_page,
                invalid_request,
                "cursor_continuity",
                prepared,
                session,
            )


def test_event_validation_session_pins_each_source_scope(tmp_path: Path) -> None:
    adapter = MappedTableAdapter.from_file(
        _spec("scope_continuity"), _table_file(tmp_path, "csv", row_count=4)
    )
    registry = SourceRegistry([adapter], evidence=adapter)
    interval = adapter.describe().data_interval
    scope = ExplorationSourceScope(
        source_ids=["scope_continuity"],
        start_at=interval.start_at,
        end_at=interval.end_at,
        native_page_size=1,
    )
    prepared = registry.prepare_paged_sources(scope)
    first_request = SourcePageRequest(scope=scope, after=None, page_size=1)
    first_page = adapter.load_event_page(first_request)
    assert first_page.next_key is not None

    changed_scopes = (
        scope.model_copy(update={"start_at": scope.start_at - timedelta(microseconds=1)}),
        scope.model_copy(update={"end_at": scope.end_at + timedelta(microseconds=1)}),
        scope.model_copy(update={"native_page_size": 2}),
        ExplorationSourceScope.model_construct(
            source_ids=scope.source_ids,
            start_at=scope.start_at - timedelta(microseconds=1),
            end_at=scope.end_at,
            native_page_size=scope.native_page_size,
        ),
    )

    for changed_scope in changed_scopes:
        second_request = SourcePageRequest(
            scope=changed_scope,
            after=first_page.next_key,
            page_size=1,
        )
        second_page = adapter.load_event_page(second_request)
        session = EventValidationSession()
        validate_event_page(
            first_page,
            first_request,
            "scope_continuity",
            prepared,
            session,
        )
        pinned_scope = session._scope_by_source["scope_continuity"]
        assert pinned_scope == scope
        assert pinned_scope is not first_request.scope

        with pytest.raises(ValueError, match="scope"):
            validate_event_page(
                second_page,
                second_request,
                "scope_continuity",
                prepared,
                session,
            )


def test_one_event_validation_session_rejects_global_event_and_evidence_collisions(
    tmp_path: Path,
) -> None:
    source = _table_file(tmp_path, "csv", row_count=1)
    first = MappedTableAdapter.from_file(_spec("collision_a"), source)
    second = MappedTableAdapter.from_file(_spec("collision_b"), source)
    scope = _scope(["collision_a", "collision_b"])
    registry = SourceRegistry([first, second], evidence=_NoEvidence())
    prepared = registry.prepare_paged_sources(scope)
    first_scope = scope.model_copy(update={"source_ids": ("collision_a",)})
    second_scope = scope.model_copy(update={"source_ids": ("collision_b",)})
    first_request = SourcePageRequest(scope=first_scope, after=None, page_size=10)
    second_request = SourcePageRequest(scope=second_scope, after=None, page_size=10)
    first_page = first.load_event_page(first_request)
    second_page = second.load_event_page(second_request)
    collided = second_page.items[0].model_copy(
        update={
            "event_id": first_page.items[0].event_id,
            "evidence_id": first_page.items[0].evidence_id,
        }
    )
    session = EventValidationSession()

    validate_event_page(first_page, first_request, "collision_a", prepared, session)
    with pytest.raises(ValueError, match="event_id|evidence_id"):
        validate_event_page(
            SourceEventPage(items=[collided], has_more=False, next_key=None),
            second_request,
            "collision_b",
            prepared,
            session,
        )
