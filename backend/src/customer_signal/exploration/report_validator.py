"""Fail-closed validation of report claims against the observed Tool ledger."""

from __future__ import annotations

from collections.abc import Iterable
from typing import NoReturn

from customer_signal.exploration.contracts import ExplorationSourceScope
from customer_signal.exploration.ledger import ExplorationLedger, ExplorationQueryRecord
from customer_signal.exploration.materialization import MaterializationError
from customer_signal.exploration.report_contracts import ExplorationMetric, ExplorationReport
from customer_signal.exploration.tool_contracts import (
    PublicExplorationEvidenceEvent,
    PublicSequenceItem,
    PublicSummaryItem,
)


class ExplorationReportValidationError(ValueError):
    """A report field is unsupported by complete, authorized Tool evidence."""


def _fail(path: str, message: str) -> NoReturn:
    raise ExplorationReportValidationError(f"{path}: {message}")


def _normalize_claim(value: str) -> str:
    return " ".join(value.casefold().split())


def _iter_items(record: ExplorationQueryRecord) -> Iterable[object]:
    for page in record.pages:
        yield from page.items


def _require_query(
    ledger: ExplorationLedger, query_ref: str, path: str
) -> ExplorationQueryRecord:
    try:
        return ledger.require_query(query_ref)
    except MaterializationError as error:
        _fail(path, str(error))


def _require_result(
    ledger: ExplorationLedger, result_ref: str, path: str
) -> ExplorationQueryRecord:
    try:
        return ledger.require_result(result_ref)
    except MaterializationError as error:
        _fail(path, str(error))


def _validate_complete_chain(
    record: ExplorationQueryRecord, path: str, ledger: ExplorationLedger
) -> None:
    if any(not page.scan_complete for page in record.pages):
        _fail(path, "cited result requires scan_complete=true")
    if record.pages[-1].has_more or not ledger.is_complete(record.query_ref):
        _fail(path, "query chain is incomplete; read until has_more=false")


def _metric_exists(record: ExplorationQueryRecord, metric: ExplorationMetric) -> bool:
    for item in _iter_items(record):
        if isinstance(item, PublicSummaryItem):
            for observed in item.metrics:
                if (
                    observed.name == metric.name
                    and observed.value == metric.value
                    and observed.unit == metric.unit
                ):
                    return True
        elif isinstance(item, PublicSequenceItem):
            sequence_values: dict[str, tuple[int | float | None, str]] = {
                "occurrence_count": (item.occurrence_count, "occurrences"),
                "completed_step_count": (item.completed_step_count, "steps"),
                "total_step_count": (item.total_step_count, "steps"),
                "span_minutes": (item.span_minutes, "minutes"),
            }
            if sequence_values.get(metric.name) == (metric.value, metric.unit):
                return True
    last = record.pages[-1]
    return (
        metric.name == "matched_count"
        and metric.value == last.matched_count
        and metric.unit in {"rows", "matches", "customers"}
    )


def _validate_metric(
    metric: ExplorationMetric,
    *,
    finding_index: int,
    metric_index: int,
    finding_query_refs: set[str],
    finding_result_refs: set[str],
    ledger: ExplorationLedger,
) -> None:
    path = f"findings[{finding_index}].metrics[{metric_index}]"
    if metric.result_ref not in finding_result_refs:
        _fail(f"{path}.result_ref", "must be cited by the containing finding")
    record = _require_result(ledger, metric.result_ref, f"{path}.result_ref")
    if record.query_ref not in finding_query_refs:
        _fail(f"{path}.result_ref", "parent query_ref must be cited by the finding")
    _validate_complete_chain(record, f"{path}.result_ref", ledger)
    if not _metric_exists(record, metric):
        _fail(
            f"{path}.value",
            "metric value, name, and unit were not observed in the cited Tool result",
        )


def _validate_finding(
    report: ExplorationReport,
    finding_index: int,
    ledger: ExplorationLedger,
    scope: ExplorationSourceScope,
) -> None:
    finding = report.findings[finding_index]
    path = f"findings[{finding_index}]"
    if not set(finding.source_ids) <= set(scope.source_ids):
        _fail(f"{path}.source_ids", "contains a Source outside the authorized run scope")
    if _normalize_claim(finding.observation) == _normalize_claim(finding.hypothesis):
        _fail(
            f"{path}.hypothesis",
            "causal hypothesis must be structurally separate from the observation",
        )

    query_refs = set(finding.query_refs)
    result_refs = set(finding.result_refs)
    query_records: dict[str, ExplorationQueryRecord] = {}
    for query_index, query_ref in enumerate(finding.query_refs):
        record = _require_query(ledger, query_ref, f"{path}.query_refs[{query_index}]")
        _validate_complete_chain(record, f"{path}.query_refs[{query_index}]", ledger)
        query_records[query_ref] = record

    result_records: dict[str, ExplorationQueryRecord] = {}
    for result_index, result_ref in enumerate(finding.result_refs):
        record = _require_result(ledger, result_ref, f"{path}.result_refs[{result_index}]")
        _validate_complete_chain(record, f"{path}.result_refs[{result_index}]", ledger)
        if record.query_ref not in query_refs:
            _fail(
                f"{path}.result_refs[{result_index}]",
                "its parent query_ref is not cited by the finding",
            )
        result_records[result_ref] = record

    cited_result_sources = {
        source_id
        for record in result_records.values()
        for source_id in record.source_ids
    }
    if not cited_result_sources <= set(finding.source_ids):
        _fail(
            f"{path}.source_ids",
            "must include every Source used by cited Tool results",
        )

    for metric_index, metric in enumerate(finding.metrics):
        _validate_metric(
            metric,
            finding_index=finding_index,
            metric_index=metric_index,
            finding_query_refs=query_refs,
            finding_result_refs=result_refs,
            ledger=ledger,
        )

    evidence: dict[str, tuple[ExplorationQueryRecord, PublicExplorationEvidenceEvent]] = {}
    for record in result_records.values():
        if record.result_kind != "evidence":
            continue
        for item in _iter_items(record):
            if isinstance(item, PublicExplorationEvidenceEvent):
                evidence[item.evidence_id] = (record, item)
    for evidence_index, evidence_id in enumerate(finding.evidence_ids):
        observed = evidence.get(evidence_id)
        if observed is None:
            _fail(
                f"{path}.evidence_ids[{evidence_index}]",
                "Evidence was not issued by a cited bounded Evidence result",
            )
        record, event = observed
        if event.source_id not in finding.source_ids:
            _fail(
                f"{path}.evidence_ids[{evidence_index}]",
                "Evidence belongs to a Source not declared by the finding",
            )
        parent_refs = {
            page.parent_result_ref
            for page in record.pages
            if page.parent_result_ref is not None
        }
        if len(parent_refs) != 1 or not parent_refs <= result_refs:
            _fail(
                f"{path}.evidence_ids[{evidence_index}]",
                "Evidence parent_result_ref is not authorized by this finding",
            )

    if finding.confidence == "high":
        has_quantitative = any(
            record.result_kind == "summary" for record in result_records.values()
        ) and bool(finding.metrics)
        has_sequence = any(
            record.result_kind in {"sequence_sequence", "sequence_funnel"}
            for record in result_records.values()
        )
        if not has_quantitative or not has_sequence or not finding.evidence_ids:
            _fail(
                f"{path}.confidence",
                "confidence=high requires complete quantitative, sequence/funnel, "
                "and authorized Evidence results",
            )


def _validate_coverage(report: ExplorationReport, ledger: ExplorationLedger) -> None:
    actual_completed = set(ledger.complete_query_refs())
    declared_completed = set(report.coverage.completed_query_refs)
    if declared_completed != actual_completed:
        _fail(
            "coverage.completed_query_refs",
            "must publish every and only completed ledger query",
        )
    cited = {
        query_ref for finding in report.findings for query_ref in finding.query_refs
    }
    if not cited <= declared_completed:
        _fail(
            "coverage.completed_query_refs",
            "must include every query cited by findings",
        )

    open_refs = set(ledger.open_query_refs)
    branches = {
        branch.query_ref: branch for branch in report.coverage.abandoned_branches
    }
    if set(branches) != open_refs:
        _fail(
            "coverage.abandoned_branches",
            "must publish every and only open ledger query",
        )
    for query_ref, branch in branches.items():
        record = ledger.require_query(query_ref)
        last = record.pages[-1]
        if branch.last_page_index != last.page_index or branch.has_more != last.has_more:
            _fail(
                "coverage.abandoned_branches",
                "last_page_index and has_more must match the observed open branch",
            )


def validate_exploration_report(
    report: ExplorationReport,
    ledger: ExplorationLedger,
    scope: ExplorationSourceScope,
) -> ExplorationReport:
    """Return the original report only when every cited claim is ledger-backed."""

    if not isinstance(report, ExplorationReport):
        _fail("report", "completed submission requires ExplorationReport")
    if not isinstance(scope, ExplorationSourceScope):
        _fail("scope", "must use ExplorationSourceScope")
    try:
        ledger.assert_current_generation()
    except MaterializationError as error:
        _fail("ledger.generation", str(error))
    if not ledger.catalog_sources_cover(scope.source_ids):
        _fail("catalog.sources", "sources catalog chain is incomplete")
    if not ledger.catalog_fields_cover(scope.source_ids):
        _fail("catalog.fields", "fields catalog chain is incomplete")
    if not report.causal_limitations:
        _fail("causal_limitations", "at least one causal limitation is required")
    for finding_index in range(len(report.findings)):
        _validate_finding(report, finding_index, ledger, scope)
    _validate_coverage(report, ledger)
    return report


__all__ = [
    "ExplorationReportValidationError",
    "validate_exploration_report",
]
