"""Machine-readable contracts for the terminal-only exploration evaluator."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


type EvaluationToolName = Literal[
    "inspect_data_space",
    "summarize_events",
    "analyze_event_sequences",
    "read_event_evidence",
    "submit_exploration_report",
]
type SequenceMode = Literal["repetition", "sequence", "funnel"]
type Direction = Literal["increase", "decrease", "unchanged"]


class _EvaluationContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EvaluationSourceGroup(_EvaluationContract):
    group_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    source_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    minimum_sources: int = Field(strict=True, ge=1, le=32)

    @field_validator("source_ids", mode="before")
    @classmethod
    def freeze_sources(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_sources(self) -> Self:
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("source_ids must be unique")
        if self.minimum_sources > len(self.source_ids):
            raise ValueError("minimum_sources cannot exceed source_ids")
        return self


class ToolResultPredicate(_EvaluationContract):
    kind: Literal["tool_result"]
    tool_names: tuple[EvaluationToolName, ...] = Field(min_length=1, max_length=5)
    modes: tuple[SequenceMode, ...] = Field(default_factory=tuple, max_length=3)
    source_group_ids: tuple[str, ...] = Field(min_length=1, max_length=8)
    minimum_complete_result_refs: int = Field(strict=True, ge=0, le=48)
    scan_complete: Literal[True]

    @field_validator("tool_names", "modes", "source_group_ids", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class MetricPredicate(_EvaluationContract):
    kind: Literal["metric"]
    metric_names: tuple[str, ...] = Field(min_length=1, max_length=24)
    minimum_metrics: int = Field(strict=True, ge=1, le=24)

    @field_validator("metric_names", mode="before")
    @classmethod
    def freeze_metrics(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class EvidencePredicate(_EvaluationContract):
    kind: Literal["evidence"]
    minimum_evidence_ids: int = Field(strict=True, ge=1, le=48)
    require_authorized_parent_result: Literal[True]


class SequencePredicate(_EvaluationContract):
    kind: Literal["sequence_or_funnel"]
    accepted_modes: tuple[SequenceMode, ...] = Field(min_length=1, max_length=3)
    minimum_complete_result_refs: int = Field(strict=True, ge=1, le=48)

    @field_validator("accepted_modes", mode="before")
    @classmethod
    def freeze_modes(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class RecommendationPredicate(_EvaluationContract):
    kind: Literal["recommendation"]
    expected_directions: tuple[Direction, ...] = Field(min_length=1, max_length=3)
    minimum_recommendations: int = Field(strict=True, ge=1, le=12)

    @field_validator("expected_directions", mode="before")
    @classmethod
    def freeze_directions(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class OracleDirectionPredicate(_EvaluationContract):
    kind: Literal["oracle_direction"]
    oracle_metric: str = Field(min_length=1, max_length=128)
    expected_direction: Direction
    baseline_phase: Literal["baseline"] = "baseline"
    comparison_phase: Literal["post"] = "post"


class CausalLimitationPredicate(_EvaluationContract):
    kind: Literal["causal_limitation"]
    minimum_limitations: int = Field(strict=True, ge=1, le=24)
    observation_hypothesis_separate: Literal[True]


class CoveragePredicate(_EvaluationContract):
    kind: Literal["coverage"]
    require_sources_catalog: Literal[True]
    require_fields_catalog: Literal[True]
    require_all_cited_queries_complete: Literal[True]


type EvaluationPredicate = Annotated[
    ToolResultPredicate
    | MetricPredicate
    | EvidencePredicate
    | SequencePredicate
    | RecommendationPredicate
    | OracleDirectionPredicate
    | CausalLimitationPredicate
    | CoveragePredicate,
    Field(discriminator="kind"),
]


class EvaluationMetricRule(_EvaluationContract):
    metric_names: tuple[str, ...] = Field(min_length=1, max_length=24)
    minimum_matches: int = Field(strict=True, ge=1, le=24)

    @field_validator("metric_names", mode="before")
    @classmethod
    def freeze_metrics(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class EvaluationOracleDirectionRule(_EvaluationContract):
    oracle_metric: str = Field(min_length=1, max_length=128)
    expected_direction: Direction


class ExplorationEvaluationCriterion(_EvaluationContract):
    criterion_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    pattern_id: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_]{1,63}$"
    )
    max_points: int = Field(strict=True, ge=1, le=14)
    required_tool_names: tuple[EvaluationToolName, ...] = Field(min_length=1, max_length=5)
    required_modes: tuple[SequenceMode, ...] = Field(default_factory=tuple, max_length=3)
    required_source_group_ids: tuple[str, ...] = Field(min_length=1, max_length=8)
    minimum_complete_result_refs: int = Field(strict=True, ge=0, le=48)
    require_scan_complete: Literal[True]
    require_evidence: bool
    require_sequence_or_funnel: bool
    require_recommendation: bool
    metric_rules: tuple[EvaluationMetricRule, ...] = Field(default_factory=tuple, max_length=12)
    oracle_direction_rules: tuple[EvaluationOracleDirectionRule, ...] = Field(
        default_factory=tuple, max_length=12
    )
    structured_predicates: tuple[EvaluationPredicate, ...] = Field(min_length=1, max_length=16)

    @field_validator(
        "required_tool_names",
        "required_modes",
        "required_source_group_ids",
        "metric_rules",
        "oracle_direction_rules",
        "structured_predicates",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def bind_flags_to_predicates(self) -> Self:
        kinds = {predicate.kind for predicate in self.structured_predicates}
        requirements = (
            (self.require_evidence, "evidence"),
            (self.require_sequence_or_funnel, "sequence_or_funnel"),
            (self.require_recommendation, "recommendation"),
        )
        for required, kind in requirements:
            if required and kind not in kinds:
                raise ValueError(f"{kind} requirement needs a structured predicate")
        if "tool_result" not in kinds:
            raise ValueError("every criterion requires a tool_result predicate")
        return self


class RequiredEvaluationPattern(_EvaluationContract):
    pattern_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    criterion_ids: tuple[str, ...] = Field(min_length=1, max_length=12)
    minimum_points: int = Field(strict=True, ge=1, le=14)

    @field_validator("criterion_ids", mode="before")
    @classmethod
    def freeze_criteria(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ExplorationEvaluationRubric(_EvaluationContract):
    rubric_version: Literal["1"] = "1"
    minimum_score: int = Field(strict=True, ge=1)
    maximum_score: int = Field(strict=True, ge=1)
    source_groups: tuple[EvaluationSourceGroup, ...] = Field(min_length=1, max_length=16)
    required_patterns: tuple[RequiredEvaluationPattern, ...] = Field(
        min_length=1, max_length=8
    )
    criteria: tuple[ExplorationEvaluationCriterion, ...] = Field(min_length=1, max_length=32)

    @field_validator("source_groups", "required_patterns", "criteria", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_references_and_scores(self) -> Self:
        if self.minimum_score > self.maximum_score:
            raise ValueError("minimum_score cannot exceed maximum_score")
        if sum(item.max_points for item in self.criteria) != self.maximum_score:
            raise ValueError("maximum_score must equal the sum of criterion max_points")
        source_group_ids = tuple(group.group_id for group in self.source_groups)
        if len(source_group_ids) != len(set(source_group_ids)):
            raise ValueError("source group ids must be unique")
        criterion_ids = tuple(item.criterion_id for item in self.criteria)
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("criterion ids must be unique")
        known_criteria = set(criterion_ids)
        known_groups = set(source_group_ids)
        for criterion in self.criteria:
            if not set(criterion.required_source_group_ids) <= known_groups:
                raise ValueError("required_source_group_ids contains an unknown group")
        pattern_ids = tuple(pattern.pattern_id for pattern in self.required_patterns)
        if len(pattern_ids) != len(set(pattern_ids)):
            raise ValueError("required pattern ids must be unique")
        for pattern in self.required_patterns:
            if not set(pattern.criterion_ids) <= known_criteria:
                raise ValueError("required pattern criterion_ids contain an unknown criterion")
            available = sum(
                item.max_points
                for item in self.criteria
                if item.criterion_id in pattern.criterion_ids
            )
            if pattern.minimum_points > available:
                raise ValueError("required pattern minimum_points exceeds available points")
        return self


__all__ = [
    "ExplorationEvaluationCriterion",
    "ExplorationEvaluationRubric",
    "EvaluationMetricRule",
    "EvaluationOracleDirectionRule",
    "EvaluationPredicate",
    "EvaluationSourceGroup",
    "RequiredEvaluationPattern",
]
