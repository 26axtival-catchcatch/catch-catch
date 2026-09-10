"""Next-day analysis must produce real measurements and the existing polling events."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from customer_signal.agent.contracts import RunRequest
from customer_signal.domain.models import CustomerEvent
from customer_signal.investigation.data import InvestigationData
from customer_signal.signals.alert_contracts import RecommendationDraft
from customer_signal.signals.alert_recommendations import build_recommendations
from customer_signal.signals.api import create_router
from customer_signal.signals.contracts import Proposal, SignalDefinition
from customer_signal.signals.measurement import measure_definition
from customer_signal.signals.scheduling import DailyScheduler, ScheduleStore
from customer_signal.signals.service import SignalService
from customer_signal.signals.store import SignalStore

DAY = timedelta(days=1)
END = datetime(2026, 9, 5, 15, tzinfo=timezone.utc)  # September 6 KST
PATH = "/api/signals/fast-forward"


@pytest.fixture
def demo(tmp_path):
    store = SignalStore(tmp_path / "signals.sqlite3")
    definition = SignalDefinition(
        source_ids=["app"],
        cohort_sql="SELECT DISTINCT customer_id FROM events WHERE action='repeat'",
        denominator_sql="SELECT DISTINCT customer_id FROM events",
        population_description="앱 이용 고객",
        normal_comparison="반복하지 않은 고객",
    )
    events = []
    for day in range(-7, 4):
        affected = {-1: 1, 0: 4, 1: 4, 2: 1, 3: 5}.get(day, 1)
        for i in range(10):
            events.append(CustomerEvent(
                event_id=f"event-{day}-{i}", evidence_id=f"evidence-{day}-{i}",
                source_id="app", occurred_at=END + day * DAY + timedelta(hours=1),
                event_type="search", action="repeat" if i < affected else "done",
                topic="settings", outcome="unknown", text="", canonical_customer_id=f"c-{i}",
            ))
    loads = []

    def load(request):
        loads.append((request.start_at, request.end_at))
        return InvestigationData(
            request=request,
            events=[e for e in events if request.start_at <= e.occurred_at < request.end_at],
            manifests=[], snapshot_id="test-source",
        )

    def recommend(signal, measurement):
        return build_recommendations(signal, measurement, [RecommendationDraft(
            metric_key="affected_customer_count", kind="absolute_change", operator="gte",
            threshold=2, rationale="직전 하루보다 대상 고객이 2명 이상 증가하면 확인합니다.",
        )], source="fixture")

    initial_data = load(RunRequest(
        question="반복 검색 고객", start_at=END - 7 * DAY, end_at=END, enabled_sources=["app"],
    ))
    try:
        initial = measure_definition(initial_data, definition)
    finally:
        initial_data.close()
    proposal = Proposal(
        proposal_id=str(uuid4()), run_id=str(uuid4()), candidate_id="repeat",
        title="반복 검색 고객", description="첫 질의에서 검증한 패턴",
        definition=definition, measurement=initial,
    )
    store.save_proposal(proposal)

    def client_for(current_store):
        app = FastAPI()
        app.include_router(create_router(
            store=current_store, is_completed=lambda _: True, load_data=load, recommend=recommend,
        ))
        return TestClient(app, raise_server_exceptions=False)

    client = client_for(store)
    signal = client.post("/api/signals", json={"proposal_id": proposal.proposal_id}).json()
    sid = signal["signal_id"]
    response = client.put(f"/api/signals/{sid}/alert-rules", json={
        "revision": 0,
        "items": [{"recommendation_id": signal["alert_recommendations"]["items"][0]["recommendation_id"]}],
    })
    assert response.status_code == 200
    loads.clear()
    yield client, store, sid, load, loads, events, client_for
    client.close()


def forward(client, **overrides):
    body = {"request_id": str(uuid4()), **overrides}
    return client.post(PATH, json=body), body


def test_first_weekly_query_next_day_real_analysis_and_polling(demo):
    client, store, sid, _, loads, _, _ = demo
    cursor = client.get("/api/signal-alert-events").json()["next_cursor"]
    response, _ = forward(client)
    assert response.status_code == 200, response.text
    result = response.json()
    item = result["items"][0]
    assert item["signal_id"] == sid
    assert item["status"] == "completed"
    assert item["baseline_measurement"]["start_at"] == (END - DAY).isoformat().replace("+00:00", "Z")
    assert item["baseline_measurement"]["values"][0]["value"] == 1
    day = item["daily_results"][0]
    assert day["start_at"] == END.isoformat().replace("+00:00", "Z")
    assert day["end_at"] == (END + DAY).isoformat().replace("+00:00", "Z")
    assert day["measurement"]["values"][0]["value"] == 4
    assert day["measurement"]["pipeline_version"] == "signal-sql-v1"
    assert loads == [(END - DAY, END), (END, END + DAY)]
    page = client.get("/api/signal-alert-events", params={"after": cursor}).json()
    assert len(page["items"]) == 1
    event = page["items"][0]
    assert event["observed_value"] == 3
    assert event["measurement_id"] == day["measurement"]["measurement_id"]
    assert event["baseline_measurement_id"] == item["baseline_measurement"]["measurement_id"]
    assert item["alert_events"] == [event]
    assert len(store.list_measurements(sid)) == 3
    assert client.get(f"/api/signals/{sid}/daily-results").json()["items"] == [day]
    briefing = client.get("/api/signals/briefing").json()
    assert day["measurement"]["measurement_id"] in str(briefing)
    assert "cohort_customer_ids" not in response.text
    assert "query_results" not in response.text


def test_multiple_days_in_order_and_new_request_continues(demo):
    client, store, sid, _, loads, _, _ = demo
    response, _ = forward(client, days=3)
    assert response.status_code == 200, response.text
    days = response.json()["items"][0]["daily_results"]
    assert [d["measurement"]["values"][0]["value"] for d in days] == [4, 4, 1]
    assert len(client.get("/api/signal-alert-events?after=0").json()["items"]) == 1
    response, _ = forward(client)
    assert response.status_code == 200
    day = response.json()["items"][0]["daily_results"][0]
    assert day["end_at"] == (END + 4 * DAY).isoformat().replace("+00:00", "Z")
    assert day["measurement"]["values"][0]["value"] == 5
    assert len(client.get("/api/signal-alert-events?after=0").json()["items"]) == 2
    assert len(loads) == 5  # one baseline, four new days


def test_retry_after_restart_returns_same_response_without_advancing(demo):
    client, store, sid, _, loads, _, client_for = demo
    first, body = forward(client)
    assert first.status_code == 200, first.text
    count = len(store.list_measurements(sid))
    loads.clear()
    with client_for(SignalStore(store.path)) as reopened:
        retry = reopened.post(PATH, json=body)
        assert retry.json() == first.json()
        assert not loads
        assert len(store.list_measurements(sid)) == count
        assert reopened.post(PATH, json={**body, "days": 2}).status_code == 409


@pytest.mark.parametrize("updates", [
    {"days": 0}, {"days": 8}, {"days": True}, {"days": "1"}, {"days": 1.5},
    {"signal_ids": []}, {"signal_ids": ["x", "x"]}, {"request_id": "bad"},
    {"unexpected": True},
])
def test_request_validation(demo, updates):
    assert forward(demo[0], **updates)[0].status_code == 422


def test_request_id_is_required(demo):
    assert demo[0].post(PATH, json={}).status_code == 422


@pytest.mark.parametrize("status", ["paused", "archived", "disabled"])
def test_inactive_or_disabled_signals_are_skipped(demo, status):
    client, store, sid, _, loads, _, _ = demo
    if status == "disabled":
        ScheduleStore(store).update(sid, enabled=False)
    else:
        store.set_status(sid, status)
    response, _ = forward(client)
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["status"] == "skipped" and item["reason"]
    assert not item["daily_results"] and not item["alert_events"] and not loads


def test_unknown_signal_and_busy_do_not_partially_execute(demo):
    client, store, sid, _, loads, _, _ = demo
    assert forward(client, signal_ids=[sid, "missing"])[0].status_code == 404
    with ScheduleStore(store).lock(sid):
        assert forward(client)[0].status_code == 409
    assert not loads and len(store.list_measurements(sid)) == 1


def test_empty_future_data_is_unavailable_without_fake_alert(demo):
    client, _, _, _, _, events, _ = demo
    events[:] = [e for e in events if e.occurred_at < END]
    response, _ = forward(client)
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["daily_results"][0]["measurement"]["status"] == "unavailable"
    assert not item["alert_events"]
    assert not client.get("/api/signal-alert-events?after=0").json()["items"]


def test_fast_forward_does_not_rewind_normal_schedule_and_worker_deduplicates(demo):
    client, store, sid, load, _, _, _ = demo
    schedules = ScheduleStore(store)
    later = END + 20 * DAY
    schedules.update(sid, enabled=True, next_run_at=later)
    response, _ = forward(client)
    assert response.status_code == 200, response.text
    assert schedules.get(sid).next_run_at == later
    schedules.update(sid, enabled=True, next_run_at=END)
    response, _ = forward(client)
    assert response.status_code == 200
    assert schedules.get(sid).next_run_at == END + 3 * DAY
    worker = DailyScheduler(schedules, SignalService(store=store, load_data=load))
    assert worker.tick(END + 2 * DAY) == 0


def test_openapi_exposes_typed_korean_fast_forward_contract(demo):
    schema = demo[0].get("/openapi.json").json()
    assert PATH in schema["paths"]
    operation = schema["paths"][PATH]["post"]
    assert operation["tags"] == ["signals"]
    assert "빨리감기" in operation["summary"]
    assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]


def test_restart_recovers_reserved_dates_after_measurement_commit(demo, monkeypatch):
    client, store, sid, _, _, _, client_for = demo
    original_finish = ScheduleStore.finish

    def crash(*args, **kwargs):
        raise RuntimeError("simulated process termination")

    monkeypatch.setattr(ScheduleStore, "finish", crash)
    response, body = forward(client, days=2)
    assert response.status_code == 500
    before = store.list_measurements(sid)
    assert len(before) == 3  # weekly, baseline, committed first day
    assert len(client.get("/api/signal-alert-events?after=0").json()["items"]) == 1
    monkeypatch.setattr(ScheduleStore, "finish", original_finish)
    with client_for(SignalStore(store.path)) as reopened:
        recovered = reopened.post(PATH, json=body)
        assert recovered.status_code == 200, recovered.text
        days = recovered.json()["items"][0]["daily_results"]
        assert [d["end_at"] for d in days] == [
            (END + n * DAY).isoformat().replace("+00:00", "Z") for n in [1, 2]
        ]
        assert days[0]["measurement"]["measurement_id"] == before[-1].measurement_id
        assert len(store.list_measurements(sid)) == 4
        assert len(reopened.get("/api/signal-alert-events?after=0").json()["items"]) == 1


def test_partial_day_registration_aligns_without_baseline_alert(demo):
    client, store, sid, load, _, _, _ = demo
    signal = store.get_signal(sid)
    # End a fresh registration during a KST day; select a value rule that the
    # baseline itself meets, so any unintended baseline evaluation is visible.
    end = END + timedelta(hours=2)
    new_definition = signal.definition.model_copy(update={"normal_comparison": "partial day"})
    data = load(RunRequest(
        question="partial", start_at=end - 7 * DAY, end_at=end, enabled_sources=["app"],
    ))
    try:
        measured = measure_definition(data, new_definition)
    finally:
        data.close()
    other = store.register_definition(
        title="부분 일자", description="부분 일자", definition=new_definition, measurement=measured,
    )
    from customer_signal.signals.alerts import AlertStore
    from customer_signal.signals.alert_contracts import RuleSelection, SelectedRecommendation
    alerts = AlertStore(store)
    recs = build_recommendations(other, measured, [RecommendationDraft(
        metric_key="affected_customer_count", kind="value", operator="gte", threshold=1,
        rationale="하루 한 명 이상",
    )], source="fixture")
    alerts.save_recommendations(other.signal_id, recs)
    alerts.replace_rules(other.signal_id, RuleSelection(revision=0, items=[
        SelectedRecommendation(recommendation_id=recs.items[0].recommendation_id),
    ]))
    response, _ = forward(client, signal_ids=[other.signal_id])
    assert response.status_code == 200, response.text
    day = response.json()["items"][0]["daily_results"][0]
    assert day["start_at"] == (END + DAY).isoformat().replace("+00:00", "Z")
    events = client.get("/api/signal-alert-events?after=0").json()["items"]
    assert len(events) == 1
    assert events[0]["measurement_id"] == day["measurement"]["measurement_id"]


def test_count_only_signal_does_not_treat_unobserved_future_as_zero(demo):
    client, store, sid, load, _, events, _ = demo
    signal = store.get_signal(sid)
    definition = signal.definition.model_copy(update={"denominator_sql": None})
    data = load(RunRequest(
        question="count", start_at=END-DAY, end_at=END, enabled_sources=["app"],
    ))
    try:
        initial = measure_definition(data, definition)
    finally:
        data.close()
    other = store.register_definition(
        title="count", description="count", definition=definition, measurement=initial,
    )
    events[:] = [e for e in events if e.occurred_at < END]
    response, _ = forward(client, signal_ids=[other.signal_id])
    assert response.status_code == 200, response.text
    m = response.json()["items"][0]["daily_results"][0]["measurement"]
    assert m["status"] == "unavailable"
    assert all(v["value"] is None for v in m["values"])


def test_no_selected_rules_measures_without_notifications(demo):
    client, store, sid, _, loads, _, _ = demo
    assert client.put(f"/api/signals/{sid}/alert-rules", json={
        "revision": 1, "items": [],
    }).status_code == 200
    response, _ = forward(client)
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["daily_results"][0]["status"] == "success"
    assert not response.json()["items"][0]["alert_events"]


def test_schedule_lock_blocks_manual_measurement_and_status_change(demo):
    client, store, sid, _, loads, _, _ = demo
    with ScheduleStore(store).lock(sid):
        assert client.patch(f"/api/signals/{sid}", json={"status": "paused"}).status_code == 409
        response = client.post(f"/api/signals/{sid}/measurements", json={
            "start_at": END.isoformat(), "end_at": (END + DAY).isoformat(),
        })
        assert response.status_code == 409
    assert not loads


def test_existing_daily_baseline_wins_over_later_weekly_snapshot_with_same_end(demo):
    client, store, sid, load, _, _, _ = demo
    signal = store.get_signal(sid)
    service = SignalService(store=store, load_data=load)
    daily = service.measure(signal, start_at=END - DAY, end_at=END, evaluate_alerts=False)
    # A newer weekly snapshot with the same end must not hide a daily baseline.
    weekly = store.list_measurements(sid)[0].model_copy(update={
        "measurement_id": str(uuid4()), "snapshot_id": "new-weekly-snapshot",
    })
    store.add_measurement(sid, weekly)
    response, _ = forward(client)
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["baseline_measurement"]["measurement_id"] == daily.measurement_id
    assert len(item["alert_events"]) == 1
    assert item["alert_events"][0]["baseline_measurement_id"] == daily.measurement_id
