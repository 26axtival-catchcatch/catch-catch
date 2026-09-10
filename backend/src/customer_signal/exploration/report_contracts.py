"""Strict public contracts for completed and degraded exploration reports."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator, model_validator

from customer_signal.exploration.contracts import QueryRef, ResultRef, ToolError
from customer_signal.exploration.ledger import ExplorationLedgerSnapshot


class _ReportContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must be nonblank")
    return value


def _unique(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must be unique")
    return values


class ExplorationMetric(_ReportContract):
    name: str = Field(min_length=1, max_length=256)
    value: FiniteFloat | int | None
    unit: str = Field(min_length=1, max_length=64)
    result_ref: ResultRef

    @field_validator("name", "unit")
    @classmethod
    def validate_nonblank(cls, value: str) -> str:
        return _nonblank(value)


class Recommendation(_ReportContract):
    action: str = Field(min_length=1, max_length=2_000)
    expected_direction: Literal["increase", "decrease", "unchanged"]
    target_metric: str = Field(min_length=1, max_length=256)

    @field_validator("action", "target_metric")
    @classmethod
    def validate_nonblank(cls, value: str) -> str:
        return _nonblank(value)


class Finding(_ReportContract):
    finding_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$"
    )
    title: str = Field(min_length=1, max_length=500)
    observation: str = Field(min_length=1, max_length=4_000)
    hypothesis: str = Field(min_length=1, max_length=4_000)
    confidence: Literal["low", "medium", "high"]
    source_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    query_refs: tuple[QueryRef, ...] = Field(min_length=1, max_length=48)
    result_refs: tuple[ResultRef, ...] = Field(min_length=1, max_length=48)
    evidence_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=48)
    metrics: tuple[ExplorationMetric, ...] = Field(min_length=1, max_length=24)
    recommendations: tuple[Recommendation, ...] = Field(min_length=1, max_length=12)
    limitations: tuple[str, ...] = Field(default_factory=tuple, max_length=24)

    @field_validator(
        "source_ids",
        "query_refs",
        "result_refs",
        "evidence_ids",
        "metrics",
        "recommendations",
        "limitations",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("title", "observation", "hypothesis")
    @classmethod
    def validate_nonblank(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("source_ids", "query_refs", "result_refs", "evidence_ids")
    @classmethod
    def validate_unique_refs(cls, value: tuple[str, ...], info: object) -> tuple[str, ...]:
        field_name = getattr(info, "field_name", "references")
        return _unique(value, field_name)

    @field_validator("limitations")
    @classmethod
    def validate_limitations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for limitation in value:
            _nonblank(limitation)
        return value

    @model_validator(mode="after")
    def separate_observation_and_hypothesis(self) -> Self:
        def normalize(value: str) -> str:
            return " ".join(value.casefold().split())

        if normalize(self.observation) == normalize(self.hypothesis):
            raise ValueError("observation and hypothesis must be structurally separate")
        if not {metric.result_ref for metric in self.metrics} <= set(self.result_refs):
            raise ValueError("every metric result_ref must be present in result_refs")
        return self


class AbandonedBranch(_ReportContract):
    query_ref: QueryRef
    last_page_index: int = Field(strict=True, ge=0)
    has_more: bool
    reason: str = Field(min_length=1, max_length=1_000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _nonblank(value)


class ExplorationCoverage(_ReportContract):
    completed_query_refs: tuple[QueryRef, ...] = Field(default_factory=tuple, max_length=48)
    abandoned_branches: tuple[AbandonedBranch, ...] = Field(default_factory=tuple, max_length=48)

    @field_validator("completed_query_refs", "abandoned_branches", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("completed_query_refs")
    @classmethod
    def unique_completed(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _unique(value, "completed_query_refs")

    @model_validator(mode="after")
    def unique_and_disjoint_branches(self) -> Self:
        abandoned = tuple(branch.query_ref for branch in self.abandoned_branches)
        _unique(abandoned, "abandoned_branches.query_ref")
        overlap = set(self.completed_query_refs) & set(abandoned)
        if overlap:
            raise ValueError("completed and abandoned query references must be disjoint")
        return self


class _ExplorationReportBase(_ReportContract):
    report_version: Literal["1"] = "1"
    executive_summary: str = Field(min_length=1, max_length=4_000)
    coverage: ExplorationCoverage
    causal_limitations: tuple[str, ...] = Field(min_length=1, max_length=24)

    @field_validator("causal_limitations", mode="before")
    @classmethod
    def freeze_causal_limitations(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("executive_summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("causal_limitations")
    @classmethod
    def validate_causal_limitations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for limitation in value:
            _nonblank(limitation)
        return value


class ExplorationReport(_ExplorationReportBase):
    findings: tuple[Finding, ...] = Field(min_length=1, max_length=12)

    @field_validator("findings", mode="before")
    @classmethod
    def freeze_findings(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("findings")
    @classmethod
    def unique_findings(cls, value: tuple[Finding, ...]) -> tuple[Finding, ...]:
        _unique(tuple(finding.finding_id for finding in value), "finding_id")
        return value


class ExplorationPartialReport(_ExplorationReportBase):
    """Degraded outcome; it cannot be promoted to a completed report."""

    findings: tuple[Finding, ...] = Field(default_factory=tuple, max_length=12)

    @field_validator("findings", mode="before")
    @classmethod
    def freeze_findings(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def require_open_branch(self) -> Self:
        if not self.coverage.abandoned_branches:
            raise ValueError("partial report requires at least one open abandoned branch")
        _unique(tuple(finding.finding_id for finding in self.findings), "finding_id")
        return self


class ExplorationReportSubmission(_ReportContract):
    """Public terminal Tool response; validation errors remain non-terminal."""

    status: Literal["success", "error"]
    terminal: bool
    report: ExplorationReport | None = None
    ledger_snapshot: ExplorationLedgerSnapshot | None = None
    error: ToolError | None = None

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.status == "success":
            if (
                not self.terminal
                or self.report is None
                or self.ledger_snapshot is None
                or self.error is not None
            ):
                raise ValueError(
                    "successful submission requires terminal report and ledger snapshot"
                )
        elif (
            self.terminal
            or self.report is not None
            or self.ledger_snapshot is not None
            or self.error is None
        ):
            raise ValueError("failed submission requires only a non-terminal error")
        return self


__all__ = [
    "AbandonedBranch",
    "ExplorationCoverage",
    "ExplorationMetric",
    "ExplorationPartialReport",
    "ExplorationReport",
    "ExplorationReportSubmission",
    "Finding",
    "Recommendation",
]
