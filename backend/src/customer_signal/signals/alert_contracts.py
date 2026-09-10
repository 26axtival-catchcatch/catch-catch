"""Public contracts for opt-in daily signal alerts."""

from datetime import datetime, timezone
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat, model_validator

Number = Annotated[FiniteFloat, Field(strict=True)]


class AlertContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RecommendationDraft(AlertContract):
    metric_key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    kind: Literal["value", "absolute_change", "relative_change_percent"]
    operator: Literal["gt", "gte", "lt", "lte"]
    threshold: Number
    rationale: str = Field(min_length=1, max_length=1000)


class Recommendation(RecommendationDraft):
    recommendation_id: str
    metric_label: str
    metric_unit: str
    comparison_unit: str
    window_seconds: Literal[86400] = 86400


class RecommendationSet(AlertContract):
    status: Literal["ready", "unavailable"]
    source: Literal["measurement", "model", "fixture"]
    items: list[Recommendation] = Field(default_factory=list, max_length=20)
    reason: str | None = None
    generated_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SelectedRecommendation(AlertContract):
    recommendation_id: str = Field(min_length=1, max_length=80)
    threshold: Number | None = None


class RuleSelection(AlertContract):
    revision: int = Field(ge=0, strict=True)
    items: list[SelectedRecommendation] = Field(max_length=20)

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        ids = [item.recommendation_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("recommendation_id must be unique")
        return self


class AlertRule(Recommendation):
    rule_id: str


class AlertRules(AlertContract):
    signal_id: str
    revision: int = 0
    items: list[AlertRule] = Field(default_factory=list)


class AlertEvent(AlertContract):
    sequence: int
    event_id: str
    event_type: Literal["threshold_crossed"] = "threshold_crossed"
    signal_id: str
    signal_title: str
    rule: AlertRule
    measurement_id: str
    baseline_measurement_id: str | None = None
    observed_value: Number
    metric_value: Number
    baseline_value: Number | None = None
    start_at: AwareDatetime
    end_at: AwareDatetime
    occurred_at: AwareDatetime


class AlertEvents(AlertContract):
    items: list[AlertEvent]
    next_cursor: int
    latest_cursor: int
    has_more: bool
