"""Alert criteria reuse the metrics already measured for each signal."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid4, uuid5

from customer_signal.signals.alert_contracts import (
    Recommendation,
    RecommendationDraft,
    RecommendationSet,
)
from customer_signal.signals.alerts import validate_threshold


def build_recommendations(signal, measurement, drafts: list[RecommendationDraft], *, source):
    metrics = {m.key: m for m in measurement.values if m.value is not None}
    if not 1 <= len(drafts) <= 20:
        raise ValueError("recommend between 1 and 20 conditions")
    items, seen = [], set()
    for draft in drafts:
        if draft.metric_key not in metrics:
            raise ValueError("recommendations must reference measured metrics")
        metric = metrics[draft.metric_key]
        signature = (draft.metric_key, draft.kind, draft.operator, draft.threshold)
        if signature in seen:
            raise ValueError("duplicate recommendation")
        seen.add(signature)
        unit = metric.unit
        if draft.kind == "relative_change_percent":
            unit = "percent"
        elif draft.kind == "absolute_change" and metric.unit in {"percent", "%"}:
            unit = "percentage_points"
        result = Recommendation(
            **draft.model_dump(),
            recommendation_id=uuid4().hex,
            metric_label=metric.label,
            metric_unit=metric.unit,
            comparison_unit=unit,
        )
        validate_threshold(result)
        items.append(result)
    return RecommendationSet(status="ready", source=source, items=items)


def measurement_recommendations(signal, measurement) -> RecommendationSet:
    """One editable value threshold per visible metric; never calls a model."""
    drafts = [
        RecommendationDraft(
            metric_key=metric.key,
            kind="value",
            operator="gte",
            threshold=metric.value,
            rationale="매일 측정한 값이 설정한 값 이상이면 알려드려요.",
        )
        for metric in measurement.values
        if metric.value is not None and metric.key != "val_count" and "확인용" not in metric.label
    ]
    if measurement.status != "success" or not drafts:
        return RecommendationSet(
            status="unavailable", source="measurement",
            reason="알림을 설정할 수 있는 측정 지표가 아직 없습니다.",
        )
    result = build_recommendations(signal, measurement, drafts, source="measurement")
    for item in result.items:
        item.recommendation_id = uuid5(
            NAMESPACE_URL, f"signal-alert:{signal.signal_id}:{item.metric_key}:value:gte"
        ).hex
    return result


def fixture_recommendations(signal, measurement) -> RecommendationSet:
    """Compatibility entry point: fixture and live modes reuse the same measurements."""
    return measurement_recommendations(signal, measurement)


def create_recommender(settings, *, model_factory=None):
    """Keep the existing wiring API without initializing any provider."""
    return measurement_recommendations
