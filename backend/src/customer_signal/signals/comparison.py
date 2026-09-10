"""Comparable periods and typed metric deltas without rerunning or redefining a signal."""

from pydantic import FiniteFloat

from customer_signal.signals.contracts import Contract, Measurement


class MetricChange(Contract):
    key: str
    label: str
    unit: str
    baseline_value: int | FiniteFloat
    target_value: int | FiniteFloat
    absolute_change: int | FiniteFloat
    change_unit: str
    relative_change_percent: FiniteFloat | None


class MeasurementComparison(Contract):
    baseline: Measurement | None = None
    target: Measurement | None = None
    comparable: bool
    comparison_limitations: list[str]
    metrics: list[MetricChange]


def comparison_limitations(windows: list[Measurement]) -> list[str]:
    reasons = []
    if len(windows) < 2:
        reasons.append("비교할 관측 기간이 두 개 이상 필요합니다.")
    if any(m.status != "success" for m in windows):
        reasons.append("측정 불가 기간이 포함되어 있습니다. 0건으로 해석하지 마세요.")
    if len({(m.end_at - m.start_at).total_seconds() for m in windows}) > 1:
        reasons.append("관측 기간의 길이가 다릅니다.")
    if len({m.definition_fingerprint for m in windows}) > 1:
        reasons.append("지표 정의가 다릅니다.")
    if len({m.pipeline_version for m in windows}) > 1:
        reasons.append("측정 파이프라인 버전이 다릅니다.")
    if len({tuple(sorted(m.source_ids)) for m in windows}) > 1:
        reasons.append("측정 Source 범위가 다릅니다.")
    if len({tuple(sorted(m.source_versions.items())) for m in windows}) > 1:
        reasons.append("Source 매핑 또는 스키마 버전이 다릅니다.")
    if any(a.end_at > b.start_at for a, b in zip(windows, windows[1:])):
        reasons.append("관측 기간이 겹치거나 기준 기간보다 비교 기간이 앞섭니다.")
    return reasons


def compare_measurements(baseline, target) -> MeasurementComparison:
    windows = [m for m in (baseline, target) if m is not None]
    reasons = comparison_limitations(windows)
    changes = []
    if not reasons:
        previous = {v.key: v for v in baseline.values}
        current = {v.key: v for v in target.values}
        if previous.keys() != current.keys() or any(
            previous[k].unit != current[k].unit
            or previous[k].value is None
            or current[k].value is None
            for k in previous
        ):
            reasons.append("지표 구성 또는 단위가 다르거나 값이 없습니다.")
        else:
            for key, before in previous.items():
                after = current[key]
                delta = after.value - before.value
                changes.append(
                    MetricChange(
                        key=key,
                        label=after.label,
                        unit=after.unit,
                        baseline_value=before.value,
                        target_value=after.value,
                        absolute_change=delta,
                        change_unit="percentage_points"
                        if after.unit in {"percent", "%"}
                        else after.unit,
                        relative_change_percent=delta / abs(before.value) * 100
                        if before.value
                        else None,
                    )
                )
    return MeasurementComparison(
        baseline=baseline,
        target=target,
        comparable=not reasons,
        comparison_limitations=reasons,
        metrics=changes,
    )
