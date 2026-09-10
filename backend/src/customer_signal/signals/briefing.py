"""Read-only card projection for the B1 briefing deck."""

from typing import Literal

from pydantic import AwareDatetime, Field

from customer_signal.domain.types import SourceId
from customer_signal.signals.comparison import (
    MetricChange,
    compare_measurements,
    comparison_limitations,
)
from customer_signal.signals.contracts import (
    Contract,
    Measurement,
    MetricValue,
    Signal,
    SignalStatus,
    now,
)


def recent_windows(items: list[Measurement]) -> list[Measurement]:
    """Keep the latest success per window, then the seven most recent windows."""
    latest: dict[tuple, Measurement] = {}
    for item in sorted(items, key=lambda m: m.measured_at):
        key = (item.start_at, item.end_at)
        previous = latest.get(key)
        if previous is None or item.status == "success" or previous.status != "success":
            latest[key] = item
    return sorted(latest.values(), key=lambda m: (m.end_at, m.start_at))[-7:]


class BriefingMeasurement(Contract):
    measurement_id: str
    start_at: AwareDatetime
    end_at: AwareDatetime
    measured_at: AwareDatetime
    status: Literal["success", "unavailable"]
    reason: str | None
    values: list[MetricValue]


class BriefingComparison(Contract):
    baseline_measurement_id: str | None
    target_measurement_id: str | None
    comparable: bool
    comparison_limitations: list[str]
    metrics: list[MetricChange]


class BriefingTrend(Contract):
    comparable: bool
    comparison_limitations: list[str]
    points: list[BriefingMeasurement]


class BriefingSignal(Contract):
    signal_id: str
    title: str
    description: str
    status: SignalStatus
    origin: Literal["analysis", "user_defined"]
    created_at: AwareDatetime
    source_ids: list[SourceId]
    population_description: str
    latest_measurement: BriefingMeasurement | None
    comparison: BriefingComparison
    trend: BriefingTrend


class SignalBriefingList(Contract):
    generated_at: AwareDatetime = Field(default_factory=now)
    items: list[BriefingSignal]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    next_offset: int | None = Field(default=None, ge=0)


def briefing_card(signal: Signal, measurements: list[Measurement]) -> BriefingSignal:
    windows = recent_windows(measurements)
    target = windows[-1] if windows else None
    baseline = windows[-2] if len(windows) > 1 else None
    comparison = compare_measurements(baseline, target)
    trend_reasons = comparison_limitations(windows)
    for before, after in zip(windows, windows[1:]):
        trend_reasons.extend(compare_measurements(before, after).comparison_limitations)
    trend_reasons = list(dict.fromkeys(trend_reasons))
    # Explicit public projection: no SQL, raw query results or customer identifiers.
    points = [
        BriefingMeasurement(**{name: getattr(m, name) for name in BriefingMeasurement.model_fields})
        for m in windows
    ]
    return BriefingSignal(
        signal_id=signal.signal_id,
        title=signal.title,
        description=signal.description,
        status=signal.status,
        origin=signal.origin,
        created_at=signal.created_at,
        source_ids=signal.definition.source_ids,
        population_description=signal.definition.population_description,
        latest_measurement=points[-1] if points else None,
        comparison=BriefingComparison(
            baseline_measurement_id=baseline.measurement_id if baseline else None,
            target_measurement_id=target.measurement_id if target else None,
            comparable=comparison.comparable,
            comparison_limitations=comparison.comparison_limitations,
            metrics=comparison.metrics,
        ),
        trend=BriefingTrend(
            comparable=not trend_reasons,
            comparison_limitations=trend_reasons,
            points=points,
        ),
    )
