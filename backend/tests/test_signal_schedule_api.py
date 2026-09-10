from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from customer_signal.signals.api import create_router
from customer_signal.signals.comparison import compare_measurements
from customer_signal.signals.scheduling import DailyScheduler
from test_signal_scheduling import setup, END  # noqa: F401


@pytest.fixture
def api(setup):  # noqa: F811
    store, schedules, signal, service = setup
    app = FastAPI()
    app.include_router(
        create_router(store=store, is_completed=lambda _: True, load_data=service.load_data)
    )
    with TestClient(app) as client:
        yield client, signal.signal_id, DailyScheduler(schedules, service), schedules


def test_schedule_api_validation_and_busy(api):
    client, sid, worker, schedules = api
    path = f"/api/signals/{sid}/schedule"
    assert client.get(path).json()["timezone"] == "Asia/Seoul"
    assert client.put(path, json={"enabled": False}).json()["enabled"] is False
    assert worker.tick(END) == 0
    assert (
        client.put(path, json={"enabled": True, "next_run_at": END.isoformat()}).status_code == 200
    )
    for value in ["2026-09-01T00:00:00Z", "2026-09-01T00:00:00", "bad"]:
        assert client.put(path, json={"enabled": True, "next_run_at": value}).status_code == 422
    with schedules.lock(sid):
        assert client.put(path, json={"enabled": False}).status_code == 409
    assert client.get("/api/signals/missing/schedule").status_code == 404
    assert client.put("/api/signals/missing/schedule", json={"enabled": True}).status_code == 404


def test_daily_pagination_default_comparison_and_openapi(api):
    client, sid, worker, _ = api
    root = f"/api/signals/{sid}"
    assert not client.get(root + "/comparison").json()["comparable"]
    worker.tick(END + timedelta(days=1))
    worker.tick(END + timedelta(days=1))
    response = client.get(root + "/daily-results?limit=1")
    assert response.status_code == 200, response.text
    page = response.json()
    assert len(page["items"]) == 1 and page["next_before"]
    next_page = client.get(
        root + "/daily-results", params={"limit": 1, "before": page["next_before"]}
    ).json()
    assert len(next_page["items"]) == 1 and next_page["next_before"] is None
    assert page["items"][0]["execution_id"] != next_page["items"][0]["execution_id"]
    assert client.get(root + "/daily-results?limit=0").status_code == 422
    assert client.get(root + "/daily-results?before=2026-09-01").status_code == 422
    comparison = client.get(root + "/comparison").json()
    assert comparison["comparable"] and len(comparison["metrics"]) == 3
    assert all(m["absolute_change"] == 0 for m in comparison["metrics"])
    assert comparison["metrics"][2]["change_unit"] == "percentage_points"
    assert client.get(root + "/comparison?baseline_measurement_id=missing").status_code == 422
    assert (
        client.get(
            root + "/comparison",
            params={"baseline_measurement_id": "other-signal", "target_measurement_id": "missing"},
        ).status_code
        == 404
    )
    schema = client.get("/openapi.json").json()
    for path, methods in schema["paths"].items():
        for method in methods.values():
            assert method["tags"] == ["signals"]
            assert any("\uac00" <= c <= "\ud7a3" for c in method["summary"])
            assert method["responses"]["200"]["content"]["application/json"]["schema"]


def two_measurements(api):
    client, sid, worker, schedules = api
    worker.tick(END + timedelta(days=1))
    worker.tick(END + timedelta(days=1))
    results = schedules.results(sid).items
    return results[1].measurement, results[0].measurement


def test_comparison_changes_and_zero_baseline(api):
    baseline, target = two_measurements(api)
    baseline.values[0].value = 0
    target.values[0].value = 2
    baseline.values[2].value = 10
    target.values[2].value = 15
    result = compare_measurements(baseline, target)
    assert result.comparable
    assert result.metrics[0].absolute_change == 2
    assert result.metrics[0].relative_change_percent is None
    assert result.metrics[2].absolute_change == 5
    assert result.metrics[2].relative_change_percent == 50


@pytest.mark.parametrize(
    "change",
    [
        {"status": "unavailable"},
        {"definition_fingerprint": "changed"},
        {"pipeline_version": "changed"},
        {"source_versions": {"app": "changed"}},
        {"source_ids": ["other"]},
        {"start_at": END - timedelta(days=1)},
        {"end_at": END + timedelta(days=2)},
    ],
)
def test_incomparable_measurements_never_report_numeric_deltas(api, change):
    baseline, target = two_measurements(api)
    result = compare_measurements(baseline, target.model_copy(update=change))
    assert not result.comparable and result.comparison_limitations
    assert result.metrics == []


def test_manual_recovery_updates_daily_measurement_but_keeps_execution_status(api):
    client, sid, worker, schedules = api
    good = worker.service.load_data
    worker.service.load_data = lambda _: (_ for _ in ()).throw(ValueError("private"))
    worker.tick(END)
    worker.service.load_data = good
    response = client.post(
        f"/api/signals/{sid}/measurements",
        json={"start_at": (END - timedelta(days=1)).isoformat(), "end_at": END.isoformat()},
    )
    assert response.status_code == 200
    result = schedules.results(sid).items[0]
    assert result.status == "unavailable"  # immutable execution outcome
    assert result.measurement.status == "success"  # latest successful measurement


def test_percent_symbol_metrics_use_percentage_point_changes(api):
    baseline, target = two_measurements(api)
    baseline.values[2].unit = target.values[2].unit = "%"
    baseline.values[2].value = 10
    target.values[2].value = 15
    result = compare_measurements(baseline, target)
    assert result.metrics[2].change_unit == "percentage_points"
    assert result.metrics[2].absolute_change == 5
