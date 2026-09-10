from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from customer_signal.exploration.contracts import ExplorationSourceScope
from customer_signal.exploration.ledger import ExplorationLedger, ToolPageObservation
from customer_signal.exploration.materialization import RunMaterializationStore
from customer_signal.exploration.report_contracts import (
    AbandonedBranch,
    ExplorationCoverage,
    ExplorationMetric,
    ExplorationPartialReport,
    ExplorationReport,
    ExplorationReportSubmission,
    Finding,
    Recommendation,
)
from customer_signal.exploration.report_validator import (
    ExplorationReportValidationError,
    validate_exploration_report,
)
from customer_signal.exploration.tool_contracts import (
    ExplorationFieldRef,
    PublicExplorationEvidenceEvent,
    PublicFieldCatalogItem,
    PublicMetricValue,
    PublicSequenceItem,
    PublicSourceCatalogItem,
    PublicSummaryItem,
)
from customer_signal.exploration.tools import ExplorationTools


SOURCE_A = "source_a"
SOURCE_B = "source_b"
SOURCE_C = "source_c"
NOW = datetime(2026, 8, 25, tzinfo=UTC)


def _scope(
    source_ids: tuple[str, ...] = (SOURCE_A, SOURCE_B),
) -> ExplorationSourceScope:
    return ExplorationSourceScope(
        source_ids=source_ids,
        start_at=datetime(2026, 8, 18, tzinfo=UTC),
        end_at=datetime(2026, 9, 1, tzinfo=UTC),
        native_page_size=50,
    )


def _request_json(kind: str, source_ids: tuple[str, ...]) -> str:
    if kind == "catalog_sources":
        return '{"page_size":50,"source_ids":[],"view":"sources"}'
    if kind == "catalog_fields":
        return (
            '{"page_size":50,"source_ids":["source_a","source_b"],'
            '"view":"fields"}'
        )
    return '{"page_size":50,"source_ids":["' + '","'.join(source_ids) + '"]}'


def _record_result(
    ledger: ExplorationLedger,
    store: RunMaterializationStore,
    *,
    result_kind: str,
    source_ids: tuple[str, ...],
    items: tuple[object, ...],
    has_more: bool = False,
    scan_complete: bool = True,
    parent_result_ref: str | None = None,
) -> tuple[str, str]:
    query_ref = store.make_ref("query")
    result_ref = store.store_result(
        query_ref=query_ref,
        result_kind=result_kind,
        query_fingerprint=(result_kind[0] * 64),
        snapshot_id="s" * 64,
        source_ids=source_ids,
        rows=tuple(((index,), item) for index, item in enumerate(items)),
        matched_count=len(items) if scan_complete else None,
        scan_complete=scan_complete,
        partial_message=None if scan_complete else "source interrupted",
        remaining_branches=() if scan_complete else (source_ids[0],),
        retry_action=None if scan_complete else "restart_query_without_cursor",
        parent_result_ref=parent_result_ref,
    )
    page_ref = store.make_ref("page", stable_value=f"{result_ref}\0{0}")
    ledger.record_page(
        ToolPageObservation(
            tool_name=(
                "inspect_data_space"
                if result_kind.startswith("catalog_")
                else "summarize_events"
                if result_kind == "summary"
                else "analyze_event_sequences"
                if result_kind.startswith("sequence_")
                else "read_event_evidence"
            ),
            result_kind=result_kind,
            request_json=_request_json(result_kind, source_ids),
            source_ids=source_ids,
            query_ref=query_ref,
            result_ref=result_ref,
            page_ref=page_ref,
            parent_page_ref=None,
            request_cursor_fingerprint=None,
            next_cursor_fingerprint="issued-next" if has_more else None,
            page_index=0,
            page_size=50,
            returned_count=len(items),
            matched_count=len(items) if scan_complete else None,
            has_more=has_more,
            scan_complete=scan_complete,
            snapshot_id="s" * 64,
            query_fingerprint=(result_kind[0] * 64),
            parent_result_ref=parent_result_ref,
            items=items,
        )
    )
    return query_ref, result_ref


def _catalogs(
    ledger: ExplorationLedger,
    store: RunMaterializationStore,
    *,
    include_sources: bool = True,
    include_fields: bool = True,
) -> None:
    if include_sources:
        _record_result(
            ledger,
            store,
            result_kind="catalog_sources",
            source_ids=(SOURCE_A, SOURCE_B),
            items=tuple(
                PublicSourceCatalogItem(
                    source_id=source_id,
                    label=source_id,
                    observed_start_at=NOW,
                    observed_end_at=NOW,
                    row_count=10,
                    event_types=("event",),
                    actions=("act",),
                    topics=("topic",),
                    outcomes=("done",),
                )
                for source_id in (SOURCE_A, SOURCE_B)
            ),
        )
    if include_fields:
        _record_result(
            ledger,
            store,
            result_kind="catalog_fields",
            source_ids=(SOURCE_A, SOURCE_B),
            items=tuple(
                PublicFieldCatalogItem(
                    source_id=source_id,
                    scope="dimension",
                    name="variant",
                    data_type="string",
                    nullable=False,
                    value_access="enumerable",
                    missing_rate=0.0,
                )
                for source_id in (SOURCE_A, SOURCE_B)
            ),
        )


def _complete_ledger(tmp_path: Path) -> tuple[ExplorationLedger, dict[str, str]]:
    store = RunMaterializationStore(tmp_path / "materializations", run_id="run-1")
    ledger = ExplorationLedger(
        "run-1", store, authorized_source_ids=(SOURCE_A, SOURCE_B)
    )
    _catalogs(ledger, store)
    summary_query, summary_result = _record_result(
        ledger,
        store,
        result_kind="summary",
        source_ids=(SOURCE_A, SOURCE_B),
        items=(
            PublicSummaryItem(
                bucket_start=None,
                group_values=(),
                metrics=(
                    PublicMetricValue(
                        name="distinct_customer_count",
                        value=42,
                        unit="customers",
                    ),
                ),
                cohort_ref=store.make_ref("cohort", stable_value="summary-cohort"),
            ),
        ),
    )
    sequence_query, sequence_result = _record_result(
        ledger,
        store,
        result_kind="sequence_sequence",
        source_ids=(SOURCE_A, SOURCE_B),
        items=(
            PublicSequenceItem(
                mode="sequence",
                customer_ref=store.make_ref("customer", stable_value="customer"),
                cohort_ref=store.make_ref("cohort", stable_value="sequence-cohort"),
                occurrence_count=None,
                completed_step_count=2,
                total_step_count=2,
                completed_step_ids=("start", "finish"),
                dropoff_after_step_id=None,
                first_match_at=NOW,
                last_match_at=NOW,
                span_minutes=0.0,
            ),
        ),
    )
    evidence_query, evidence_result = _record_result(
        ledger,
        store,
        result_kind="evidence",
        source_ids=(SOURCE_A, SOURCE_B),
        parent_result_ref=sequence_result,
        items=(
            PublicExplorationEvidenceEvent(
                evidence_id="evidence-1",
                source_id=SOURCE_A,
                occurred_at=NOW,
                event_type="event",
                action="act",
                topic="topic",
                outcome="done",
                customer_ref=store.make_ref("customer", stable_value="customer"),
                semantic_fields=(
                    {
                        "field": ExplorationFieldRef(
                            scope="dimension", name="variant", source_id=SOURCE_A
                        ),
                        "value": "before",
                    },
                ),
            ),
        ),
    )
    return ledger, {
        "summary_query": summary_query,
        "summary_result": summary_result,
        "sequence_query": sequence_query,
        "sequence_result": sequence_result,
        "evidence_query": evidence_query,
        "evidence_result": evidence_result,
    }


def _valid_report(ledger: ExplorationLedger, refs: dict[str, str]) -> ExplorationReport:
    return ExplorationReport(
        report_version="1",
        executive_summary="두 Source에서 반복되는 이탈 패턴과 개선 기회를 확인했습니다.",
        findings=(
            Finding(
                finding_id="finding-1",
                title="연결 여정의 반복 이탈",
                observation="완주한 집계에서 고유 고객 42명이 동일한 순서를 보였습니다.",
                hypothesis="단계 설명 부족이 이탈 가능성을 높였을 수 있습니다.",
                confidence="high",
                source_ids=(SOURCE_A, SOURCE_B),
                query_refs=(
                    refs["summary_query"],
                    refs["sequence_query"],
                    refs["evidence_query"],
                ),
                result_refs=(
                    refs["summary_result"],
                    refs["sequence_result"],
                    refs["evidence_result"],
                ),
                evidence_ids=("evidence-1",),
                metrics=(
                    ExplorationMetric(
                        name="distinct_customer_count",
                        value=42,
                        unit="customers",
                        result_ref=refs["summary_result"],
                    ),
                ),
                recommendations=(
                    Recommendation(
                        action="다음 단계와 동의 이유를 진입 전에 안내합니다.",
                        expected_direction="decrease",
                        target_metric="journey_dropoff_rate",
                    ),
                ),
                limitations=("합성 관찰 데이터이므로 실제 실험으로 확인해야 합니다.",),
            ),
        ),
        coverage=ExplorationCoverage(
            completed_query_refs=tuple(sorted(ledger.complete_query_refs())),
            abandoned_branches=(),
        ),
        causal_limitations=(
            "관찰된 연관성은 인과를 증명하지 않으며 개선안은 실험 검증이 필요합니다.",
        ),
    )


def test_valid_report_passes_without_mutation(tmp_path: Path) -> None:
    ledger, refs = _complete_ledger(tmp_path)
    report = _valid_report(ledger, refs)

    validated = validate_exploration_report(report, ledger, _scope())

    assert validated is report


def test_report_rejects_incomplete_referenced_chain(tmp_path: Path) -> None:
    ledger, refs = _complete_ledger(tmp_path)
    open_query, open_result = _record_result(
        ledger,
        ledger.materializations,
        result_kind="summary",
        source_ids=(SOURCE_A,),
        items=(
            PublicSummaryItem(
                metrics=(PublicMetricValue(name="event_count", value=1, unit="events"),),
                cohort_ref=ledger.materializations.make_ref("cohort", stable_value="open"),
            ),
        ),
        has_more=True,
    )
    report = _valid_report(ledger, refs)
    finding = report.findings[0].model_copy(
        update={
            "query_refs": (*report.findings[0].query_refs, open_query),
            "result_refs": (*report.findings[0].result_refs, open_result),
        }
    )
    report = report.model_copy(update={"findings": (finding,)})

    with pytest.raises(
        ExplorationReportValidationError,
        match=r"findings\[0\].*query chain is incomplete",
    ):
        validate_exploration_report(report, ledger, _scope())


def test_report_rejects_unobserved_metric(tmp_path: Path) -> None:
    ledger, refs = _complete_ledger(tmp_path)
    report = _valid_report(ledger, refs)
    bad_metric = report.findings[0].metrics[0].model_copy(update={"value": 999_999})
    finding = report.findings[0].model_copy(update={"metrics": (bad_metric,)})
    report = report.model_copy(update={"findings": (finding,)})

    with pytest.raises(ExplorationReportValidationError, match="metric value"):
        validate_exploration_report(report, ledger, _scope())


def test_report_requires_structural_causal_separation(tmp_path: Path) -> None:
    ledger, refs = _complete_ledger(tmp_path)
    report = _valid_report(ledger, refs)
    finding = report.findings[0].model_copy(
        update={"hypothesis": report.findings[0].observation}
    )
    report = report.model_copy(
        update={"causal_limitations": (), "findings": (finding,)}
    )

    with pytest.raises(ExplorationReportValidationError, match="causal"):
        validate_exploration_report(report, ledger, _scope())


@pytest.mark.parametrize("missing", ["sources", "fields"])
def test_report_rejects_incomplete_required_catalog(
    tmp_path: Path, missing: str
) -> None:
    store = RunMaterializationStore(tmp_path / missing, run_id="run-1")
    ledger = ExplorationLedger(
        "run-1", store, authorized_source_ids=(SOURCE_A, SOURCE_B)
    )
    _catalogs(
        ledger,
        store,
        include_sources=missing != "sources",
        include_fields=missing != "fields",
    )

    with pytest.raises(ExplorationReportValidationError, match=f"catalog.{missing}"):
        validate_exploration_report(
            ExplorationReport(
                report_version="1",
                executive_summary="근거가 있는 탐색 요약입니다.",
                findings=(
                    Finding(
                        finding_id="finding-1",
                        title="탐색 결과",
                        observation="관찰 결과입니다.",
                        hypothesis="가능한 설명입니다.",
                        confidence="low",
                        source_ids=(SOURCE_A,),
                        query_refs=("unknown-query",),
                        result_refs=("unknown-result",),
                        metrics=(
                            ExplorationMetric(
                                name="event_count",
                                value=1,
                                unit="events",
                                result_ref="unknown-result",
                            ),
                        ),
                        recommendations=(
                            Recommendation(
                                action="검증합니다.",
                                expected_direction="decrease",
                                target_metric="error_rate",
                            ),
                        ),
                    ),
                ),
                coverage=ExplorationCoverage(
                    completed_query_refs=tuple(sorted(ledger.complete_query_refs())),
                    abandoned_branches=(),
                ),
                causal_limitations=("추가 검증이 필요합니다.",),
            ),
            ledger,
            _scope(),
        )


def test_report_rejects_catalog_that_covers_only_scope_subset(tmp_path: Path) -> None:
    ledger, refs = _complete_ledger(tmp_path)
    report = _valid_report(ledger, refs)

    with pytest.raises(ExplorationReportValidationError, match="catalog"):
        validate_exploration_report(
            report,
            ledger,
            _scope((SOURCE_A, SOURCE_B, SOURCE_C)),
        )


def test_report_rejects_ledger_after_materialization_generation_changes(
    tmp_path: Path,
) -> None:
    ledger, refs = _complete_ledger(tmp_path)
    report = _valid_report(ledger, refs)
    ledger.materializations.invalidate_snapshot()

    with pytest.raises(ExplorationReportValidationError, match="stale snapshot"):
        validate_exploration_report(report, ledger, _scope())


def test_report_rejects_scan_incomplete_result(tmp_path: Path) -> None:
    ledger, refs = _complete_ledger(tmp_path)
    partial_query, partial_result = _record_result(
        ledger,
        ledger.materializations,
        result_kind="summary",
        source_ids=(SOURCE_A,),
        items=(),
        scan_complete=False,
    )
    report = _valid_report(ledger, refs)
    finding = report.findings[0].model_copy(
        update={
            "query_refs": (*report.findings[0].query_refs, partial_query),
            "result_refs": (*report.findings[0].result_refs, partial_result),
        }
    )
    report = report.model_copy(update={"findings": (finding,)})

    with pytest.raises(ExplorationReportValidationError, match="scan_complete"):
        validate_exploration_report(report, ledger, _scope())


def test_completed_report_can_abandon_terminal_partial_after_successful_retry(
    tmp_path: Path,
) -> None:
    ledger, refs = _complete_ledger(tmp_path)
    partial_query, _ = _record_result(
        ledger,
        ledger.materializations,
        result_kind="summary",
        source_ids=(SOURCE_A,),
        items=(),
        scan_complete=False,
    )
    _record_result(
        ledger,
        ledger.materializations,
        result_kind="summary",
        source_ids=(SOURCE_A,),
        items=(
            PublicSummaryItem(
                metrics=(PublicMetricValue(name="event_count", value=1, unit="events"),),
                cohort_ref=ledger.materializations.make_ref(
                    "cohort", stable_value="successful-retry"
                ),
            ),
        ),
    )
    report = _valid_report(ledger, refs)
    report = report.model_copy(
        update={
            "coverage": ExplorationCoverage(
                completed_query_refs=tuple(sorted(ledger.complete_query_refs())),
                abandoned_branches=(
                    AbandonedBranch(
                        query_ref=partial_query,
                        last_page_index=0,
                        has_more=False,
                        reason="retry without cursor completed successfully",
                    ),
                ),
            )
        }
    )

    assert validate_exploration_report(report, ledger, _scope()) is report


def test_report_rejects_foreign_source(tmp_path: Path) -> None:
    ledger, refs = _complete_ledger(tmp_path)
    report = _valid_report(ledger, refs)
    finding = report.findings[0].model_copy(
        update={"source_ids": (*report.findings[0].source_ids, "source-foreign")}
    )
    report = report.model_copy(update={"findings": (finding,)})

    with pytest.raises(ExplorationReportValidationError, match="source_ids"):
        validate_exploration_report(report, ledger, _scope())


def test_report_rejects_foreign_evidence(tmp_path: Path) -> None:
    ledger, refs = _complete_ledger(tmp_path)
    report = _valid_report(ledger, refs)
    finding = report.findings[0].model_copy(update={"evidence_ids": ("forged",)})
    report = report.model_copy(update={"findings": (finding,)})

    with pytest.raises(ExplorationReportValidationError, match="evidence_ids"):
        validate_exploration_report(report, ledger, _scope())


def test_report_rejects_unsupported_high_confidence(tmp_path: Path) -> None:
    ledger, refs = _complete_ledger(tmp_path)
    report = _valid_report(ledger, refs)
    finding = report.findings[0].model_copy(
        update={
            "query_refs": (refs["summary_query"],),
            "result_refs": (refs["summary_result"],),
            "evidence_ids": (),
        }
    )
    report = report.model_copy(update={"findings": (finding,)})

    with pytest.raises(ExplorationReportValidationError, match="confidence=high"):
        validate_exploration_report(report, ledger, _scope())


def test_report_requires_every_open_branch_to_be_published(tmp_path: Path) -> None:
    ledger, refs = _complete_ledger(tmp_path)
    _record_result(
        ledger,
        ledger.materializations,
        result_kind="summary",
        source_ids=(SOURCE_A,),
        items=(),
        has_more=True,
    )

    with pytest.raises(ExplorationReportValidationError, match="abandoned_branches"):
        validate_exploration_report(_valid_report(ledger, refs), ledger, _scope())


def test_partial_report_allows_no_findings_only_with_open_branch_and_limitation() -> None:
    partial = ExplorationPartialReport(
        report_version="1",
        executive_summary="예산 종료로 탐색을 부분 완료했습니다.",
        findings=(),
        coverage=ExplorationCoverage(
            completed_query_refs=(),
            abandoned_branches=(
                AbandonedBranch(
                    query_ref="query-open",
                    last_page_index=0,
                    has_more=True,
                    reason="Agent 실행 예산 종료",
                ),
            ),
        ),
        causal_limitations=("미완주 분기는 전체 결과로 해석할 수 없습니다.",),
    )
    assert partial.findings == ()

    with pytest.raises(ValidationError):
        ExplorationPartialReport(
            report_version="1",
            executive_summary="예산 종료로 탐색을 부분 완료했습니다.",
            findings=(),
            coverage=ExplorationCoverage(
                completed_query_refs=(), abandoned_branches=()
            ),
            causal_limitations=("미완주 분기가 없습니다.",),
        )
    with pytest.raises(ValidationError):
        ExplorationReport(
            report_version="1",
            executive_summary="완료 보고서입니다.",
            findings=(),
            coverage=ExplorationCoverage(
                completed_query_refs=(), abandoned_branches=()
            ),
            causal_limitations=("검증 한계가 있습니다.",),
        )


def test_submit_report_returns_terminal_report_and_public_ledger(tmp_path: Path) -> None:
    ledger, refs = _complete_ledger(tmp_path)
    reader = SimpleNamespace(
        materializations=ledger.materializations,
        authorized_scope=_scope(),
        active_source_ids=(SOURCE_A, SOURCE_B),
    )
    tools = ExplorationTools(
        reader=reader,  # type: ignore[arg-type]
        materializations=ledger.materializations,
        ledger=ledger,
    )
    report = _valid_report(ledger, refs)

    response = tools.submit_exploration_report(report.model_dump(mode="json"))

    assert isinstance(response, ExplorationReportSubmission)
    assert response.status == "success"
    assert response.terminal is True
    assert response.report == report
    assert response.ledger_snapshot == ledger.public_snapshot()
    assert response.error is None


def test_submit_report_returns_nonretryable_validation_error(tmp_path: Path) -> None:
    ledger, refs = _complete_ledger(tmp_path)
    reader = SimpleNamespace(
        materializations=ledger.materializations,
        authorized_scope=_scope(),
        active_source_ids=(SOURCE_A, SOURCE_B),
    )
    tools = ExplorationTools(
        reader=reader,  # type: ignore[arg-type]
        materializations=ledger.materializations,
        ledger=ledger,
    )
    report = _valid_report(ledger, refs)
    payload = report.model_dump(mode="json")
    payload["findings"][0]["metrics"][0]["value"] = 999_999

    response = tools.submit_exploration_report(payload)

    assert response.status == "error"
    assert response.terminal is False
    assert response.report is None
    assert response.ledger_snapshot is None
    assert response.error is not None
    assert response.error.category == "validation"
    assert response.error.is_retryable is False
    assert "findings[0].metrics[0].value" in response.error.message
