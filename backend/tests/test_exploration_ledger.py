from __future__ import annotations

from pathlib import Path

import pytest

from customer_signal.exploration.ledger import (
    ExplorationLedger,
    ExplorationLedgerError,
    ToolPageObservation,
)
from customer_signal.exploration.materialization import (
    ForeignRunReferenceError,
    RunMaterializationStore,
    StaleSnapshotReferenceError,
)
from customer_signal.exploration.tool_contracts import PublicSourceCatalogItem


def _materializations(tmp_path: Path, run_id: str = "run-1") -> RunMaterializationStore:
    return RunMaterializationStore(tmp_path / run_id, run_id=run_id)


def _result(
    store: RunMaterializationStore,
    *,
    result_kind: str = "catalog_sources",
    scan_complete: bool = True,
) -> tuple[str, str]:
    query_ref = store.make_ref("query")
    result_ref = store.store_result(
        query_ref=query_ref,
        result_kind=result_kind,
        query_fingerprint="f" * 64,
        snapshot_id="s" * 64,
        source_ids=("source-a",),
        rows=(),
        matched_count=1 if scan_complete else None,
        scan_complete=scan_complete,
        partial_message=None if scan_complete else "interrupted",
        remaining_branches=() if scan_complete else ("source-a",),
        retry_action=None if scan_complete else "restart_query_without_cursor",
    )
    return query_ref, result_ref


def _page(
    store: RunMaterializationStore,
    *,
    query_ref: str,
    result_ref: str,
    index: int,
    has_more: bool,
    parent: str | None = None,
    request_cursor_fingerprint: str | None = None,
    page_ref: str | None = None,
    result_kind: str = "catalog_sources",
) -> ToolPageObservation:
    return ToolPageObservation(
        tool_name="inspect_data_space",
        result_kind=result_kind,
        request_json='{"page_size":1,"source_ids":[],"view":"sources"}',
        source_ids=("source-a",),
        query_ref=query_ref,
        result_ref=result_ref,
        page_ref=page_ref
        or store.make_ref("page", stable_value=f"{result_ref}\0{index}"),
        parent_page_ref=parent,
        request_cursor_fingerprint=request_cursor_fingerprint,
        next_cursor_fingerprint=(f"next-{index}" if has_more else None),
        page_index=index,
        page_size=1,
        returned_count=1,
        matched_count=1,
        has_more=has_more,
        scan_complete=True,
        snapshot_id="s" * 64,
        query_fingerprint="f" * 64,
        items=(
            PublicSourceCatalogItem(
                source_id="source-a",
                label="Source A",
                observed_start_at=None,
                observed_end_at=None,
                row_count=1,
                event_types=("event",),
                actions=("act",),
                topics=("topic",),
                outcomes=("done",),
            ),
        ),
    )


def test_ledger_keeps_result_ref_and_orders_pages(tmp_path: Path) -> None:
    store = _materializations(tmp_path)
    query_ref, result_ref = _result(store)
    ledger = ExplorationLedger(
        run_id="run-1", materializations=store, authorized_source_ids=("source-a",)
    )

    first = ledger.record_page(
        _page(store, query_ref=query_ref, result_ref=result_ref, index=0, has_more=True)
    )
    second = ledger.record_page(
        _page(
            store,
            query_ref=query_ref,
            result_ref=result_ref,
            index=1,
            has_more=False,
            parent=first.page_ref,
            request_cursor_fingerprint=first.next_cursor_fingerprint,
        )
    )

    assert first.query_ref == second.query_ref
    assert first.result_ref == second.result_ref
    assert first.page_ref != second.page_ref
    assert ledger.is_complete(first.query_ref) is True
    assert [page.page_index for page in ledger.require_query(query_ref).pages] == [0, 1]


def test_same_cursor_is_an_idempotent_read(tmp_path: Path) -> None:
    store = _materializations(tmp_path)
    query_ref, result_ref = _result(store)
    ledger = ExplorationLedger(
        run_id="run-1", materializations=store, authorized_source_ids=("source-a",)
    )
    first = ledger.record_page(
        _page(store, query_ref=query_ref, result_ref=result_ref, index=0, has_more=True)
    )
    second = _page(
        store,
        query_ref=query_ref,
        result_ref=result_ref,
        index=1,
        has_more=False,
        parent=first.page_ref,
        request_cursor_fingerprint=first.next_cursor_fingerprint,
    )

    assert ledger.record_page(second) == ledger.record_page(second)


def test_same_cursor_with_different_result_is_rejected(tmp_path: Path) -> None:
    store = _materializations(tmp_path)
    query_ref, result_ref = _result(store)
    ledger = ExplorationLedger(run_id="run-1", materializations=store)
    first = ledger.record_page(
        _page(store, query_ref=query_ref, result_ref=result_ref, index=0, has_more=True)
    )
    second = _page(
        store,
        query_ref=query_ref,
        result_ref=result_ref,
        index=1,
        has_more=False,
        parent=first.page_ref,
        request_cursor_fingerprint=first.next_cursor_fingerprint,
    )
    ledger.record_page(second)

    forged = second.model_copy(update={"returned_count": 0, "items": ()})
    with pytest.raises(ExplorationLedgerError, match="same cursor"):
        ledger.record_page(forged)


@pytest.mark.parametrize("bad_index", [1, 3])
def test_page_index_gaps_are_rejected(tmp_path: Path, bad_index: int) -> None:
    store = _materializations(tmp_path)
    query_ref, result_ref = _result(store)
    ledger = ExplorationLedger(run_id="run-1", materializations=store)

    with pytest.raises(ExplorationLedgerError, match="page index"):
        ledger.record_page(
            _page(
                store,
                query_ref=query_ref,
                result_ref=result_ref,
                index=bad_index,
                has_more=False,
                parent=store.make_ref("page", stable_value="missing-parent"),
                request_cursor_fingerprint="missing-cursor",
            )
        )


def test_wrong_parent_page_is_rejected(tmp_path: Path) -> None:
    store = _materializations(tmp_path)
    query_ref, result_ref = _result(store)
    ledger = ExplorationLedger(run_id="run-1", materializations=store)
    first = ledger.record_page(
        _page(store, query_ref=query_ref, result_ref=result_ref, index=0, has_more=True)
    )

    with pytest.raises(ExplorationLedgerError, match="parent page"):
        ledger.record_page(
            _page(
                store,
                query_ref=query_ref,
                result_ref=result_ref,
                index=1,
                has_more=False,
                parent=store.make_ref("page", stable_value="wrong"),
                request_cursor_fingerprint=first.next_cursor_fingerprint,
            )
        )


def test_foreign_run_result_is_rejected(tmp_path: Path) -> None:
    store = _materializations(tmp_path, "run-1")
    foreign = _materializations(tmp_path, "run-2")
    foreign_query, foreign_result = _result(foreign)
    ledger = ExplorationLedger(run_id="run-1", materializations=store)

    with pytest.raises(ForeignRunReferenceError):
        ledger.record_page(
            _page(
                store,
                query_ref=foreign_query,
                result_ref=foreign_result,
                index=0,
                has_more=False,
            )
        )


def test_snapshot_reset_invalidates_all_refs_and_catalog_completion(
    tmp_path: Path,
) -> None:
    store = _materializations(tmp_path)
    ledger = ExplorationLedger(
        run_id="run-1", materializations=store, authorized_source_ids=("source-a",)
    )
    for kind in ("catalog_sources", "catalog_fields"):
        query_ref, result_ref = _result(store, result_kind=kind)
        ledger.record_page(
            _page(
                store,
                query_ref=query_ref,
                result_ref=result_ref,
                index=0,
                has_more=False,
                result_kind=kind,
            )
        )
    old_refs = ledger.public_snapshot().completed_query_refs
    assert ledger.catalog_complete is True

    ledger.reset_for_snapshot_change()

    assert ledger.public_snapshot().completed_query_refs == ()
    assert ledger.catalog_complete is False
    for ref in old_refs:
        with pytest.raises(StaleSnapshotReferenceError):
            ledger.require_query(ref)


def test_catalog_completion_requires_every_bound_active_source(tmp_path: Path) -> None:
    store = _materializations(tmp_path)
    ledger = ExplorationLedger(
        run_id="run-1",
        materializations=store,
        authorized_source_ids=("source-a", "source-b"),
    )
    for kind in ("catalog_sources", "catalog_fields"):
        query_ref, result_ref = _result(store, result_kind=kind)
        ledger.record_page(
            _page(
                store,
                query_ref=query_ref,
                result_ref=result_ref,
                index=0,
                has_more=False,
                result_kind=kind,
            )
        )

    assert ledger.catalog_sources_complete is False
    assert ledger.catalog_fields_complete is False
    assert ledger.catalog_complete is False


def test_external_generation_change_makes_query_and_snapshot_stale(tmp_path: Path) -> None:
    store = _materializations(tmp_path)
    query_ref, result_ref = _result(store)
    ledger = ExplorationLedger(
        run_id="run-1", materializations=store, authorized_source_ids=("source-a",)
    )
    ledger.record_page(
        _page(
            store,
            query_ref=query_ref,
            result_ref=result_ref,
            index=0,
            has_more=False,
        )
    )

    store.invalidate_snapshot()

    with pytest.raises(StaleSnapshotReferenceError):
        ledger.require_query(query_ref)
    with pytest.raises(StaleSnapshotReferenceError):
        ledger.public_snapshot()
    with pytest.raises(StaleSnapshotReferenceError):
        ledger.complete_query_refs()


def test_public_snapshot_excludes_cursor_and_canonical_customer_id(tmp_path: Path) -> None:
    store = _materializations(tmp_path)
    query_ref, result_ref = _result(store)
    ledger = ExplorationLedger(run_id="run-1", materializations=store)
    ledger.public_customer_ref("customer-secret")
    ledger.record_page(
        _page(store, query_ref=query_ref, result_ref=result_ref, index=0, has_more=True)
    )

    serialized = ledger.public_snapshot().model_dump_json()

    assert "customer-secret" not in serialized
    assert "next-0" not in serialized
    assert "cursor" not in serialized


def test_cohort_and_customer_authorization_delegate_to_run_store(tmp_path: Path) -> None:
    store = _materializations(tmp_path)
    _, result_ref = _result(store)
    ledger = ExplorationLedger(run_id="run-1", materializations=store)
    cohort_ref = store.store_cohort(
        result_ref,
        ("customer-secret",),
        stable_label="authorized",
    )
    customer_ref = ledger.public_customer_ref("customer-secret")

    authorized = ledger.authorize_cohort(cohort_ref)

    assert len(authorized) == 1
    assert next(iter(authorized)).startswith("ck_")
    assert ledger.resolve_customer_ref(customer_ref) == next(iter(authorized))


def test_materialized_evidence_binds_one_same_run_parent(tmp_path: Path) -> None:
    store = _materializations(tmp_path)
    _, parent_result = _result(store, result_kind="sequence_sequence")
    query_ref = store.make_ref("query")

    with pytest.raises(ValueError, match="parent_result_ref"):
        store.store_result(
            query_ref=query_ref,
            result_kind="evidence",
            query_fingerprint="e" * 64,
            snapshot_id="s" * 64,
            source_ids=("source-a",),
            rows=(),
            matched_count=0,
            scan_complete=True,
        )

    evidence_result = store.store_result(
        query_ref=query_ref,
        result_kind="evidence",
        query_fingerprint="e" * 64,
        snapshot_id="s" * 64,
        source_ids=("source-a",),
        rows=(),
        matched_count=0,
        scan_complete=True,
        parent_result_ref=parent_result,
    )

    assert store.read_result(evidence_result).parent_result_ref == parent_result
    with pytest.raises(ValueError, match="parent_result_ref"):
        store.store_result(
            query_ref=store.make_ref("query"),
            result_kind="summary",
            query_fingerprint="x" * 64,
            snapshot_id="s" * 64,
            source_ids=("source-a",),
            rows=(),
            matched_count=0,
            scan_complete=True,
            parent_result_ref=parent_result,
        )

    foreign = _materializations(tmp_path, "foreign-run")
    with pytest.raises(ForeignRunReferenceError):
        foreign.store_result(
            query_ref=foreign.make_ref("query"),
            result_kind="evidence",
            query_fingerprint="e" * 64,
            snapshot_id="s" * 64,
            source_ids=("source-a",),
            rows=(),
            matched_count=0,
            scan_complete=True,
            parent_result_ref=parent_result,
        )


def test_ledger_rejects_evidence_parent_unrelated_to_materialized_binding(
    tmp_path: Path,
) -> None:
    store = _materializations(tmp_path)
    ledger = ExplorationLedger(
        run_id="run-1", materializations=store, authorized_source_ids=("source-a",)
    )
    parent_query, parent_result = _result(store, result_kind="sequence_sequence")
    ledger.record_page(
        _page(
            store,
            query_ref=parent_query,
            result_ref=parent_result,
            index=0,
            has_more=False,
            result_kind="sequence_sequence",
        ).model_copy(update={"tool_name": "analyze_event_sequences"})
    )
    unrelated_query, unrelated_result = _result(store, result_kind="summary")
    ledger.record_page(
        _page(
            store,
            query_ref=unrelated_query,
            result_ref=unrelated_result,
            index=0,
            has_more=False,
            result_kind="summary",
        ).model_copy(update={"tool_name": "summarize_events"})
    )
    evidence_query = store.make_ref("query")
    evidence_result = store.store_result(
        query_ref=evidence_query,
        result_kind="evidence",
        query_fingerprint="f" * 64,
        snapshot_id="s" * 64,
        source_ids=("source-a",),
        rows=(),
        matched_count=0,
        scan_complete=True,
        parent_result_ref=parent_result,
    )
    forged = _page(
        store,
        query_ref=evidence_query,
        result_ref=evidence_result,
        index=0,
        has_more=False,
        result_kind="evidence",
    ).model_copy(
        update={
            "tool_name": "read_event_evidence",
            "parent_result_ref": unrelated_result,
            "returned_count": 0,
            "items": (),
            "matched_count": 0,
        }
    )

    with pytest.raises(ExplorationLedgerError, match="parent_result_ref"):
        ledger.record_page(forged)


def test_ledger_rejects_unobserved_same_run_evidence_parent(tmp_path: Path) -> None:
    store = _materializations(tmp_path)
    ledger = ExplorationLedger(
        run_id="run-1", materializations=store, authorized_source_ids=("source-a",)
    )
    _, unobserved_parent = _result(store, result_kind="sequence_sequence")
    evidence_query = store.make_ref("query")
    evidence_result = store.store_result(
        query_ref=evidence_query,
        result_kind="evidence",
        query_fingerprint="f" * 64,
        snapshot_id="s" * 64,
        source_ids=("source-a",),
        rows=(),
        matched_count=0,
        scan_complete=True,
        parent_result_ref=unobserved_parent,
    )
    observation = _page(
        store,
        query_ref=evidence_query,
        result_ref=evidence_result,
        index=0,
        has_more=False,
        result_kind="evidence",
    ).model_copy(
        update={
            "tool_name": "read_event_evidence",
            "parent_result_ref": unobserved_parent,
            "returned_count": 0,
            "items": (),
            "matched_count": 0,
        }
    )

    with pytest.raises(ExplorationLedgerError, match="parent_result_ref"):
        ledger.record_page(observation)


def test_ledger_rejects_parent_on_non_evidence_result(tmp_path: Path) -> None:
    store = _materializations(tmp_path)
    ledger = ExplorationLedger(
        run_id="run-1", materializations=store, authorized_source_ids=("source-a",)
    )
    query_ref, result_ref = _result(store, result_kind="summary")
    _, unrelated_result = _result(store, result_kind="sequence_sequence")
    forged = _page(
        store,
        query_ref=query_ref,
        result_ref=result_ref,
        index=0,
        has_more=False,
        result_kind="summary",
    ).model_copy(
        update={
            "tool_name": "summarize_events",
            "parent_result_ref": unrelated_result,
        }
    )

    with pytest.raises(ExplorationLedgerError, match="parent_result_ref"):
        ledger.record_page(forged)


def test_ledger_rejects_evidence_parent_change_between_pages(tmp_path: Path) -> None:
    store = _materializations(tmp_path)
    ledger = ExplorationLedger(
        run_id="run-1", materializations=store, authorized_source_ids=("source-a",)
    )
    parent_query, parent_result = _result(store, result_kind="sequence_sequence")
    ledger.record_page(
        _page(
            store,
            query_ref=parent_query,
            result_ref=parent_result,
            index=0,
            has_more=False,
            result_kind="sequence_sequence",
        ).model_copy(update={"tool_name": "analyze_event_sequences"})
    )
    _, unrelated_result = _result(store, result_kind="summary")
    evidence_query = store.make_ref("query")
    evidence_result = store.store_result(
        query_ref=evidence_query,
        result_kind="evidence",
        query_fingerprint="f" * 64,
        snapshot_id="s" * 64,
        source_ids=("source-a",),
        rows=(),
        matched_count=0,
        scan_complete=True,
        parent_result_ref=parent_result,
    )
    first = ledger.record_page(
        _page(
            store,
            query_ref=evidence_query,
            result_ref=evidence_result,
            index=0,
            has_more=True,
            result_kind="evidence",
        ).model_copy(
            update={
                "tool_name": "read_event_evidence",
                "parent_result_ref": parent_result,
                "returned_count": 0,
                "items": (),
                "matched_count": 0,
            }
        )
    )
    changed = _page(
        store,
        query_ref=evidence_query,
        result_ref=evidence_result,
        index=1,
        has_more=False,
        parent=first.page_ref,
        request_cursor_fingerprint=first.next_cursor_fingerprint,
        result_kind="evidence",
    ).model_copy(
        update={
            "tool_name": "read_event_evidence",
            "parent_result_ref": unrelated_result,
            "returned_count": 0,
            "items": (),
            "matched_count": 0,
        }
    )

    with pytest.raises(ExplorationLedgerError, match="parent_result_ref"):
        ledger.record_page(changed)
