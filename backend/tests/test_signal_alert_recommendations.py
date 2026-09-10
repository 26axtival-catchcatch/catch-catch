import json

import pytest

from customer_signal.config import Settings
from customer_signal.signals.alert_recommendations import create_recommender
from customer_signal.signals.contracts import Signal
from test_signal_alerts import measured
from test_signals import definition


def context():
    return Signal(
        signal_id="test",
        title="합성 이탈 고객",
        description="이탈 증가 탐지",
        definition=definition(),
    ), measured(0)


@pytest.mark.parametrize("mode", ["gemini", "bedrock"])
def test_model_recommends_typed_conditions_from_public_aggregates(mode):
    calls = []

    class FakeModel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def with_structured_output(self, schema, **kwargs):
            return self

        def invoke(self, messages, config):
            calls.append((messages, config))
            return {
                "document": json.dumps(
                    {
                        "items": [
                            {
                                "metric_key": "affected_customer_count",
                                "kind": "relative_change_percent",
                                "operator": "gte",
                                "threshold": 35,
                                "rationale": "전일보다 35% 늘면 확인합니다.",
                            }
                        ]
                    }
                )
            }

    recommend = create_recommender(
        Settings(agent_mode=mode, _env_file=None), model_factory=FakeModel
    )
    signal, measurement = context()
    measurement.cohort_customer_ids = ["private-customer"]
    measurement.query_results = [{"secret": "raw result"}]
    result = recommend(signal, measurement)
    assert result.source == "model" and result.status == "ready"
    assert result.items[0].threshold == 35 and result.items[0].window_seconds == 86400
    assert result.items[0].comparison_unit == "percent"
    messages, config = calls[0]
    assert "private-customer" not in str(messages) and "raw result" not in str(messages)
    assert "cohort_sql" not in str(messages)
    assert config["run_name"] == "customer_signal.alert_recommendation"
    assert config["metadata"]["stage"] == "alert_recommendation"
    assert {"customer-signal", mode, "alert_recommendation"} <= set(config["tags"])


@pytest.mark.parametrize("failure", ["exception", "malformed", "unknown_metric", "empty"])
def test_model_failures_return_safe_unavailable_without_fixed_fallback(failure):
    class FakeModel:
        def __init__(self, **kwargs):
            pass

        def with_structured_output(self, *args, **kwargs):
            return self

        def invoke(self, *args, **kwargs):
            if failure == "exception":
                raise RuntimeError("private-api-key=never-expose")
            if failure == "malformed":
                return {"document": "raw-private-invalid"}
            return {
                "document": json.dumps(
                    {
                        "items": []
                        if failure == "empty"
                        else [
                            {
                                "metric_key": "invented",
                                "kind": "value",
                                "operator": "gte",
                                "threshold": 1,
                                "rationale": "unknown",
                            }
                        ]
                    }
                )
            }

    result = create_recommender(
        Settings(agent_mode="bedrock", _env_file=None), model_factory=FakeModel
    )(*context())
    assert result.status == "unavailable" and result.source == "model" and result.items == []
    assert "private" not in result.model_dump_json()


def test_fixture_does_not_call_provider_and_normalizes_weekly_counts():
    signal, measurement = context()
    measurement.end_at = measurement.start_at + __import__("datetime").timedelta(days=7)
    measurement.values[0].value = 70
    recommend = create_recommender(
        Settings(agent_mode="fixture", _env_file=None),
        model_factory=lambda **_: pytest.fail("external provider"),
    )
    result = recommend(signal, measurement)
    assert result.source == "fixture" and result.status == "ready"
    assert result.items[0].threshold == 13
