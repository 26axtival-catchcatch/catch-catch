"""Persistent signal definitions and server-computed measurement contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from customer_signal.domain.types import SourceId

SignalStatus = Literal["active", "paused", "archived"]
_RESERVED = {"affected_customer_count", "denominator_customer_count", "affected_customer_rate"}


def now() -> datetime:
    return datetime.now(timezone.utc)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetricDefinition(Contract):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1)
    sql: str = Field(min_length=1)
    unit: str = Field(min_length=1)


class SignalDefinition(Contract):
    source_ids: list[SourceId] = Field(min_length=1, max_length=32)
    cohort_sql: str = Field(min_length=1)
    denominator_sql: str | None = None
    population_description: str = Field(min_length=1)
    normal_comparison: str = Field(min_length=1)
    metrics: list[MetricDefinition] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_keys(self) -> Self:
        keys = [m.key for m in self.metrics]
        if len(keys) != len(set(keys)) or set(keys) & _RESERVED:
            raise ValueError("metric keys must be unique and cannot replace built-in metrics")
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("source_ids must be unique")
        return self


class MetricValue(Contract):
    key: str
    label: str
    value: int | FiniteFloat | None
    unit: str
    numerator: int | FiniteFloat | None = None
    denominator: int | FiniteFloat | None = None


class Measurement(Contract):
    measurement_id: str
    definition_fingerprint: str
    start_at: AwareDatetime
    end_at: AwareDatetime
    measured_at: AwareDatetime = Field(default_factory=now)
    snapshot_id: str
    trace_id: str | None = None
    status: Literal["success", "unavailable"]
    reason: str | None = None
    values: list[MetricValue] = Field(default_factory=list)
    queries: list[dict] = Field(default_factory=list)
    source_ids: list[SourceId]
    source_versions: dict[str, str] = Field(default_factory=dict)
    cohort_customer_ids: list[str] = Field(default_factory=list, exclude=True)
    query_results: list[dict] = Field(default_factory=list, exclude=True)

    @model_validator(mode="after")
    def valid_window(self) -> Self:
        if self.start_at >= self.end_at:
            raise ValueError("measurement window must be increasing")
        self.start_at = self.start_at.astimezone(timezone.utc)
        self.end_at = self.end_at.astimezone(timezone.utc)
        return self


class Proposal(Contract):
    proposal_id: str
    run_id: str
    candidate_id: str
    task_id: str | None = None
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    definition: SignalDefinition
    measurement: Measurement
    created_at: AwareDatetime = Field(default_factory=now)
    limitations: list[str] = Field(default_factory=list)


class Signal(Contract):
    signal_id: str
    title: str
    description: str
    status: SignalStatus = "active"
    definition_version: int = 1
    definition: SignalDefinition
    created_at: AwareDatetime = Field(default_factory=now)
    proposal_id: str | None = None
    origin: Literal["analysis", "user_defined"] = "analysis"
