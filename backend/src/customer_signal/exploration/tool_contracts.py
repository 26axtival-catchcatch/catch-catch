"""Strict, storage-neutral contracts for the four read-only exploration Tools."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    field_validator,
    model_validator,
)

from customer_signal.exploration.contracts import ToolError, ToolStatus


type PublicScalar = str | int | float | bool | None
type FieldScope = Literal["canonical", "dimension", "measure"]


class ToolContract(BaseModel):
    """Immutable and strict public model; unknown Agent input always fails closed."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ExplorationTimeRange(ToolContract):
    start_at: AwareDatetime
    end_at: AwareDatetime

    @model_validator(mode="after")
    def require_half_open_range(self) -> Self:
        if self.start_at >= self.end_at:
            raise ValueError("start_at must be before exclusive end_at")
        return self


class ExplorationFieldRef(ToolContract):
    scope: FieldScope
    name: str = Field(min_length=1, max_length=128)
    source_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def bind_source_to_scope(self) -> Self:
        if self.scope == "canonical" and self.source_id is not None:
            raise ValueError("canonical fields require source_id=null")
        if self.scope != "canonical" and self.source_id is None:
            raise ValueError("dimension and measure fields require source_id")
        return self


class ComparisonPredicate(ToolContract):
    kind: Literal["comparison"]
    field: ExplorationFieldRef
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte"]
    value: str | int | float | bool


class MembershipPredicate(ToolContract):
    kind: Literal["membership"]
    field: ExplorationFieldRef
    operator: Literal["in", "not_in"]
    values: tuple[str | int | float | bool, ...] = Field(min_length=1, max_length=100)

    @field_validator("values", mode="before")
    @classmethod
    def freeze_values(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class TextPredicate(ToolContract):
    kind: Literal["text"]
    field: ExplorationFieldRef
    operator: Literal["contains", "starts_with"]
    value: str = Field(min_length=1, max_length=1_000)
    case_sensitive: bool = False


class ExistsPredicate(ToolContract):
    kind: Literal["exists"]
    field: ExplorationFieldRef
    present: bool


type Predicate = Annotated[
    ComparisonPredicate | MembershipPredicate | TextPredicate | ExistsPredicate,
    Field(discriminator="kind"),
]


class CountMetric(ToolContract):
    kind: Literal["count"]
    operation: Literal["event_count", "distinct_customer_count"]


class NumericMetric(ToolContract):
    kind: Literal["numeric"]
    operation: Literal["sum", "average", "minimum", "maximum"]
    field: ExplorationFieldRef

    @model_validator(mode="after")
    def require_measure(self) -> Self:
        if self.field.scope != "measure":
            raise ValueError("numeric metrics require a measure field")
        return self


class RatioMetric(ToolContract):
    kind: Literal["ratio"]
    basis: Literal["events", "distinct_customers"]
    numerator_predicates: tuple[Predicate, ...] = Field(default_factory=tuple, max_length=20)
    denominator_predicates: tuple[Predicate, ...] = Field(default_factory=tuple, max_length=20)
    unit: Literal["fraction", "percent"] = "fraction"

    @field_validator("numerator_predicates", "denominator_predicates", mode="before")
    @classmethod
    def freeze_predicates(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


type MetricSpec = Annotated[CountMetric | NumericMetric | RatioMetric, Field(discriminator="kind")]


class _PagedInput(ToolContract):
    cursor: str | None = Field(default=None, min_length=1, max_length=16_384)
    page_size: int = Field(default=50, strict=True, ge=1, le=200)


class InspectSourcesInput(_PagedInput):
    view: Literal["sources"]
    source_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=32)

    @field_validator("source_ids", mode="before")
    @classmethod
    def normalize_sources(cls, value: object) -> object:
        if isinstance(value, list):
            value = tuple(value)
        if isinstance(value, tuple):
            if len(value) != len(set(value)):
                raise ValueError("source_ids must be unique")
            return tuple(sorted(value))
        return value


class InspectFieldsInput(_PagedInput):
    view: Literal["fields"]
    source_ids: tuple[str, ...] = Field(min_length=1, max_length=32)

    @field_validator("source_ids", mode="before")
    @classmethod
    def normalize_sources(cls, value: object) -> object:
        value = tuple(value) if isinstance(value, list) else value
        if isinstance(value, tuple):
            if len(value) != len(set(value)):
                raise ValueError("source_ids must be unique")
            return tuple(sorted(value))
        return value


class InspectValuesInput(_PagedInput):
    view: Literal["values"]
    source_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    field: ExplorationFieldRef
    predicates: tuple[Predicate, ...] = Field(default_factory=tuple, max_length=20)

    @field_validator("source_ids", "predicates", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @field_validator("source_ids")
    @classmethod
    def normalize_sources(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("source_ids must be unique")
        return tuple(sorted(value))


type InspectDataSpaceInput = Annotated[
    InspectSourcesInput | InspectFieldsInput | InspectValuesInput,
    Field(discriminator="view"),
]


class SummarizeEventsInput(_PagedInput):
    source_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    time_range: ExplorationTimeRange
    predicates: tuple[Predicate, ...] = Field(default_factory=tuple, max_length=20)
    cohort_ref: str | None = Field(default=None, min_length=1, max_length=128)
    group_by: tuple[ExplorationFieldRef, ...] = Field(default_factory=tuple, max_length=5)
    metrics: tuple[MetricSpec, ...] = Field(min_length=1, max_length=10)
    time_bucket: Literal["hour", "day", "week"] | None = None

    @field_validator("source_ids", "predicates", "group_by", "metrics", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("source_ids")
    @classmethod
    def normalize_sources(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("source_ids must be unique")
        return tuple(sorted(value))


class SequenceStep(ToolContract):
    step_id: str = Field(pattern=r"^[a-z][a-z0-9_\-]{0,63}$")
    source_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    event_predicates: tuple[Predicate, ...] = Field(default_factory=tuple, max_length=20)
    min_occurrences: int = Field(default=1, strict=True, ge=1, le=100)

    @field_validator("source_ids", "event_predicates", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("source_ids")
    @classmethod
    def normalize_sources(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("source_ids must be unique")
        return tuple(sorted(value))


class RepetitionTarget(ToolContract):
    event_predicates: tuple[Predicate, ...] = Field(default_factory=tuple, max_length=20)
    grouping_fields: tuple[ExplorationFieldRef, ...] = Field(default_factory=tuple, max_length=5)
    min_occurrences: int = Field(default=2, strict=True, ge=2, le=100)
    max_gap_minutes: int = Field(strict=True, ge=1, le=525_600)

    @field_validator("event_predicates", "grouping_fields", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class _SequenceBase(_PagedInput):
    source_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    time_range: ExplorationTimeRange
    cohort_ref: str | None = Field(default=None, min_length=1, max_length=128)
    group_by: tuple[ExplorationFieldRef, ...] = Field(default_factory=tuple, max_length=5)

    @field_validator("source_ids", "group_by", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("source_ids")
    @classmethod
    def normalize_sources(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("source_ids must be unique")
        return tuple(sorted(value))


class RepetitionInput(_SequenceBase):
    mode: Literal["repetition"]
    target: RepetitionTarget


class SequenceInput(_SequenceBase):
    mode: Literal["sequence"]
    steps: tuple[SequenceStep, ...] = Field(min_length=2, max_length=12)
    max_total_span_minutes: int = Field(strict=True, ge=1, le=525_600)

    @field_validator("steps", mode="before")
    @classmethod
    def freeze_steps(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("steps")
    @classmethod
    def unique_step_ids(cls, value: tuple[SequenceStep, ...]) -> tuple[SequenceStep, ...]:
        if len({step.step_id for step in value}) != len(value):
            raise ValueError("sequence step_id values must be unique")
        return value


class FunnelInput(_SequenceBase):
    mode: Literal["funnel"]
    steps: tuple[SequenceStep, ...] = Field(min_length=2, max_length=12)
    max_total_span_minutes: int = Field(strict=True, ge=1, le=525_600)

    @field_validator("steps", mode="before")
    @classmethod
    def freeze_steps(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("steps")
    @classmethod
    def unique_step_ids(cls, value: tuple[SequenceStep, ...]) -> tuple[SequenceStep, ...]:
        if len({step.step_id for step in value}) != len(value):
            raise ValueError("funnel step_id values must be unique")
        return value


type AnalyzeEventSequencesInput = Annotated[
    RepetitionInput | SequenceInput | FunnelInput,
    Field(discriminator="mode"),
]


class EvidenceSelection(ToolContract):
    strategy: Literal["representative"]
    customer_refs: tuple[str, ...] = Field(default_factory=tuple, max_length=3)
    max_customers: int = Field(default=3, strict=True, ge=1, le=3)
    events_before_match: int = Field(default=5, strict=True, ge=0, le=5)
    events_after_match: int = Field(default=10, strict=True, ge=0, le=10)

    @field_validator("customer_refs", mode="before")
    @classmethod
    def freeze_customers(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("customer_refs")
    @classmethod
    def unique_customers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("customer_refs must be unique")
        return value

    @model_validator(mode="after")
    def bound_explicit_selection(self) -> Self:
        if len(self.customer_refs) > self.max_customers:
            raise ValueError("customer_refs cannot exceed max_customers")
        return self


class ReadEventEvidenceInput(_PagedInput):
    parent_result_ref: str = Field(min_length=1, max_length=128)
    selection: EvidenceSelection
    include_fields: tuple[ExplorationFieldRef, ...] = Field(default_factory=tuple, max_length=20)

    @field_validator("include_fields", mode="before")
    @classmethod
    def freeze_fields(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class PublicSemanticValue(ToolContract):
    field: ExplorationFieldRef
    value: PublicScalar


class PublicMetricValue(ToolContract):
    name: str = Field(min_length=1, max_length=256)
    value: FiniteFloat | int | None
    unit: str = Field(min_length=1, max_length=64)
    limitation: str | None = Field(default=None, min_length=1, max_length=500)


class PublicSourceCatalogItem(ToolContract):
    item_kind: Literal["source"] = "source"
    source_id: str
    label: str
    observed_start_at: AwareDatetime | None
    observed_end_at: AwareDatetime | None
    row_count: int = Field(strict=True, ge=0)
    event_types: tuple[str, ...] = Field(default=(), max_length=64)
    actions: tuple[str, ...] = Field(default=(), max_length=64)
    topics: tuple[str, ...] = Field(default=(), max_length=64)
    outcomes: tuple[str, ...] = Field(default=(), max_length=64)
    vocabulary_limit: Literal[64] = 64
    truncated_fields: tuple[
        Literal["event_type", "action", "topic", "outcome"], ...
    ] = Field(default=(), max_length=4)
    vocabulary_limitation: str = Field(
        default=(
            "Canonical vocabularies are bounded; use inspect_data_space view=values "
            "for each field listed in truncated_fields."
        ),
        min_length=1,
        max_length=500,
    )


class PublicFieldCatalogItem(ToolContract):
    item_kind: Literal["field"] = "field"
    source_id: str
    scope: FieldScope
    name: str
    data_type: Literal["timestamp", "string", "text", "boolean", "integer", "number"]
    nullable: bool
    value_access: Literal["enumerable", "cardinality_only"]
    missing_rate: FiniteFloat | None = Field(default=None, ge=0, le=1)


class PublicValueCatalogItem(ToolContract):
    item_kind: Literal["value"] = "value"
    field: ExplorationFieldRef
    value: PublicScalar
    count: int = Field(strict=True, ge=0)
    missing_rate: FiniteFloat = Field(ge=0, le=1)


class PublicSummaryItem(ToolContract):
    item_kind: Literal["summary"] = "summary"
    bucket_start: AwareDatetime | None = None
    group_values: tuple[PublicSemanticValue, ...] = ()
    metrics: tuple[PublicMetricValue, ...]
    cohort_ref: str


class PublicSequenceItem(ToolContract):
    item_kind: Literal["sequence"] = "sequence"
    mode: Literal["repetition", "sequence", "funnel"]
    customer_ref: str
    cohort_ref: str
    group_values: tuple[PublicSemanticValue, ...] = ()
    occurrence_count: int | None = Field(default=None, strict=True, ge=1)
    completed_step_count: int = Field(strict=True, ge=0)
    total_step_count: int = Field(strict=True, ge=1)
    completed_step_ids: tuple[str, ...] = ()
    dropoff_after_step_id: str | None = None
    first_match_at: AwareDatetime
    last_match_at: AwareDatetime
    span_minutes: FiniteFloat = Field(ge=0)


class PublicExplorationEvidenceEvent(ToolContract):
    item_kind: Literal["evidence"] = "evidence"
    evidence_id: str
    source_id: str
    occurred_at: AwareDatetime
    event_type: str
    action: str
    topic: str
    outcome: str
    customer_ref: str
    semantic_fields: tuple[PublicSemanticValue, ...] = ()


type PublicExplorationItem = Annotated[
    PublicSourceCatalogItem
    | PublicFieldCatalogItem
    | PublicValueCatalogItem
    | PublicSummaryItem
    | PublicSequenceItem
    | PublicExplorationEvidenceEvent,
    Field(discriminator="item_kind"),
]


class ExplorationResult(ToolContract):
    query_ref: str | None = None
    result_ref: str | None = None
    page_ref: str | None = None
    items: tuple[PublicExplorationItem, ...] = ()
    candidate_customer_count: int | None = Field(default=None, strict=True, ge=0)
    selected_customer_count: int | None = Field(default=None, strict=True, ge=0, le=3)
    selection_strategy: Literal["representative", "explicit"] | None = None
    events_before_match: int | None = Field(default=None, strict=True, ge=0, le=5)
    events_after_match: int | None = Field(default=None, strict=True, ge=0, le=10)
    selection_rationale: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def bind_evidence_selection_metadata(self) -> Self:
        evidence_meta = (
            self.candidate_customer_count,
            self.selected_customer_count,
            self.selection_strategy,
            self.events_before_match,
            self.events_after_match,
            self.selection_rationale,
        )
        if any(value is not None for value in evidence_meta) and not all(
            value is not None for value in evidence_meta
        ):
            raise ValueError("evidence selection metadata must be supplied together")
        if (
            self.candidate_customer_count is not None
            and self.selected_customer_count is not None
            and self.selected_customer_count > self.candidate_customer_count
        ):
            raise ValueError("selected_customer_count cannot exceed candidate_customer_count")
        return self


class ExplorationPage(ToolContract):
    page_index: int = Field(strict=True, ge=0)
    page_size: int = Field(strict=True, ge=1, le=200)
    returned_count: int = Field(strict=True, ge=0)
    matched_count: int | None = Field(default=None, strict=True, ge=0)
    has_more: bool
    next_cursor: str | None = None
    scan_complete: bool

    @model_validator(mode="after")
    def bind_cursor_and_count(self) -> Self:
        if self.has_more != (self.next_cursor is not None):
            raise ValueError("next_cursor must exist exactly when has_more is true")
        if not self.scan_complete and self.matched_count is not None:
            raise ValueError("matched_count is unknown until the input scan completes")
        return self


class ExplorationCoverage(ToolContract):
    snapshot_id: str
    query_fingerprint: str


class ExplorationPartialState(ToolContract):
    """Actionable description of the source space left by a controlled interruption."""

    category: Literal["transient"] = "transient"
    is_retryable: Literal[True] = True
    message: str = Field(min_length=1, max_length=1_000)
    remaining_branches: tuple[str, ...] = Field(min_length=1, max_length=32)
    retry_action: Literal["restart_query_without_cursor"]

    @field_validator("remaining_branches", mode="before")
    @classmethod
    def freeze_branches(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("remaining_branches")
    @classmethod
    def normalize_branches(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("remaining_branches must be unique")
        return tuple(sorted(value))


class ExplorationToolEnvelope(ToolContract):
    status: ToolStatus
    result: ExplorationResult
    page: ExplorationPage
    coverage: ExplorationCoverage
    error: ToolError | None = None
    partial: ExplorationPartialState | None = None

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.status == "error":
            if self.error is None or self.partial is not None or self.result.items:
                raise ValueError("error responses require an error and no result items")
        elif self.error is not None:
            raise ValueError("successful or partial responses cannot include an error")
        if self.status == "partial":
            if self.partial is None or self.page.scan_complete:
                raise ValueError(
                    "partial responses require partial state and scan_complete=false"
                )
        if self.status == "success":
            if self.partial is not None or not self.page.scan_complete:
                raise ValueError(
                    "success responses require no partial state and scan_complete=true"
                )
        if self.status != "error" and (
            self.result.query_ref is None
            or self.result.result_ref is None
            or self.result.page_ref is None
        ):
            raise ValueError("non-error responses require query, result, and page references")
        return self


__all__ = [
    "AnalyzeEventSequencesInput",
    "ComparisonPredicate",
    "CountMetric",
    "EvidenceSelection",
    "ExistsPredicate",
    "ExplorationCoverage",
    "ExplorationFieldRef",
    "ExplorationPage",
    "ExplorationPartialState",
    "ExplorationResult",
    "ExplorationTimeRange",
    "ExplorationToolEnvelope",
    "FunnelInput",
    "InspectDataSpaceInput",
    "InspectFieldsInput",
    "InspectSourcesInput",
    "InspectValuesInput",
    "MembershipPredicate",
    "MetricSpec",
    "NumericMetric",
    "Predicate",
    "PublicExplorationEvidenceEvent",
    "PublicExplorationItem",
    "PublicFieldCatalogItem",
    "PublicMetricValue",
    "PublicSemanticValue",
    "PublicSequenceItem",
    "PublicSourceCatalogItem",
    "PublicSummaryItem",
    "PublicValueCatalogItem",
    "RatioMetric",
    "ReadEventEvidenceInput",
    "RepetitionInput",
    "RepetitionTarget",
    "SequenceInput",
    "SequenceStep",
    "SummarizeEventsInput",
    "TextPredicate",
]
