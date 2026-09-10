from fastapi import FastAPI
from fastapi.testclient import TestClient

from customer_signal.signals.api import create_router
from customer_signal.signals.alert_contracts import (
    RecommendationDraft,
    RuleSelection,
    SelectedRecommendation,
)
from customer_signal.signals.alert_recommendations import build_recommendations
from customer_signal.signals.alerts import AlertStore
from customer_signal.signals.scheduling import DailyScheduler
from test_signal_first_class import registry, direct_payload  # noqa: F401
from test_signal_scheduling import setup, END  # noqa: F401


def test_registration_returns_recommendations_and_explicit_opt_in(registry):  # noqa: F811
    store, client = registry
    created = client.post("/api/signals", json={"proposal_id": "done"}).json()
    sid = created["signal_id"]
    recs = created["alert_recommendations"]
    assert recs["status"] == "ready" and recs["source"] == "measurement"
    base = f"/api/signals/{sid}"
    assert client.get(base + "/alert-recommendations").json() == recs
    assert client.get(base + "/alert-rules").json()["items"] == []
    rid = recs["items"][0]["recommendation_id"]
    request = {"revision": 0, "items": [{"recommendation_id": rid, "threshold": 1}]}
    saved = client.put(base + "/alert-rules", json=request)
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 1
    assert client.put(base + "/alert-rules", json=request).status_code == 409
    assert client.get("/api/signal-alert-events").json()["items"] == []
    response = client.post(
        base + "/measurements",
        json={
            "start_at": "2026-09-02T00:00:00Z",
            "end_at": "2026-09-03T00:00:00Z",
        },
    )
    assert response.status_code == 200
    page = client.get("/api/signal-alert-events?after=0").json()
    assert len(page["items"]) == 1 and page["items"][0]["signal_id"] == sid
    assert client.get("/api/signal-alert-events").json()["next_cursor"] == page["next_cursor"]
    assert "cohort_customer_ids" not in str(page) and "queries" not in str(page)
    assert (
        client.post("/api/signals", json=direct_payload()).json()["alert_recommendations"] == recs
    )
    assert client.post(base + "/alert-recommendations").json() == recs
    schema = client.get("/openapi.json").json()
    for path in [
        "/api/signal-alert-events",
        base.replace(sid, "{signal_id}") + "/alert-rules",
        base.replace(sid, "{signal_id}") + "/alert-recommendations",
    ]:
        for operation in schema["paths"][path].values():
            assert operation["tags"] == ["signals"]
            assert any("\uac00" <= c <= "\ud7a3" for c in operation["summary"])
            assert operation["responses"]["200"]["content"]["application/json"]["schema"]


def test_api_validation_and_missing_signals(registry):  # noqa: F811
    _, client = registry
    signal = client.post("/api/signals", json=direct_payload()).json()
    sid = signal["signal_id"]
    for method, suffix in [
        ("get", "/alert-rules"),
        ("get", "/alert-recommendations"),
        ("post", "/alert-recommendations"),
    ]:
        assert getattr(client, method)("/api/signals/missing" + suffix).status_code == 404
    assert (
        client.put(
            "/api/signals/missing/alert-rules", json={"revision": 0, "items": []}
        ).status_code
        == 404
    )
    for qs in ["after=-1", "after=bad", "limit=0", "limit=501"]:
        assert client.get("/api/signal-alert-events?" + qs).status_code == 422
    assert (
        client.put(
            f"/api/signals/{sid}/alert-rules",
            json={"revision": 0, "items": [{"recommendation_id": "unknown"}]},
        ).status_code
        == 422
    )


def test_daily_scheduler_to_polling_integration(setup):  # noqa: F811
    store, schedules, signal, service = setup
    alerts = AlertStore(store)
    recs = build_recommendations(
        signal,
        store.list_measurements(signal.signal_id)[0],
        [
            RecommendationDraft(
                metric_key="affected_customer_count",
                kind="value",
                operator="gte",
                threshold=1,
                rationale="합성 고객 수 확인",
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
    app = FastAPI()
    app.include_router(
        create_router(store=store, is_completed=lambda _: True, load_data=service.load_data)
    )
    assert DailyScheduler(schedules, service).tick(END) == 1
    with TestClient(app) as client:
        page = client.get("/api/signal-alert-events?after=0").json()
    assert len(page["items"]) == 1
    assert (
        page["items"][0]["measurement_id"]
        == schedules.results(signal.signal_id).items[0].measurement.measurement_id
    )


def test_recommendation_failure_preserves_registration_and_retries_once(tmp_path):
    from customer_signal.signals.store import SignalStore
    from customer_signal.signals.alert_recommendations import fixture_recommendations
    from test_signals import make_data

    calls = []

    def recommend(signal, measurement):
        calls.append(signal.signal_id)
        if len(calls) == 1:
            raise ValueError("private-secret")
        return fixture_recommendations(signal, measurement)

    store = SignalStore(tmp_path / "signals.sqlite3")
    app = FastAPI()
    app.include_router(
        create_router(
            store=store,
            is_completed=lambda _: True,
            load_data=lambda _: make_data(),
            recommend=recommend,
        )
    )
    with TestClient(app) as client:
        created = client.post("/api/signals", json=direct_payload())
        assert created.status_code == 200
        sid = created.json()["signal_id"]
        assert created.json()["alert_recommendations"]["status"] == "unavailable"
        assert "private-secret" not in created.text
        assert len(store.list_signals()) == 1
        duplicate = client.post("/api/signals", json=direct_payload())
        assert duplicate.json()["signal_id"] == sid and len(calls) == 1
        response = client.post(f"/api/signals/{sid}/alert-recommendations")
        assert response.json()["status"] == "ready" and len(calls) == 2
        assert client.post(f"/api/signals/{sid}/alert-recommendations").json() == response.json()
        assert len(calls) == 2


def test_nonfinite_json_threshold_is_a_validation_error(registry):  # noqa: F811
    _, client = registry
    signal = client.post("/api/signals", json=direct_payload()).json()
    rid = signal["alert_recommendations"]["items"][0]["recommendation_id"]
    path = f"/api/signals/{signal['signal_id']}/alert-rules"
    for value in ["1e309", "NaN", "Infinity", "-Infinity"]:
        response = client.put(
            path,
            content=(
                '{"revision":0,"items":[{"recommendation_id":"'
                + rid
                + '","threshold":'
                + value
                + "}]}"
            ),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422


def test_legacy_recommendations_upgrade_without_changing_active_alerts(registry):  # noqa: F811
    store, client = registry
    signal = client.post("/api/signals", json={"proposal_id": "done"}).json()
    sid = signal["signal_id"]
    base = f"/api/signals/{sid}"
    legacy = signal["alert_recommendations"]
    legacy["source"] = "model"
    legacy["items"] = [dict(legacy["items"][0], recommendation_id="legacy-rate",
        kind="relative_change_percent", comparison_unit="percent", threshold=35)]
    signal["alert_recommendations"] = legacy
    import json
    with store._connection() as db:
        db.execute("UPDATE signals SET payload=? WHERE signal_id=?", (json.dumps(signal), sid))
    saved = client.put(base + "/alert-rules", json={
        "revision": 0, "items": [{"recommendation_id": "legacy-rate", "threshold": 42}],
    }).json()
    upgraded = client.post(base + "/alert-recommendations").json()
    assert upgraded["source"] == "measurement"
    assert all(item["kind"] == "value" and item["operator"] == "gte" for item in upgraded["items"])
    assert client.get(base + "/alert-rules").json() == saved
    assert client.post("/api/signals", json={"proposal_id": "done"}).json()["alert_recommendations"] == upgraded
    selected = client.put(base + "/alert-rules", json={
        "revision": saved["revision"],
        "items": [{"recommendation_id": upgraded["items"][0]["recommendation_id"], "threshold": 12}],
    })
    assert selected.status_code == 200
    assert selected.json()["items"][0]["threshold"] == 12
    assert selected.json()["items"][0]["kind"] == "value"
