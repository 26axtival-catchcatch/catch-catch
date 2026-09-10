from datetime import timedelta

import pytest

from customer_signal.config import Settings
from customer_signal.signals.alert_recommendations import create_recommender
from customer_signal.signals.contracts import MetricValue, Signal
from test_signal_alerts import measured
from test_signals import definition


def context():
    return Signal(
        signal_id="test", title="합성 이탈 고객", description="이탈 증가 탐지",
        definition=definition(),
    ), measured(0)


@pytest.mark.parametrize("mode", ["fixture", "gemini", "bedrock"])
def test_reuses_measured_metrics_without_initializing_a_provider(mode):
    signal, measurement = context()
    measurement.end_at = measurement.start_at + timedelta(days=7)
    measurement.values[0].value = 70
    measurement.values.extend([
        MetricValue(key="affected_customer_rate", label="대상 고객 비율", value=35, unit="percent"),
        MetricValue(key="average_steps", label="평균 탐색 횟수", value=2.5, unit="events"),
        MetricValue(key="denominator_customer_count", label="전체 고객 수", value=200, unit="customers"),
        MetricValue(key="val_count", label="확인용", value=200, unit="records"),
        MetricValue(key="unavailable", label="측정 불가", value=None, unit="events"),
    ])
    recommend = create_recommender(
        Settings(agent_mode=mode, _env_file=None),
        model_factory=lambda **_: pytest.fail("must not initialize an external provider"),
    )
    result = recommend(signal, measurement)
    assert result.status == "ready" and result.source == "measurement"
    visible = measurement.values[:4]
    assert [(r.metric_key, r.metric_label, r.metric_unit, r.threshold) for r in result.items] == [
        (m.key, m.label, m.unit, m.value) for m in visible
    ]
    assert all(r.kind == "value" and r.operator == "gte" for r in result.items)
    assert all(r.comparison_unit == r.metric_unit for r in result.items)
    assert all(r.window_seconds == 86400 for r in result.items)
    assert [r.recommendation_id for r in recommend(signal, measurement).items] == [
        r.recommendation_id for r in result.items
    ]


def test_no_measured_metrics_returns_explanation_without_inventing_conditions():
    signal, measurement = context()
    measurement.values[0].value = None
    result = create_recommender(Settings(agent_mode="bedrock", _env_file=None))(signal, measurement)
    assert result.status == "unavailable" and result.source == "measurement"
    assert result.items == [] and result.reason
