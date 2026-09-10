from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from customer_signal.signals.alert_contracts import (
    RecommendationDraft,
    RuleSelection,
    SelectedRecommendation,
)
from customer_signal.signals.alert_recommendations import build_recommendations
from customer_signal.signals.alerts import AlertStore, RuleConflict
from customer_signal.signals.contracts import Measurement, MetricValue
from customer_signal.signals.measurement import definition_fingerprint
from customer_signal.signals.store import SignalStore
from test_signals import definition

START = datetime(2026, 9, 1, tzinfo=timezone.utc)


def measured(day, value=10, *, status="success", **updates):
    result = Measurement(
        measurement_id=uuid4().hex,
        definition_fingerprint=definition_fingerprint(definition()),
        start_at=START + timedelta(days=day),
        end_at=START + timedelta(days=day + 1),
        snapshot_id=f"snapshot-{day}-{value}",
        status=status,
        source_ids=definition().source_ids,
        values=[
            MetricValue(
                key="affected_customer_count", label="영향 고객 수", value=value, unit="customers"
            )
        ],
    )
    return result.model_copy(update=updates)


@pytest.fixture
def registered(tmp_path):
    store = SignalStore(tmp_path / "signals.sqlite3")
    signal, initial = store.register_definition_with_measurement(
        title="합성 시그널",
        description="테스트",
        definition=definition(),
        measurement=measured(0),
    )
    alerts = AlertStore(store)
    recommendations = build_recommendations(
        signal,
        initial,
        [
            RecommendationDraft(
                metric_key="affected_customer_count",
                kind="value",
                operator="gte",
                threshold=20,
                rationale="영향 고객이 하루 20명 이상이면 확인합니다.",
            )
        ],
        source="fixture",
    )
    alerts.save_recommendations(signal.signal_id, recommendations)
    return store, alerts, signal.signal_id, recommendations.items[0].recommendation_id


def select(registered, *, threshold=None, revision=0):
    _, alerts, sid, rid = registered
    return alerts.replace_rules(
        sid,
        RuleSelection(
            revision=revision,
            items=[SelectedRecommendation(recommendation_id=rid, threshold=threshold)],
        ),
    )


def test_opt_in_boundary_dedup_rearm_and_restart(registered):
    store, alerts, sid, _ = registered
    store.add_measurement(sid, measured(1, 30))
    assert alerts.events(after=0).items == []
    rules = select(registered)
    assert rules.revision == 1
    assert alerts.events(after=0).items == []
    crossing = measured(2, 20)
    store.add_measurement(sid, crossing)
    store.add_measurement(sid, crossing)
    store.add_measurement(sid, measured(3, 30))
    assert len(alerts.events(after=0).items) == 1
    # Failed or missing data never reset a matched condition.
    store.add_measurement(sid, measured(4, None, status="unavailable"))
    store.add_measurement(sid, measured(5, None))
    store.add_measurement(sid, measured(6, 40))
    assert len(alerts.events(after=0).items) == 1
    store.add_measurement(sid, measured(7, 19))
    store.add_measurement(sid, measured(8, 20))
    reopened = AlertStore(SignalStore(store.path))
    events = reopened.events(after=0)
    assert [item.observed_value for item in events.items] == [20, 20]
    assert len({item.event_id for item in events.items}) == 2
    assert reopened.get_rules(sid).items[0].rule_id == rules.items[0].rule_id


def test_rule_replacement_is_idempotent_and_revision_checked(registered):
    store, alerts, sid, rid = registered
    first = select(registered)
    store.add_measurement(sid, measured(1, 30))
    same = select(registered, revision=first.revision)
    assert same == first
    store.add_measurement(sid, measured(2, 30))
    assert len(alerts.events(after=0).items) == 1
    with pytest.raises(RuleConflict):
        select(registered, revision=0)
    changed = select(registered, threshold=40, revision=first.revision)
    assert changed.revision == 2 and changed.items[0].rule_id != first.items[0].rule_id
    store.add_measurement(sid, measured(3, 40))
    assert len(alerts.events(after=0).items) == 2
    cleared = alerts.replace_rules(sid, RuleSelection(revision=2, items=[]))
    store.add_measurement(sid, measured(4, 100))
    assert cleared.items == [] and len(alerts.events(after=0).items) == 2


def test_old_windows_paused_signals_and_wrong_duration_do_not_alert(registered):
    store, alerts, sid, _ = registered
    select(registered)
    store.add_measurement(sid, measured(-1, 100))
    store.add_measurement(sid, measured(0, 100, snapshot_id="correction"))
    store.add_measurement(sid, measured(1, 100, end_at=START + timedelta(days=3)))
    store.set_status(sid, "paused")
    store.add_measurement(sid, measured(3, 100))
    store.set_status(sid, "archived")
    store.add_measurement(sid, measured(4, 100))
    assert alerts.events(after=0).items == []
    store.set_status(sid, "active")
    store.add_measurement(sid, measured(5, 30))
    assert len(alerts.events(after=0).items) == 1
    store.add_measurement(sid, measured(2, 0))
    store.add_measurement(sid, measured(6, 30))
    assert len(alerts.events(after=0).items) == 1


def test_events_bootstrap_pagination_and_concurrent_dedup(registered):
    store, alerts, sid, _ = registered
    select(registered)
    assert alerts.events().next_cursor == 0
    m = measured(1, 30)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: SignalStore(store.path).add_measurement(sid, m), range(8)))
    for day, value in [(2, 0), (3, 30), (4, 0), (5, 30)]:
        store.add_measurement(sid, measured(day, value))
    bootstrap = alerts.events()
    assert bootstrap.items == [] and bootstrap.next_cursor == 3
    first = alerts.events(after=0, limit=2)
    assert len(first.items) == 2 and first.has_more and first.next_cursor == 2
    second = alerts.events(after=first.next_cursor, limit=2)
    assert len(second.items) == 1 and not second.has_more and second.next_cursor == 3
    assert alerts.events(after=3).next_cursor == 3
    assert alerts.events(after=999).next_cursor == 999
    assert all(item.signal_id == sid for item in first.items)


@pytest.mark.parametrize(
    "kind,operator,threshold,baseline,target,expected",
    [
        ("value", "gt", 20, 10, 20, False),
        ("value", "lt", 10, 20, 9, True),
        ("value", "lte", 10, 20, 10, True),
        ("absolute_change", "gte", 5, 10, 15, True),
        ("absolute_change", "lte", -5, 10, 5, True),
        ("relative_change_percent", "gte", 50, 10, 15, True),
        ("relative_change_percent", "gte", 1, 0, 15, False),
    ],
)
def test_condition_types(tmp_path, kind, operator, threshold, baseline, target, expected):
    store = SignalStore(tmp_path / "signals.sqlite3")
    signal, initial = store.register_definition_with_measurement(
        title="합성",
        description="테스트",
        definition=definition(),
        measurement=measured(0, baseline),
    )
    alerts = AlertStore(store)
    recs = build_recommendations(
        signal,
        initial,
        [
            RecommendationDraft(
                metric_key="affected_customer_count",
                kind=kind,
                operator=operator,
                threshold=threshold,
                rationale="테스트용 추천입니다.",
            )
        ],
        source="fixture",
    )
    alerts.save_recommendations(signal.signal_id, recs)
    alerts.replace_rules(
        signal.signal_id,
        RuleSelection(
            revision=0,
            items=[SelectedRecommendation(recommendation_id=recs.items[0].recommendation_id)],
        ),
    )
    store.add_measurement(signal.signal_id, measured(1, target))
    assert bool(alerts.events(after=0).items) is expected


def test_selection_validates_unknown_duplicate_and_invalid_thresholds(registered):
    _, alerts, sid, rid = registered
    with pytest.raises(ValueError):
        alerts.replace_rules(
            sid,
            RuleSelection(revision=0, items=[SelectedRecommendation(recommendation_id="unknown")]),
        )
    with pytest.raises(ValueError):
        select(registered, threshold=-1)
    with pytest.raises(ValidationError):
        RuleSelection(revision=0, items=[SelectedRecommendation(recommendation_id=rid)] * 2)
    for bad in [float("inf"), float("nan"), True, "20"]:
        with pytest.raises(ValidationError):
            SelectedRecommendation(recommendation_id=rid, threshold=bad)


def test_event_failure_rolls_back_measurement_and_state(registered):
    import sqlite3

    store, alerts, sid, _ = registered
    select(registered)
    with store._connection() as db:
        db.execute(
            "CREATE TRIGGER fail_event BEFORE INSERT ON signal_alert_events "
            "BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        store.add_measurement(sid, measured(1, 30))
    assert len(store.list_measurements(sid)) == 1
    assert alerts.events(after=0).items == []
    with store._connection() as db:
        db.execute("DROP TRIGGER fail_event")
    store.add_measurement(sid, measured(1, 30))
    assert len(alerts.events(after=0).items) == 1


def test_failed_day_recovery_and_same_window_correction(registered):
    store, alerts, sid, _ = registered
    select(registered)
    store.add_measurement(sid, measured(1, None, status="unavailable"))
    store.add_measurement(sid, measured(1, 30))
    store.add_measurement(sid, measured(1, 0, snapshot_id="corrected"))
    store.add_measurement(sid, measured(2, 30))
    assert len(alerts.events(after=0).items) == 1


def test_percent_and_custom_metric_changes_have_correct_units(tmp_path):
    from customer_signal.signals.contracts import MetricDefinition

    d = definition(
        metrics=[
            MetricDefinition(key="duration", label="평균 소요", unit="seconds", sql="SELECT 1")
        ]
    )
    store = SignalStore(tmp_path / "signals.sqlite3")

    def values(day, rate, seconds):
        return measured(
            day,
            definition_fingerprint=definition_fingerprint(d),
            values=[
                MetricValue(
                    key="affected_customer_rate", label="영향 비율", value=rate, unit="percent"
                ),
                MetricValue(key="duration", label="평균 소요", value=seconds, unit="seconds"),
            ],
        )

    signal, initial = store.register_definition_with_measurement(
        title="비율과 시간",
        description="합성",
        definition=d,
        measurement=values(0, 10, 10),
    )
    alerts = AlertStore(store)
    recs = build_recommendations(
        signal,
        initial,
        [
            RecommendationDraft(
                metric_key="affected_customer_rate",
                kind="absolute_change",
                operator="gte",
                threshold=5,
                rationale="5%p 증가",
            ),
            RecommendationDraft(
                metric_key="duration",
                kind="value",
                operator="gte",
                threshold=15,
                rationale="15초 이상",
            ),
        ],
        source="fixture",
    )
    assert recs.items[0].comparison_unit == "percentage_points"
    alerts.save_recommendations(signal.signal_id, recs)
    alerts.replace_rules(
        signal.signal_id,
        RuleSelection(
            revision=0,
            items=[
                SelectedRecommendation(recommendation_id=r.recommendation_id) for r in recs.items
            ],
        ),
    )
    store.add_measurement(signal.signal_id, values(1, 15, 15))
    events = alerts.events(after=0).items
    assert {e.rule.metric_key: e.observed_value for e in events} == {
        "affected_customer_rate": 5,
        "duration": 15,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"source_versions": {"app": "changed"}},
        {"pipeline_version": "changed"},
        {"start_at": START + timedelta(hours=12), "end_at": START + timedelta(days=1, hours=12)},
    ],
)
def test_incomparable_changes_do_not_alert(tmp_path, change):
    store = SignalStore(tmp_path / "signals.sqlite3")
    signal, initial = store.register_definition_with_measurement(
        title="비교",
        description="합성",
        definition=definition(),
        measurement=measured(0),
    )
    alerts = AlertStore(store)
    recs = build_recommendations(
        signal,
        initial,
        [
            RecommendationDraft(
                metric_key="affected_customer_count",
                kind="absolute_change",
                operator="gte",
                threshold=1,
                rationale="전일 비교",
            )
        ],
        source="fixture",
    )
    alerts.save_recommendations(signal.signal_id, recs)
    alerts.replace_rules(
        signal.signal_id,
        RuleSelection(
            revision=0,
            items=[SelectedRecommendation(recommendation_id=recs.items[0].recommendation_id)],
        ),
    )
    store.add_measurement(signal.signal_id, measured(1, 100, **change))
    assert alerts.events(after=0).items == []


def test_missing_unrelated_metric_does_not_block_selected_metric(tmp_path):
    store = SignalStore(tmp_path / "signals.sqlite3")
    initial = measured(0)
    initial.values.append(
        MetricValue(key="affected_customer_rate", label="비율", value=None, unit="percent")
    )
    signal, initial = store.register_definition_with_measurement(
        title="독립 지표 평가",
        description="합성",
        definition=definition(),
        measurement=initial,
    )
    alerts = AlertStore(store)
    recs = build_recommendations(
        signal,
        initial,
        [
            RecommendationDraft(
                metric_key="affected_customer_count",
                kind="absolute_change",
                operator="gte",
                threshold=5,
                rationale="5명 증가",
            )
        ],
        source="fixture",
    )
    alerts.save_recommendations(signal.signal_id, recs)
    alerts.replace_rules(
        signal.signal_id,
        RuleSelection(
            revision=0,
            items=[SelectedRecommendation(recommendation_id=recs.items[0].recommendation_id)],
        ),
    )
    current = measured(1, 15)
    current.values.append(
        MetricValue(key="affected_customer_rate", label="비율", value=None, unit="percent")
    )
    store.add_measurement(signal.signal_id, current)
    assert len(alerts.events(after=0).items) == 1


def test_overflowing_relative_change_preserves_measurement_without_event(tmp_path):
    store = SignalStore(tmp_path / "signals.sqlite3")
    signal, initial = store.register_definition_with_measurement(
        title="유한값 비교",
        description="합성",
        definition=definition(),
        measurement=measured(0, 1e-308),
    )
    alerts = AlertStore(store)
    recs = build_recommendations(
        signal,
        initial,
        [
            RecommendationDraft(
                metric_key="affected_customer_count",
                kind="relative_change_percent",
                operator="gte",
                threshold=10,
                rationale="변화 확인",
            )
        ],
        source="fixture",
    )
    alerts.save_recommendations(signal.signal_id, recs)
    alerts.replace_rules(
        signal.signal_id,
        RuleSelection(
            revision=0,
            items=[SelectedRecommendation(recommendation_id=recs.items[0].recommendation_id)],
        ),
    )
    store.add_measurement(signal.signal_id, measured(1, 1e308))
    assert len(store.list_measurements(signal.signal_id)) == 2
    assert alerts.events(after=0).items == []
