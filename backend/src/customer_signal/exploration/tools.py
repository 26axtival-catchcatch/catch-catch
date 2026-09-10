"""Four stable read-only Tools for autonomous normalized-data exploration."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import groupby
from typing import Any, cast

from pydantic import BaseModel, TypeAdapter

from customer_signal.domain.models import CustomerEvent
from customer_signal.exploration.contracts import ExplorationSourceScope, ToolError
from customer_signal.exploration.cursor import (
    CursorPayload,
    CursorValidationError,
    canonical_json,
    query_fingerprint,
)
from customer_signal.exploration.fields import (
    ExplorationFieldCompiler,
    FieldValidationError,
)
from customer_signal.exploration.ledger import (
    ExplorationLedger,
    ExplorationLedgerError,
    ToolPageObservation,
)
from customer_signal.exploration.materialization import (
    CustomerAnchor,
    DerivedResultEntry,
    ForeignRunReferenceError,
    MaterializationError,
    MaterializedResult,
    PreparedCohort,
    RunMaterializationStore,
    StaleSnapshotReferenceError,
    UnknownMaterializationReferenceError,
    WorkEvent,
)
from customer_signal.exploration.report_contracts import (
    ExplorationReport,
    ExplorationReportSubmission,
)
from customer_signal.exploration.report_validator import (
    ExplorationReportValidationError,
    validate_exploration_report,
)
from customer_signal.exploration.reader import (
    DataSpacePermissionError,
    DataSpaceReader,
    ScanInterruptedError,
    SnapshotBarrierUnavailableError,
    SnapshotChangedDuringScanError,
)
from customer_signal.exploration.tool_contracts import (
    AnalyzeEventSequencesInput,
    CountMetric,
    ExplorationCoverage,
    ExplorationFieldRef,
    ExplorationPage,
    ExplorationPartialState,
    ExplorationResult,
    ExplorationToolEnvelope,
    FunnelInput,
    InspectDataSpaceInput,
    InspectFieldsInput,
    InspectSourcesInput,
    InspectValuesInput,
    MetricSpec,
    NumericMetric,
    PublicExplorationEvidenceEvent,
    PublicExplorationItem,
    PublicFieldCatalogItem,
    PublicMetricValue,
    PublicSemanticValue,
    PublicSequenceItem,
    PublicSourceCatalogItem,
    PublicSummaryItem,
    PublicValueCatalogItem,
    RatioMetric,
    ReadEventEvidenceInput,
    RepetitionInput,
    SequenceInput,
    SequenceStep,
    SummarizeEventsInput,
)


_ITEM_ADAPTER = TypeAdapter(PublicExplorationItem)
_INSPECT_ADAPTER = TypeAdapter(InspectDataSpaceInput)
_SUMMARY_ADAPTER = TypeAdapter(SummarizeEventsInput)
_SEQUENCE_ADAPTER = TypeAdapter(AnalyzeEventSequencesInput)
_EVIDENCE_ADAPTER = TypeAdapter(ReadEventEvidenceInput)
_REPORT_ADAPTER = TypeAdapter(ExplorationReport)


TOOL_DESCRIPTIONS: dict[str, str] = {
    "inspect_data_space": (
        "활성 Source와 공개 의미 필드 또는 값 카탈로그를 cursor로 탐색한다. "
        "분석 시작 시 sources와 fields를 각각 끝까지 읽을 때 선택한다. "
        "Source item의 canonical 값 목록은 결정론적 상한까지만 제공하므로 "
        "truncated_fields가 있으면 fields 이후 해당 values view를 cursor 끝까지 읽는다. "
        "분포·시간 순서·가설 계산에는 사용하지 말고 내부 컬럼이나 필드명을 추측하지 않는다."
    ),
    "summarize_events": (
        "허용된 이벤트 공간을 모두 scan한 뒤 분포, 비율, 수치와 시간 추세를 집계한다. "
        "규모·비율·코호트 비교에 선택하고 행동 순서나 인과 관계 검증에는 사용하지 않는다. "
        "보고서에 쓸 결과는 has_more=false까지 읽는다."
    ),
    "analyze_event_sequences": (
        "고객별 반복, 순차 행동 또는 funnel 이탈을 전체 scan으로 계산한다. "
        "시간 순서가 있는 가설을 검증할 때 선택하고 단순 분포 조회에는 사용하지 않는다. "
        "반환된 고객 수를 먼저 자른 뒤 전체 수처럼 해석하지 않는다."
    ),
    "read_event_evidence": (
        "앞선 result_ref가 허용한 최대 3명의 match 주변 Journey를 마스킹된 공개 Event로 읽는다. "
        "집계·sequence의 대표 근거 확인에만 선택하며 임의 고객, 원시 PII, 전체 export를 요청하지 않는다. "
        "bounded 결과도 has_more=false까지 읽는다."
    ),
}

_SOURCE_VOCABULARY_LIMIT = 64


def exploration_tool_json_schema() -> dict[str, dict[str, object]]:
    """Return the stable model-facing Tool descriptions and strict input schemas."""

    schemas = {
        "inspect_data_space": _INSPECT_ADAPTER.json_schema(),
        "summarize_events": SummarizeEventsInput.model_json_schema(),
        "analyze_event_sequences": _SEQUENCE_ADAPTER.json_schema(),
        "read_event_evidence": ReadEventEvidenceInput.model_json_schema(),
    }
    return {
        name: {"description": TOOL_DESCRIPTIONS[name], "input_schema": schemas[name]}
        for name in TOOL_DESCRIPTIONS
    }


def _validate_tool_input(adapter: TypeAdapter[Any], value: object) -> Any:
    """Validate live JSON-decoded args in JSON mode without loosening strict fields."""

    if isinstance(value, BaseModel):
        return adapter.validate_python(value)
    if isinstance(value, Mapping):
        try:
            payload = json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as error:
            raise ValueError("Tool arguments must be canonical JSON-compatible values") from error
        return adapter.validate_json(payload)
    return adapter.validate_python(value)


@dataclass(slots=True)
class _BoundedVocabulary:
    values: set[str] = field(default_factory=set)
    truncated: bool = False

    def add(self, value: str) -> None:
        if value in self.values:
            return
        if len(self.values) < _SOURCE_VOCABULARY_LIMIT:
            self.values.add(value)
            return
        self.truncated = True
        largest = max(self.values)
        if value < largest:
            self.values.remove(largest)
            self.values.add(value)

    def sorted_values(self) -> tuple[str, ...]:
        return tuple(sorted(self.values))


@dataclass(slots=True)
class _SourceStats:
    row_count: int = 0
    start_at: datetime | None = None
    end_at: datetime | None = None
    event_types: _BoundedVocabulary = field(default_factory=_BoundedVocabulary)
    actions: _BoundedVocabulary = field(default_factory=_BoundedVocabulary)
    topics: _BoundedVocabulary = field(default_factory=_BoundedVocabulary)
    outcomes: _BoundedVocabulary = field(default_factory=_BoundedVocabulary)


@dataclass(slots=True)
class _NumericStats:
    count: int = 0
    total: float = 0
    minimum: float | None = None
    maximum: float | None = None

    def add(self, value: int | float) -> None:
        numeric = float(value)
        self.count += 1
        self.total += numeric
        self.minimum = numeric if self.minimum is None else min(self.minimum, numeric)
        self.maximum = numeric if self.maximum is None else max(self.maximum, numeric)


@dataclass(slots=True)
class _RatioStats:
    denominator_events: int = 0
    numerator_events: int = 0
    denominator_customers: set[str] = field(default_factory=set)
    numerator_customers: set[str] = field(default_factory=set)


@dataclass(slots=True)
class _SummaryStats:
    event_count: int = 0
    customers: set[str] = field(default_factory=set)
    anchors: dict[str, CustomerAnchor] = field(default_factory=dict)
    numeric: dict[int, _NumericStats] = field(default_factory=dict)
    ratios: dict[int, _RatioStats] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _SequenceMatch:
    item: PublicSequenceItem
    sort_key: tuple[object, ...]
    anchor: CustomerAnchor
    cohort: PreparedCohort


@dataclass(frozen=True, slots=True)
class _EvidenceResponseMeta:
    candidate_customer_count: int
    selected_customer_count: int
    selection_strategy: str
    events_before_match: int
    events_after_match: int
    selection_rationale: str


class ExplorationTools:
    """Production Tool implementation over one prepared run data space."""

    def __init__(
        self,
        *,
        reader: DataSpaceReader,
        materializations: RunMaterializationStore,
        ledger: ExplorationLedger | None = None,
    ) -> None:
        if reader.materializations is not materializations:
            raise ValueError("reader and Tools must share exactly one materialization store")
        self.reader = reader
        self.materializations = materializations
        self.ledger = ledger or ExplorationLedger(
            run_id=materializations.run_id,
            materializations=materializations,
        )
        if self.ledger.materializations is not materializations:
            raise ValueError("Tools and ledger must share exactly one materialization store")
        self.ledger.bind_active_source_ids(reader.active_source_ids)
        self.fields = ExplorationFieldCompiler(reader)

    def inspect_data_space(
        self, request: InspectSourcesInput | InspectFieldsInput | InspectValuesInput
    ) -> ExplorationToolEnvelope:
        try:
            request = _validate_tool_input(_INSPECT_ADAPTER, request)
            if isinstance(request, InspectSourcesInput):
                response = self._inspect_sources(request)
            elif isinstance(request, InspectFieldsInput):
                response = self._inspect_fields(request)
            else:
                response = self._inspect_values(request)
            return self._record_tool_page("inspect_data_space", request, response)
        except Exception as error:
            return self._known_error(request, error)

    def summarize_events(self, request: SummarizeEventsInput) -> ExplorationToolEnvelope:
        try:
            request = _validate_tool_input(_SUMMARY_ADAPTER, request)
            source_ids = self.reader.validate_source_ids(request.source_ids)
            self._validate_summary_request(request, source_ids)
            fingerprint = query_fingerprint(request)
            if request.cursor is not None:
                response = self._read_page(
                    request=request,
                    source_ids=source_ids,
                    fingerprint=fingerprint,
                    result_kind="summary",
                )
            else:
                response = self._compute_summary(request, source_ids, fingerprint)
            return self._record_tool_page("summarize_events", request, response)
        except Exception as error:
            return self._known_error(request, error)

    def analyze_event_sequences(
        self, request: RepetitionInput | SequenceInput | FunnelInput
    ) -> ExplorationToolEnvelope:
        try:
            request = _validate_tool_input(_SEQUENCE_ADAPTER, request)
            source_ids = self.reader.validate_source_ids(request.source_ids)
            self._validate_sequence_request(request, source_ids)
            fingerprint = query_fingerprint(request)
            result_kind = f"sequence_{request.mode}"
            if request.cursor is not None:
                response = self._read_page(
                    request=request,
                    source_ids=source_ids,
                    fingerprint=fingerprint,
                    result_kind=result_kind,
                )
            else:
                response = self._compute_sequence(
                    request, source_ids, fingerprint, result_kind
                )
            return self._record_tool_page("analyze_event_sequences", request, response)
        except Exception as error:
            return self._known_error(request, error)

    def read_event_evidence(
        self, request: ReadEventEvidenceInput
    ) -> ExplorationToolEnvelope:
        try:
            request = _validate_tool_input(_EVIDENCE_ADAPTER, request)
            fingerprint = query_fingerprint(request)
            if request.cursor is not None:
                self.materializations.read_result(request.parent_result_ref)
                # The evidence result has its own ref in the cursor; parent lookup only
                # verifies the authorization context is still live.
                response = self._read_page(
                    request=request,
                    source_ids=self.reader.active_source_ids,
                    fingerprint=fingerprint,
                    result_kind="evidence",
                    evidence_parent_ref=request.parent_result_ref,
                )
            else:
                response = self._compute_evidence(request, fingerprint)
            return self._record_tool_page("read_event_evidence", request, response)
        except Exception as error:
            return self._known_error(request, error)

    def submit_exploration_report(
        self, request: ExplorationReport | Mapping[str, object]
    ) -> ExplorationReportSubmission:
        """Parse and validate the terminal report without ending on validation failure."""

        try:
            report = _validate_tool_input(_REPORT_ADAPTER, request)
            report = validate_exploration_report(
                report,
                self.ledger,
                self.reader.authorized_scope,
            )
        except (ExplorationReportValidationError, ValueError) as error:
            return ExplorationReportSubmission(
                status="error",
                terminal=False,
                error=ToolError(
                    category="validation",
                    is_retryable=False,
                    message=str(error)[:1_000] or type(error).__name__,
                ),
            )
        return ExplorationReportSubmission(
            status="success",
            terminal=True,
            report=report,
            ledger_snapshot=self.ledger.public_snapshot(),
            error=None,
        )

    def _record_tool_page(
        self,
        tool_name: str,
        request: BaseModel,
        response: ExplorationToolEnvelope,
    ) -> ExplorationToolEnvelope:
        if response.status == "error":
            return response
        assert response.result.query_ref is not None
        assert response.result.result_ref is not None
        assert response.result.page_ref is not None
        meta = self.materializations.read_result(response.result.result_ref)
        request_cursor = getattr(request, "cursor", None)
        request_cursor_fingerprint = (
            hashlib.sha256(request_cursor.encode("utf-8")).hexdigest()
            if request_cursor is not None
            else None
        )
        next_cursor = response.page.next_cursor
        next_cursor_fingerprint = (
            hashlib.sha256(next_cursor.encode("utf-8")).hexdigest()
            if next_cursor is not None
            else None
        )
        parent_page_ref = None
        if response.page.page_index > 0:
            record = self.ledger.require_query(response.result.query_ref)
            if len(record.pages) > response.page.page_index:
                parent_page_ref = record.pages[response.page.page_index].parent_page_ref
            else:
                parent_page_ref = record.pages[-1].page_ref
        request_payload = request.model_dump(
            mode="json", exclude={"cursor"}, exclude_none=False
        )
        self.ledger.record_page(
            ToolPageObservation(
                tool_name=cast(Any, tool_name),
                result_kind=meta.result_kind,
                request_json=canonical_json(request_payload),
                source_ids=meta.source_ids,
                query_ref=response.result.query_ref,
                result_ref=response.result.result_ref,
                page_ref=response.result.page_ref,
                parent_page_ref=parent_page_ref,
                request_cursor_fingerprint=request_cursor_fingerprint,
                next_cursor_fingerprint=next_cursor_fingerprint,
                page_index=response.page.page_index,
                page_size=response.page.page_size,
                returned_count=response.page.returned_count,
                matched_count=response.page.matched_count,
                has_more=response.page.has_more,
                scan_complete=response.page.scan_complete,
                snapshot_id=response.coverage.snapshot_id,
                query_fingerprint=response.coverage.query_fingerprint,
                parent_result_ref=(
                    meta.parent_result_ref
                    if isinstance(request, ReadEventEvidenceInput)
                    else None
                ),
                items=response.result.items,
            )
        )
        return response

    def _inspect_sources(self, request: InspectSourcesInput) -> ExplorationToolEnvelope:
        source_ids = self.reader.validate_source_ids(
            request.source_ids, allow_empty_as_all=True
        )
        fingerprint = query_fingerprint(request)
        if request.cursor is not None:
            return self._read_page(
                request=request,
                source_ids=source_ids,
                fingerprint=fingerprint,
                result_kind="catalog_sources",
            )
        stats = {source_id: _SourceStats() for source_id in source_ids}

        def consume(event: CustomerEvent) -> None:
            current = stats[event.source_id]
            current.row_count += 1
            current.start_at = (
                event.occurred_at
                if current.start_at is None
                else min(current.start_at, event.occurred_at)
            )
            current.end_at = (
                event.occurred_at
                if current.end_at is None
                else max(current.end_at, event.occurred_at)
            )
            current.event_types.add(event.event_type)
            current.actions.add(event.action)
            current.topics.add(event.topic)
            current.outcomes.add(event.outcome)

        interruption = self._scan_prefix(self._scope(source_ids), consume)
        rows = []
        for source_id in source_ids:
            manifest = self.reader.manifest(source_id)
            current = stats[source_id]
            item = PublicSourceCatalogItem(
                source_id=source_id,
                label=_neutral_label(manifest.label, source_id),
                observed_start_at=current.start_at,
                observed_end_at=current.end_at,
                row_count=current.row_count,
                event_types=current.event_types.sorted_values(),
                actions=current.actions.sorted_values(),
                topics=current.topics.sorted_values(),
                outcomes=current.outcomes.sorted_values(),
                truncated_fields=tuple(
                    field_name
                    for field_name, vocabulary in (
                        ("event_type", current.event_types),
                        ("action", current.actions),
                        ("topic", current.topics),
                        ("outcome", current.outcomes),
                    )
                    if vocabulary.truncated
                ),
            )
            rows.append(((source_id,), item))
        return self._store_and_first_page(
            request=request,
            source_ids=source_ids,
            fingerprint=fingerprint,
            result_kind="catalog_sources",
            rows=rows,
            matched_count=len(rows) if interruption is None else None,
            interruption=interruption,
        )

    def _inspect_fields(self, request: InspectFieldsInput) -> ExplorationToolEnvelope:
        source_ids = self.reader.validate_source_ids(request.source_ids)
        fingerprint = query_fingerprint(request)
        if request.cursor is not None:
            return self._read_page(
                request=request,
                source_ids=source_ids,
                fingerprint=fingerprint,
                result_kind="catalog_fields",
            )
        definitions = self.fields.public_fields(source_ids)
        totals = {source_id: 0 for source_id in source_ids}
        missing = {(item.source_id, item.scope, item.name): 0 for item in definitions}

        def consume(event: CustomerEvent) -> None:
            totals[event.source_id] += 1
            for definition in definitions:
                if definition.source_id != event.source_id:
                    continue
                if definition.scope == "canonical":
                    continue
                values = (
                    event.dimensions
                    if definition.scope == "dimension"
                    else event.measures
                )
                if values.get(definition.name) is None:
                    missing[(definition.source_id, definition.scope, definition.name)] += 1

        interruption = self._scan_prefix(self._scope(source_ids), consume)
        rows = []
        for definition in definitions:
            total = totals[definition.source_id]
            absent = missing[(definition.source_id, definition.scope, definition.name)]
            item = PublicFieldCatalogItem(
                source_id=definition.source_id,
                scope=cast(Any, definition.scope),
                name=definition.name,
                data_type=cast(Any, definition.data_type),
                nullable=definition.nullable,
                value_access=cast(Any, definition.value_access),
                missing_rate=(
                    absent / total
                    if interruption is None and total
                    else None
                ),
            )
            rows.append(((definition.source_id, definition.scope, definition.name), item))
        return self._store_and_first_page(
            request=request,
            source_ids=source_ids,
            fingerprint=fingerprint,
            result_kind="catalog_fields",
            rows=rows,
            matched_count=len(rows) if interruption is None else None,
            interruption=interruption,
        )

    def _inspect_values(self, request: InspectValuesInput) -> ExplorationToolEnvelope:
        source_ids = self.reader.validate_source_ids(request.source_ids)
        self.fields.validate_field(
            request.field, source_ids, value_access_required=True
        )
        for predicate in request.predicates:
            self.fields.validate_predicate(predicate, source_ids)
        fingerprint = query_fingerprint(request)
        if request.cursor is not None:
            return self._read_page(
                request=request,
                source_ids=source_ids,
                fingerprint=fingerprint,
                result_kind="catalog_values",
            )
        counts: dict[str, tuple[object, int]] = {}
        total = 0
        missing = 0
        anchors: dict[str, CustomerAnchor] = {}

        def consume(event: CustomerEvent) -> None:
            nonlocal total, missing
            if not self.fields.matches(event, request.predicates):
                return
            lookup = self.fields.lookup(event, request.field)
            if not lookup.applicable:
                return
            total += 1
            if lookup.value is None:
                missing += 1
            key = canonical_json(lookup.value)
            previous = counts.get(key)
            counts[key] = (lookup.value, 1 if previous is None else previous[1] + 1)
            _remember_anchor(anchors, event)

        interruption = self._scan_prefix(self._scope(source_ids), consume)
        missing_rate = missing / total if total else 0.0
        ordered = sorted(counts.values(), key=lambda pair: (-pair[1], canonical_json(pair[0])))
        rows = [
            (
                (-count, canonical_json(value)),
                PublicValueCatalogItem(
                    field=request.field,
                    value=cast(Any, value),
                    count=count,
                    missing_rate=missing_rate,
                ),
            )
            for value, count in ordered
        ]
        return self._store_and_first_page(
            request=request,
            source_ids=source_ids,
            fingerprint=fingerprint,
            result_kind="catalog_values",
            rows=rows,
            matched_count=len(rows) if interruption is None else None,
            customer_anchors=tuple(anchors.values()),
            interruption=interruption,
        )

    def _compute_summary(
        self,
        request: SummarizeEventsInput,
        source_ids: tuple[str, ...],
        fingerprint: str,
    ) -> ExplorationToolEnvelope:
        allowed_customers = (
            self.materializations.resolve_cohort(request.cohort_ref)
            if request.cohort_ref is not None
            else None
        )
        grouped: dict[tuple[object, ...], _SummaryStats] = {}

        def consume(event: CustomerEvent) -> None:
            customer_key = self.materializations.customer_key(
                event.canonical_customer_id
            )
            if allowed_customers is not None and customer_key not in allowed_customers:
                return
            if not self.fields.matches(event, request.predicates):
                return
            lookups = [self.fields.lookup(event, item) for item in request.group_by]
            if any(not lookup.applicable for lookup in lookups):
                return
            bucket = _time_bucket(event.occurred_at, request.time_bucket)
            group_values = tuple(lookup.value for lookup in lookups)
            key = (bucket, *group_values)
            current = grouped.setdefault(key, _SummaryStats())
            current.event_count += 1
            current.customers.add(customer_key)
            _remember_anchor(current.anchors, event)
            for index, metric in enumerate(request.metrics):
                if isinstance(metric, NumericMetric):
                    lookup = self.fields.lookup(event, metric.field)
                    if lookup.applicable and type(lookup.value) in (int, float):
                        current.numeric.setdefault(index, _NumericStats()).add(lookup.value)
                elif isinstance(metric, RatioMetric):
                    ratio = current.ratios.setdefault(index, _RatioStats())
                    # Numerator is evaluated only inside the denominator population,
                    # making numerator <= denominator true by construction.
                    if self.fields.matches(event, metric.denominator_predicates):
                        ratio.denominator_events += 1
                        ratio.denominator_customers.add(customer_key)
                        if self.fields.matches(event, metric.numerator_predicates):
                            ratio.numerator_events += 1
                            ratio.numerator_customers.add(customer_key)

        interruption = self._scan_prefix(
            self._scope(source_ids, request.time_range), consume
        )
        query_ref = self.materializations.make_ref("query")
        rows: list[tuple[tuple[object, ...], BaseModel]] = []
        anchors: dict[str, CustomerAnchor] = {}
        cohorts: list[PreparedCohort] = []
        for key, current in grouped.items():
            bucket = cast(datetime | None, key[0])
            raw_groups = key[1:]
            group_values = tuple(
                PublicSemanticValue(field=field_ref, value=cast(Any, value))
                for field_ref, value in zip(request.group_by, raw_groups, strict=True)
            )
            stable_label = canonical_json(
                [bucket.isoformat() if bucket else None, list(raw_groups)]
            )
            cohort_ref = self.materializations.make_ref(
                "cohort", stable_value=f"{query_ref}\0{stable_label}"
            )
            cohorts.append(
                PreparedCohort(
                    cohort_ref=cohort_ref,
                    canonical_customer_ids=tuple(sorted(current.customers)),
                )
            )
            anchors.update(current.anchors)
            item = PublicSummaryItem(
                bucket_start=bucket,
                group_values=group_values,
                metrics=tuple(
                    self._metric_value(
                        metric,
                        index,
                        current,
                        partial=interruption is not None,
                    )
                    for index, metric in enumerate(request.metrics)
                ),
                cohort_ref=cohort_ref,
            )
            rows.append(
                (
                    (
                        bucket.isoformat() if bucket else "",
                        canonical_json([value.value for value in group_values]),
                    ),
                    item,
                )
            )
        rows.sort(key=lambda row: row[0])
        return self._store_and_first_page(
            request=request,
            source_ids=source_ids,
            fingerprint=fingerprint,
            result_kind="summary",
            rows=rows,
            matched_count=len(rows) if interruption is None else None,
            customer_anchors=tuple(anchors.values()),
            cohorts=cohorts,
            query_ref=query_ref,
            interruption=interruption,
        )

    def _compute_sequence(
        self,
        request: RepetitionInput | SequenceInput | FunnelInput,
        source_ids: tuple[str, ...],
        fingerprint: str,
        result_kind: str,
    ) -> ExplorationToolEnvelope:
        allowed_customers = (
            self.materializations.resolve_cohort(request.cohort_ref)
            if request.cohort_ref is not None
            else None
        )
        work_ref = self.materializations.begin_work()
        query_ref = self.materializations.make_ref("query")
        projection_fields = _sequence_projection_fields(request)
        try:
            def consume(event: CustomerEvent) -> None:
                customer_key = self.materializations.customer_key(
                    event.canonical_customer_id
                )
                if (
                    allowed_customers is not None
                    and customer_key not in allowed_customers
                ):
                    return
                if self._event_is_sequence_candidate(event, request):
                    dimensions, measures = _project_source_fields(
                        self.fields, event, projection_fields
                    )
                    self.materializations.append_work_event(
                        work_ref,
                        event,
                        dimensions=dimensions,
                        measures=measures,
                    )

            interruption = self._scan_prefix(
                self._scope(source_ids, request.time_range), consume
            )
            def entries() -> Iterable[DerivedResultEntry]:
                if interruption is not None and isinstance(
                    request, (FunnelInput, RepetitionInput)
                ):
                    # A prefix cannot prove funnel dropoff or a repetition
                    # cluster's final occurrence count.  Neither public row has a
                    # limitation field, so publish no misleading derived rows.
                    return
                stream = self.materializations.iter_work_events(work_ref)
                for customer_id, events_iter in groupby(
                    stream, key=lambda event: event.canonical_customer_id
                ):
                    # Only one customer's query projection is resident at a time.
                    customer_events = list(events_iter)
                    if isinstance(request, RepetitionInput):
                        matches = self._repetition_matches(
                            query_ref, customer_id, customer_events, request
                        )
                    else:
                        match = self._ordered_sequence_match(
                            query_ref, customer_id, customer_events, request
                        )
                        matches = [] if match is None else [match]
                    for match in matches:
                        yield DerivedResultEntry(
                            sort_key=match.sort_key,
                            item=match.item,
                            customer_anchors=(match.anchor,),
                            cohorts=(match.cohort,),
                        )

            return self._store_and_first_page(
                request=request,
                source_ids=source_ids,
                fingerprint=fingerprint,
                result_kind=result_kind,
                rows=(),
                entries=entries(),
                matched_count=None,
                matched_count_from_rows=interruption is None,
                query_ref=query_ref,
                interruption=interruption,
            )
        finally:
            self.materializations.clear_work(work_ref)

    def _compute_evidence(
        self, request: ReadEventEvidenceInput, fingerprint: str
    ) -> ExplorationToolEnvelope:
        self.materializations.read_result(request.parent_result_ref)
        source_ids = self.reader.active_source_ids
        for field_ref in request.include_fields:
            self.fields.validate_field(
                field_ref, source_ids, value_access_required=True
            )
        candidate_count = self.materializations.authorized_customer_count(
            request.parent_result_ref
        )
        selection = self.materializations.select_authorized_customers(
            request.parent_result_ref,
            customer_refs=request.selection.customer_refs,
            limit=request.selection.max_customers,
        )
        selected = selection.customers
        evidence_meta = _EvidenceResponseMeta(
            candidate_customer_count=candidate_count,
            selected_customer_count=len(selected),
            selection_strategy=selection.strategy,
            events_before_match=request.selection.events_before_match,
            events_after_match=request.selection.events_after_match,
            selection_rationale=selection.rationale,
        )
        selected_by_customer = {item.canonical_customer_id: item for item in selected}
        before = {
            customer_id: deque(maxlen=request.selection.events_before_match)
            for customer_id in selected_by_customer
        }
        captured: dict[str, list[CustomerEvent]] = {
            customer_id: [] for customer_id in selected_by_customer
        }
        found_anchor = {customer_id: False for customer_id in selected_by_customer}
        remaining_after = {
            customer_id: request.selection.events_after_match
            for customer_id in selected_by_customer
        }

        def consume(event: CustomerEvent) -> None:
            customer_key = self.materializations.customer_key(
                event.canonical_customer_id
            )
            authorization = selected_by_customer.get(customer_key)
            if authorization is None:
                return
            customer_id = customer_key
            event_key = (event.occurred_at, event.source_id, event.event_id)
            anchor_key = (
                authorization.anchor_at,
                authorization.anchor_source_id,
                authorization.anchor_event_id,
            )
            if event_key < anchor_key:
                before[customer_id].append(event)
                return
            if event_key == anchor_key:
                captured[customer_id].extend(before[customer_id])
                captured[customer_id].append(event)
                found_anchor[customer_id] = True
                return
            if found_anchor[customer_id] and remaining_after[customer_id] > 0:
                captured[customer_id].append(event)
                remaining_after[customer_id] -= 1

        interruption = self._scan_prefix(self._scope(source_ids), consume)
        if interruption is None and any(not found for found in found_anchor.values()):
            raise MaterializationError(
                "authorized match anchor is not present in the current source snapshot"
            )
        events = [event for values in captured.values() for event in values]
        events.sort(key=_event_key)
        public_rows = []
        anchors = []
        for event in events:
            authorization = selected_by_customer[
                self.materializations.customer_key(event.canonical_customer_id)
            ]
            semantics = []
            for field_ref in request.include_fields:
                lookup = self.fields.lookup(event, field_ref)
                if not lookup.applicable:
                    continue
                value = (
                    lookup.value.isoformat()
                    if isinstance(lookup.value, datetime)
                    else lookup.value
                )
                semantics.append(
                    PublicSemanticValue(field=field_ref, value=cast(Any, value))
                )
            item = PublicExplorationEvidenceEvent(
                evidence_id=event.evidence_id,
                source_id=event.source_id,
                occurred_at=event.occurred_at,
                event_type=event.event_type,
                action=event.action,
                topic=event.topic,
                outcome=event.outcome,
                customer_ref=authorization.customer_ref,
                semantic_fields=tuple(semantics),
            )
            public_rows.append((_event_key(event), item))
        for authorization in selected:
            if interruption is not None and not found_anchor[authorization.canonical_customer_id]:
                continue
            anchors.append(
                CustomerAnchor(
                    canonical_customer_id=authorization.canonical_customer_id,
                    anchor_at=authorization.anchor_at,
                    anchor_source_id=authorization.anchor_source_id,
                    anchor_event_id=authorization.anchor_event_id,
                )
            )
        return self._store_and_first_page(
            request=request,
            source_ids=source_ids,
            fingerprint=fingerprint,
            result_kind="evidence",
            rows=public_rows,
            matched_count=len(public_rows) if interruption is None else None,
            customer_anchors=anchors,
            evidence_meta=evidence_meta,
            interruption=interruption,
            parent_result_ref=request.parent_result_ref,
        )

    def _store_and_first_page(
        self,
        *,
        request: BaseModel,
        source_ids: tuple[str, ...],
        fingerprint: str,
        result_kind: str,
        rows: Iterable[tuple[tuple[object, ...], BaseModel | dict[str, object]]],
        matched_count: int | None,
        entries: Iterable[DerivedResultEntry] | None = None,
        matched_count_from_rows: bool = False,
        customer_anchors: Iterable[CustomerAnchor] = (),
        cohorts: Iterable[PreparedCohort] = (),
        query_ref: str | None = None,
        evidence_meta: _EvidenceResponseMeta | None = None,
        interruption: ScanInterruptedError | None = None,
        parent_result_ref: str | None = None,
    ) -> ExplorationToolEnvelope:
        query_ref = query_ref or self.materializations.make_ref("query")
        result_ref = self.materializations.store_result(
            query_ref=query_ref,
            result_kind=result_kind,
            query_fingerprint=fingerprint,
            snapshot_id=self.reader.snapshot_id,
            source_ids=source_ids,
            rows=rows,
            entries=entries,
            matched_count=matched_count,
            scan_complete=interruption is None,
            matched_count_from_rows=matched_count_from_rows,
            customer_anchors=customer_anchors,
            cohorts=cohorts,
            partial_message=(str(interruption) if interruption is not None else None),
            remaining_branches=(
                interruption.remaining_branches if interruption is not None else ()
            ),
            retry_action=(
                "restart_query_without_cursor" if interruption is not None else None
            ),
            parent_result_ref=parent_result_ref,
        )
        return self._build_page(
            request=request,
            meta=self.materializations.read_result(result_ref),
            page_index=0,
            after_ordinal=None,
            evidence_meta=evidence_meta,
        )

    def _read_page(
        self,
        *,
        request: BaseModel,
        source_ids: tuple[str, ...],
        fingerprint: str,
        result_kind: str,
        evidence_parent_ref: str | None = None,
    ) -> ExplorationToolEnvelope:
        cursor = cast(str, getattr(request, "cursor"))
        page_size = cast(int, getattr(request, "page_size"))
        self.reader.assert_current_snapshot(source_ids)
        payload = self.reader.cursor_codec.decode_and_validate(
            cursor,
            run_id=self.materializations.run_id,
            generation=self.materializations.generation,
            query_fingerprint=fingerprint,
            snapshot_id=self.reader.snapshot_id,
            source_ids=source_ids,
            result_kind=result_kind,
            page_size=page_size,
        )
        meta = self.materializations.read_result(payload.result_ref)
        if payload.query_ref != meta.query_ref:
            raise CursorValidationError("cursor query_ref does not match its stored result")
        if (
            meta.query_fingerprint != fingerprint
            or meta.snapshot_id != self.reader.snapshot_id
            or meta.source_ids != tuple(sorted(source_ids))
            or meta.result_kind != result_kind
        ):
            raise CursorValidationError("cursor does not match stored result bindings")
        if meta.parent_result_ref != evidence_parent_ref:
            raise CursorValidationError(
                "cursor parent_result_ref does not match its stored result"
            )
        try:
            last_key = json.loads(payload.last_sort_key)
        except json.JSONDecodeError as error:
            raise CursorValidationError("cursor result ordinal is invalid") from error
        if (
            not isinstance(last_key, dict)
            or set(last_key) != {"ordinal"}
            or type(last_key["ordinal"]) is not int
            or last_key["ordinal"] < 0
        ):
            raise CursorValidationError("cursor result ordinal is invalid")
        evidence_meta = None
        if evidence_parent_ref is not None:
            candidate_count = self.materializations.authorized_customer_count(
                evidence_parent_ref
            )
            selection = cast(ReadEventEvidenceInput, request).selection
            selected = self.materializations.select_authorized_customers(
                evidence_parent_ref,
                customer_refs=selection.customer_refs,
                limit=selection.max_customers,
            )
            evidence_meta = _EvidenceResponseMeta(
                candidate_customer_count=candidate_count,
                selected_customer_count=len(selected.customers),
                selection_strategy=selected.strategy,
                events_before_match=selection.events_before_match,
                events_after_match=selection.events_after_match,
                selection_rationale=selected.rationale,
            )
        return self._build_page(
            request=request,
            meta=meta,
            page_index=payload.page_index,
            after_ordinal=last_key["ordinal"],
            evidence_meta=evidence_meta,
        )

    def _build_page(
        self,
        *,
        request: BaseModel,
        meta: MaterializedResult,
        page_index: int,
        after_ordinal: int | None,
        evidence_meta: _EvidenceResponseMeta | None = None,
    ) -> ExplorationToolEnvelope:
        page_size = cast(int, getattr(request, "page_size"))
        rows, has_more = self.materializations.read_result_page(
            meta.result_ref, after_ordinal=after_ordinal, page_size=page_size
        )
        items = tuple(
            _ITEM_ADAPTER.validate_json(canonical_json(row.item)) for row in rows
        )
        next_cursor = None
        if has_more:
            assert rows
            next_cursor = self.reader.cursor_codec.encode(
                CursorPayload(
                    run_id=self.materializations.run_id,
                    generation=self.materializations.generation,
                    query_fingerprint=meta.query_fingerprint,
                    snapshot_id=meta.snapshot_id,
                    source_ids=meta.source_ids,
                    result_kind=meta.result_kind,
                    query_ref=meta.query_ref,
                    result_ref=meta.result_ref,
                    page_index=page_index + 1,
                    page_size=page_size,
                    last_sort_key=canonical_json({"ordinal": rows[-1].ordinal}),
                )
            )
        page_ref = self.materializations.make_ref(
            "page", stable_value=f"{meta.result_ref}\0{page_index}"
        )
        partial = None
        if not meta.scan_complete:
            assert meta.partial_message is not None
            assert meta.remaining_branches
            assert meta.retry_action == "restart_query_without_cursor"
            partial = ExplorationPartialState(
                message=meta.partial_message,
                remaining_branches=meta.remaining_branches,
                retry_action="restart_query_without_cursor",
            )
        return ExplorationToolEnvelope(
            status="success" if meta.scan_complete else "partial",
            result=ExplorationResult(
                query_ref=meta.query_ref,
                result_ref=meta.result_ref,
                page_ref=page_ref,
                items=items,
                candidate_customer_count=(
                    evidence_meta.candidate_customer_count if evidence_meta else None
                ),
                selected_customer_count=(
                    evidence_meta.selected_customer_count if evidence_meta else None
                ),
                selection_strategy=(
                    cast(Any, evidence_meta.selection_strategy) if evidence_meta else None
                ),
                events_before_match=(
                    evidence_meta.events_before_match if evidence_meta else None
                ),
                events_after_match=(
                    evidence_meta.events_after_match if evidence_meta else None
                ),
                selection_rationale=(
                    evidence_meta.selection_rationale if evidence_meta else None
                ),
            ),
            page=ExplorationPage(
                page_index=page_index,
                page_size=page_size,
                returned_count=len(items),
                matched_count=meta.matched_count,
                has_more=has_more,
                next_cursor=next_cursor,
                scan_complete=meta.scan_complete,
            ),
            coverage=ExplorationCoverage(
                snapshot_id=meta.snapshot_id,
                query_fingerprint=meta.query_fingerprint,
            ),
            error=None,
            partial=partial,
        )

    def _validate_summary_request(
        self, request: SummarizeEventsInput, source_ids: tuple[str, ...]
    ) -> None:
        for predicate in request.predicates:
            self.fields.validate_predicate(predicate, source_ids)
        for field_ref in request.group_by:
            self.fields.validate_field(
                field_ref, source_ids, value_access_required=True
            )
        for metric in request.metrics:
            if isinstance(metric, NumericMetric):
                self.fields.validate_field(metric.field, source_ids, numeric_required=True)
            elif isinstance(metric, RatioMetric):
                for predicate in (
                    *metric.denominator_predicates,
                    *metric.numerator_predicates,
                ):
                    self.fields.validate_predicate(predicate, source_ids)
        if request.cohort_ref is not None:
            self.materializations.resolve_cohort(request.cohort_ref)

    def _validate_sequence_request(
        self,
        request: RepetitionInput | SequenceInput | FunnelInput,
        source_ids: tuple[str, ...],
    ) -> None:
        for field_ref in request.group_by:
            self.fields.validate_field(
                field_ref, source_ids, value_access_required=True
            )
        if isinstance(request, RepetitionInput):
            for predicate in request.target.event_predicates:
                self.fields.validate_predicate(predicate, source_ids)
            for field_ref in request.target.grouping_fields:
                self.fields.validate_field(
                    field_ref, source_ids, value_access_required=True
                )
        else:
            for step in request.steps:
                if not set(step.source_ids) <= set(source_ids):
                    raise DataSpacePermissionError(
                        "sequence step sources must be inside query source_ids"
                    )
                for predicate in step.event_predicates:
                    self.fields.validate_predicate(predicate, step.source_ids)
        if request.cohort_ref is not None:
            self.materializations.resolve_cohort(request.cohort_ref)

    def _event_is_sequence_candidate(
        self,
        event: CustomerEvent,
        request: RepetitionInput | SequenceInput | FunnelInput,
    ) -> bool:
        if isinstance(request, RepetitionInput):
            if not self.fields.matches(event, request.target.event_predicates):
                return False
            return all(
                self.fields.lookup(event, field_ref).applicable
                for field_ref in request.target.grouping_fields
            )
        return any(self._matches_step(event, step) for step in request.steps)

    def _matches_step(self, event: CustomerEvent | WorkEvent, step: SequenceStep) -> bool:
        return event.source_id in step.source_ids and self.fields.matches(
            cast(CustomerEvent, event), step.event_predicates
        )

    def _repetition_matches(
        self,
        query_ref: str,
        customer_id: str,
        events: list[WorkEvent],
        request: RepetitionInput,
    ) -> list[_SequenceMatch]:
        grouped: dict[tuple[object, ...], list[WorkEvent]] = defaultdict(list)
        for event in events:
            key = tuple(
                self.fields.lookup(cast(CustomerEvent, event), field_ref).value
                for field_ref in request.target.grouping_fields
            )
            grouped[key].append(event)
        matches: list[_SequenceMatch] = []
        max_gap = timedelta(minutes=request.target.max_gap_minutes)
        customer_ref = self.materializations.make_ref(
            "customer", stable_value=customer_id
        )
        for values, grouped_events in sorted(
            grouped.items(), key=lambda item: canonical_json(item[0])
        ):
            clusters: list[list[WorkEvent]] = []
            for event in grouped_events:
                if (
                    not clusters
                    or event.occurred_at - clusters[-1][-1].occurred_at > max_gap
                ):
                    clusters.append([event])
                else:
                    clusters[-1].append(event)
            for cluster_index, cluster in enumerate(clusters):
                if len(cluster) < request.target.min_occurrences:
                    continue
                completion = cluster[request.target.min_occurrences - 1]
                group_values = tuple(
                    PublicSemanticValue(field=field_ref, value=cast(Any, value))
                    for field_ref, value in zip(
                        request.target.grouping_fields, values, strict=True
                    )
                )
                existing_fields = set(request.target.grouping_fields)
                extra_values = tuple(
                    PublicSemanticValue(
                        field=field_ref,
                        value=cast(
                            Any,
                            self.fields.lookup(
                                cast(CustomerEvent, completion), field_ref
                            ).value,
                        ),
                    )
                    for field_ref in request.group_by
                    if field_ref not in existing_fields
                    and self.fields.lookup(
                        cast(CustomerEvent, completion), field_ref
                    ).applicable
                )
                group_values += extra_values
                stable = canonical_json(
                    [customer_id, list(values), cluster[0].occurred_at, cluster_index]
                )
                cohort_ref = self.materializations.make_ref(
                    "cohort", stable_value=f"{query_ref}\0{stable}"
                )
                span = (cluster[-1].occurred_at - cluster[0].occurred_at).total_seconds() / 60
                item = PublicSequenceItem(
                    mode="repetition",
                    customer_ref=customer_ref,
                    cohort_ref=cohort_ref,
                    group_values=group_values,
                    occurrence_count=len(cluster),
                    completed_step_count=1,
                    total_step_count=1,
                    completed_step_ids=("repetition_target",),
                    first_match_at=cluster[0].occurred_at,
                    last_match_at=cluster[-1].occurred_at,
                    span_minutes=span,
                )
                matches.append(
                    _SequenceMatch(
                        item=item,
                        sort_key=(
                            -len(cluster),
                            customer_ref,
                            canonical_json(values),
                            cluster[0].occurred_at.isoformat(),
                        ),
                        anchor=_work_anchor(customer_id, completion),
                        cohort=PreparedCohort(
                            cohort_ref=cohort_ref,
                            canonical_customer_ids=(customer_id,),
                        ),
                    )
                )
        return matches

    def _ordered_sequence_match(
        self,
        query_ref: str,
        customer_id: str,
        events: list[WorkEvent],
        request: SequenceInput | FunnelInput,
    ) -> _SequenceMatch | None:
        cursor_index = 0
        completed: list[tuple[SequenceStep, WorkEvent, WorkEvent]] = []
        first_match: WorkEvent | None = None
        previous_completion_at: datetime | None = None
        for step in request.steps:
            occurrences: list[tuple[int, WorkEvent]] = []
            for index in range(cursor_index, len(events)):
                event = events[index]
                if (
                    previous_completion_at is not None
                    and event.occurred_at <= previous_completion_at
                ):
                    continue
                if self._matches_step(event, step):
                    occurrences.append((index, event))
                    if len(occurrences) == step.min_occurrences:
                        break
            if len(occurrences) < step.min_occurrences:
                break
            if first_match is None:
                first_match = occurrences[0][1]
            completion = occurrences[-1][1]
            if (
                completion.occurred_at - first_match.occurred_at
                > timedelta(minutes=request.max_total_span_minutes)
            ):
                break
            completed.append((step, occurrences[0][1], completion))
            previous_completion_at = completion.occurred_at
            cursor_index = occurrences[-1][0] + 1
        if not completed:
            return None
        if isinstance(request, SequenceInput) and len(completed) != len(request.steps):
            return None
        assert first_match is not None
        last_match = completed[-1][2]
        customer_ref = self.materializations.make_ref(
            "customer", stable_value=customer_id
        )
        cohort_ref = self.materializations.make_ref(
            "cohort", stable_value=f"{query_ref}\0{customer_id}"
        )
        dropoff = (
            completed[-1][0].step_id
            if isinstance(request, FunnelInput) and len(completed) < len(request.steps)
            else None
        )
        span = (last_match.occurred_at - first_match.occurred_at).total_seconds() / 60
        completion_events = [completion for _, _, completion in completed]
        group_values = []
        for field_ref in request.group_by:
            lookup = next(
                (
                    lookup
                    for event in completion_events
                    if (
                        lookup := self.fields.lookup(
                            cast(CustomerEvent, event), field_ref
                        )
                    ).applicable
                ),
                None,
            )
            if lookup is not None:
                group_values.append(
                    PublicSemanticValue(
                        field=field_ref,
                        value=cast(Any, lookup.value),
                    )
                )
        item = PublicSequenceItem(
            mode=request.mode,
            customer_ref=customer_ref,
            cohort_ref=cohort_ref,
            group_values=tuple(group_values),
            occurrence_count=None,
            completed_step_count=len(completed),
            total_step_count=len(request.steps),
            completed_step_ids=tuple(step.step_id for step, _, _ in completed),
            dropoff_after_step_id=dropoff,
            first_match_at=first_match.occurred_at,
            last_match_at=last_match.occurred_at,
            span_minutes=span,
        )
        return _SequenceMatch(
            item=item,
            sort_key=(
                -len(completed),
                customer_ref,
                canonical_json([value.value for value in group_values]),
            ),
            anchor=_work_anchor(customer_id, last_match),
            cohort=PreparedCohort(
                cohort_ref=cohort_ref,
                canonical_customer_ids=(customer_id,),
            ),
        )

    def _metric_value(
        self,
        metric: MetricSpec,
        index: int,
        current: _SummaryStats,
        *,
        partial: bool = False,
    ) -> PublicMetricValue:
        partial_limitation = (
            "partial input scan; value reflects only the acquired stable prefix"
            if partial
            else None
        )
        if isinstance(metric, CountMetric):
            value = (
                current.event_count
                if metric.operation == "event_count"
                else len(current.customers)
            )
            return PublicMetricValue(
                name=metric.operation,
                value=value,
                unit="events" if metric.operation == "event_count" else "customers",
                limitation=partial_limitation,
            )
        if isinstance(metric, NumericMetric):
            stats = current.numeric.get(index, _NumericStats())
            values = {
                "sum": stats.total if stats.count else None,
                "average": stats.total / stats.count if stats.count else None,
                "minimum": stats.minimum,
                "maximum": stats.maximum,
            }
            return PublicMetricValue(
                name=f"{metric.operation}:{metric.field.source_id}.{metric.field.name}",
                value=values[metric.operation],
                unit="number",
                limitation=(
                    partial_limitation
                    or ("no numeric values in this group" if stats.count == 0 else None)
                ),
            )
        assert isinstance(metric, RatioMetric)
        stats = current.ratios.get(index, _RatioStats())
        if metric.basis == "events":
            numerator = stats.numerator_events
            denominator = stats.denominator_events
        else:
            numerator = len(stats.numerator_customers)
            denominator = len(stats.denominator_customers)
        if partial:
            value = None
            limitation = "partial input scan; ratio is unavailable until retry completes"
        elif denominator == 0:
            value = None
            limitation = "ratio denominator is zero"
        else:
            value = numerator / denominator
            if metric.unit == "percent":
                value *= 100
            limitation = None
        return PublicMetricValue(
            name=f"ratio_{index + 1}",
            value=value,
            unit=metric.unit,
            limitation=limitation,
        )

    def _scan_prefix(
        self,
        scope: ExplorationSourceScope,
        consumer: Any,
    ) -> ScanInterruptedError | None:
        try:
            self.reader.scan_events(scope, consumer=consumer)
        except ScanInterruptedError as error:
            return error
        return None

    def _scope(
        self,
        source_ids: tuple[str, ...],
        time_range: object | None = None,
    ) -> ExplorationSourceScope:
        start_at = (
            cast(Any, time_range).start_at
            if time_range is not None
            else self.reader.authorized_scope.start_at
        )
        end_at = (
            cast(Any, time_range).end_at
            if time_range is not None
            else self.reader.authorized_scope.end_at
        )
        return ExplorationSourceScope(
            source_ids=source_ids,
            start_at=start_at,
            end_at=end_at,
            native_page_size=self.reader.authorized_scope.native_page_size,
        )

    def _known_error(self, request: object, error: Exception) -> ExplorationToolEnvelope:
        if (
            isinstance(error, SnapshotChangedDuringScanError)
            and self.ledger.generation != self.materializations.generation
        ):
            self.ledger.reset_for_snapshot_change()
        if isinstance(
            error,
            (
                ScanInterruptedError,
                SnapshotBarrierUnavailableError,
                SnapshotChangedDuringScanError,
            ),
        ):
            category = "transient"
            retryable = True
        elif isinstance(
            error,
            (DataSpacePermissionError, ForeignRunReferenceError),
        ):
            category = "permission"
            retryable = False
        elif isinstance(
            error,
            (
                CursorValidationError,
                FieldValidationError,
                StaleSnapshotReferenceError,
                UnknownMaterializationReferenceError,
                MaterializationError,
                ExplorationLedgerError,
                ValueError,
            ),
        ):
            category = "validation"
            retryable = False
        else:
            raise error
        page_size = getattr(request, "page_size", 50)
        try:
            fingerprint = query_fingerprint(request)
        except Exception:
            fingerprint = "0" * 64
        return ExplorationToolEnvelope(
            status="error",
            result=ExplorationResult(items=()),
            page=ExplorationPage(
                page_index=0,
                page_size=page_size if type(page_size) is int and 1 <= page_size <= 200 else 50,
                returned_count=0,
                matched_count=None,
                has_more=False,
                next_cursor=None,
                scan_complete=False,
            ),
            coverage=ExplorationCoverage(
                snapshot_id=self.reader.snapshot_id,
                query_fingerprint=fingerprint,
            ),
            error=ToolError(
                category=cast(Any, category),
                is_retryable=retryable,
                message=str(error)[:1_000] or type(error).__name__,
            ),
        )


def _event_key(event: CustomerEvent) -> tuple[datetime, str, str]:
    return (event.occurred_at, event.source_id, event.event_id)


def _remember_anchor(anchors: dict[str, CustomerAnchor], event: CustomerEvent) -> None:
    candidate = CustomerAnchor(
        canonical_customer_id=event.canonical_customer_id,
        anchor_at=event.occurred_at,
        anchor_source_id=event.source_id,
        anchor_event_id=event.event_id,
    )
    current = anchors.get(event.canonical_customer_id)
    if current is None or (
        candidate.anchor_at,
        candidate.anchor_source_id,
        candidate.anchor_event_id,
    ) < (current.anchor_at, current.anchor_source_id, current.anchor_event_id):
        anchors[event.canonical_customer_id] = candidate


def _work_anchor(customer_id: str, event: WorkEvent) -> CustomerAnchor:
    return CustomerAnchor(
        canonical_customer_id=customer_id,
        anchor_at=event.occurred_at,
        anchor_source_id=event.source_id,
        anchor_event_id=event.event_id,
    )


def _sequence_projection_fields(
    request: RepetitionInput | SequenceInput | FunnelInput,
) -> tuple[ExplorationFieldRef, ...]:
    candidates = list(request.group_by)
    if isinstance(request, RepetitionInput):
        candidates.extend(request.target.grouping_fields)
        candidates.extend(
            predicate.field for predicate in request.target.event_predicates
        )
    else:
        candidates.extend(
            predicate.field
            for step in request.steps
            for predicate in step.event_predicates
        )
    unique: dict[tuple[str, str | None, str], ExplorationFieldRef] = {}
    for field_ref in candidates:
        unique[(field_ref.scope, field_ref.source_id, field_ref.name)] = field_ref
    return tuple(unique[key] for key in sorted(unique))


def _project_source_fields(
    compiler: ExplorationFieldCompiler,
    event: CustomerEvent,
    fields: tuple[ExplorationFieldRef, ...],
) -> tuple[dict[str, object], dict[str, object]]:
    dimensions: dict[str, object] = {}
    measures: dict[str, object] = {}
    for field_ref in fields:
        if field_ref.scope == "canonical":
            continue
        lookup = compiler.lookup(event, field_ref)
        if not lookup.applicable:
            continue
        target = dimensions if field_ref.scope == "dimension" else measures
        target[field_ref.name] = lookup.value
    return dimensions, measures


def _time_bucket(value: datetime, bucket: str | None) -> datetime | None:
    if bucket is None:
        return None
    if bucket == "hour":
        return value.replace(minute=0, second=0, microsecond=0)
    if bucket == "day":
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    day = value.replace(hour=0, minute=0, second=0, microsecond=0)
    return day - timedelta(days=day.weekday())


def _neutral_label(label: str, source_id: str) -> str:
    del label
    return source_id


__all__ = [
    "ExplorationTools",
    "TOOL_DESCRIPTIONS",
    "exploration_tool_json_schema",
]
