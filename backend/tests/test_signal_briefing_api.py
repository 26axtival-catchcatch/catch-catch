from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from customer_signal.signals.api import create_router
from customer_signal.signals.contracts import Measurement, MetricValue, Proposal
from customer_signal.signals.measurement import definition_fingerprint
from customer_signal.signals.store import SignalStore
from test_signals import definition


START = datetime(2026, 9, 1, tzinfo=timezone.utc)
PATH = "/api/signals/briefing"


def measurement(spec, day=0, value=10, **changes):
    return Measurement.model_validate(
        dict(
            measurement_id=uuid4().hex,
            definition_fingerprint=definition_fingerprint(spec),
            start_at=START + timedelta(days=day),
            end_at=START + timedelta(days=day + 1),
            measured_at=START + timedelta(days=day + 1),
            snapshot_id=uuid4().hex,
            status="success",
            source_ids=spec.source_ids,
            values=[
                MetricValue(
                    key="affected_customer_rate",
                    label="대상 고객 비율",
                    value=value,
                    unit="percent",
                )
            ],
            cohort_customer_ids=["synthetic-private-customer"],
            query_results=[{"private": "synthetic-raw-result"}],
            queries=[{"sql": "SELECT synthetic_private_sql"}],
        )
        | changes
    )


def register(store, name="시그널", *, analysis=False):
    spec = definition(population_description=name)
    initial = measurement(spec)
    if analysis:
        proposal = Proposal(
            proposal_id=uuid4().hex,
            run_id="done",
            candidate_id="candidate",
            title=name,
            description="등록 당시 설명",
            definition=spec,
            measurement=initial,
        )
        store.save_proposal(proposal)
        return store.register(proposal.proposal_id)
    return store.register_definition(
        title=name, description="등록 당시 설명", definition=spec, measurement=initial
    )


@pytest.fixture
def api(tmp_path):
    store = SignalStore(tmp_path / "signals.sqlite3")

    def no_load(_):
        pytest.fail("목록 조회는 측정이나 외부 데이터 로딩을 실행하면 안 됩니다")

    app = FastAPI()
    app.include_router(create_router(store=store, is_completed=lambda _: True, load_data=no_load))
    with TestClient(app) as client:
        yield store, client


def test_empty_briefing_and_existing_list_contract(api):
    _, client = api
    response = client.get(PATH)
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["items"] == []
    assert page["total"] == 0
    assert page["limit"] == 20 and page["offset"] == 0
    assert page["next_offset"] is None
    assert datetime.fromisoformat(page["generated_at"]).tzinfo is not None
    assert client.get("/api/signals").json() == {"items": []}


def test_cards_include_latest_values_comparison_and_private_free_trend(api):
    store, client = api
    signal = register(store, analysis=True)
    newest = measurement(signal.definition, day=1, value=15)
    store.add_measurement(signal.signal_id, newest)
    response = client.get(PATH)
    assert response.status_code == 200, response.text
    card = response.json()["items"][0]
    assert card["signal_id"] == signal.signal_id
    assert card["title"] == signal.title
    assert card["description"] == "등록 당시 설명"
    assert card["origin"] == "analysis" and card["source_ids"] == ["app"]
    assert card["latest_measurement"]["measurement_id"] == newest.measurement_id
    comparison = card["comparison"]
    assert comparison["comparable"] is True
    assert comparison["target_measurement_id"] == newest.measurement_id
    assert comparison["metrics"][0]["absolute_change"] == 5
    assert comparison["metrics"][0]["change_unit"] == "percentage_points"
    assert comparison["metrics"][0]["relative_change_percent"] == 50
    assert card["trend"]["comparable"] is True
    assert [p["values"][0]["value"] for p in card["trend"]["points"]] == [10, 15]
    for private in [
        "cohort_customer_ids",
        "query_results",
        "queries",
        "cohort_sql",
        "synthetic-private",
        "synthetic-raw",
        "synthetic_private",
    ]:
        assert private not in response.text
    assert client.get(f"/api/signals/{signal.signal_id}").json()["definition"]


def test_filter_pagination_and_stable_newest_registration_order(api):
    store, client = api
    old = register(store, "첫 번째")
    paused = register(store, "중지")
    store.set_status(paused.signal_id, "paused")
    archived = register(store, "보관")
    store.set_status(archived.signal_id, "archived")
    new = register(store, "최근")
    first = client.get(PATH, params={"limit": 1}).json()
    assert first["total"] == 2 and first["next_offset"] == 1
    assert first["items"][0]["signal_id"] == new.signal_id
    second = client.get(PATH, params={"limit": 1, "offset": first["next_offset"]}).json()
    assert second["items"][0]["signal_id"] == old.signal_id
    assert second["next_offset"] is None
    for status, expected in [("paused", paused), ("archived", archived)]:
        page = client.get(PATH, params={"status": status}).json()
        assert page["total"] == 1 and page["items"][0]["signal_id"] == expected.signal_id
    assert client.get(PATH, params={"status": "all"}).json()["total"] == 4
    beyond = client.get(PATH, params={"offset": 10**30}).json()
    assert beyond["items"] == [] and beyond["total"] == 2 and beyond["next_offset"] is None
    assert len(client.get("/api/signals").json()["items"]) == 4


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": "bad"},
        {"offset": -1},
        {"status": "unknown"},
    ],
)
def test_invalid_queries_are_422(api, params):
    _, client = api
    assert client.get(PATH, params=params).status_code == 422


def test_latest_window_prefers_success_and_ignores_late_old_backfill(api):
    store, client = api
    signal = register(store)
    good = measurement(signal.definition, day=2, value=25)
    store.add_measurement(signal.signal_id, good)
    failed = measurement(
        signal.definition,
        day=2,
        status="unavailable",
        values=[],
        measured_at=START + timedelta(days=20),
    )
    store.add_measurement(signal.signal_id, failed)
    backfill = measurement(
        signal.definition, day=1, value=20, measured_at=START + timedelta(days=30)
    )
    store.add_measurement(signal.signal_id, backfill)
    card = client.get(PATH).json()["items"][0]
    assert card["latest_measurement"]["measurement_id"] == good.measurement_id
    assert card["comparison"]["baseline_measurement_id"] == backfill.measurement_id
    assert [p["values"][0]["value"] for p in card["trend"]["points"]] == [10, 20, 25]


def test_single_window_and_unavailable_latest_do_not_invent_deltas(api):
    store, client = api
    signal = register(store)
    card = client.get(PATH).json()["items"][0]
    assert card["origin"] == "user_defined"
    assert not card["comparison"]["comparable"] and card["comparison"]["metrics"] == []
    assert not card["trend"]["comparable"]
    unavailable = measurement(
        signal.definition,
        day=1,
        status="unavailable",
        values=[],
        reason="대상 기간의 데이터가 없습니다.",
    )
    store.add_measurement(signal.signal_id, unavailable)
    card = client.get(PATH).json()["items"][0]
    assert card["latest_measurement"]["status"] == "unavailable"
    assert card["latest_measurement"]["values"] == []
    assert card["comparison"]["comparison_limitations"]
    assert card["comparison"]["metrics"] == []
    assert not card["trend"]["comparable"]


@pytest.mark.parametrize(
    "changes",
    [
        {"pipeline_version": "changed"},
        {"source_versions": {"app": "v2"}},
        {"start_at": START + timedelta(hours=12)},
        {"values": [MetricValue(key="other", label="다른 지표", value=1, unit="count")]},
    ],
)
def test_incomparable_windows_hide_comparison_and_trend(api, changes):
    store, client = api
    signal = register(store)
    store.add_measurement(signal.signal_id, measurement(signal.definition, day=1, **changes))
    card = client.get(PATH).json()["items"][0]
    assert not card["comparison"]["comparable"] and card["comparison"]["metrics"] == []
    assert not card["trend"]["comparable"] and card["trend"]["comparison_limitations"]


def test_trend_is_limited_to_seven_distinct_periods(api):
    store, client = api
    signal = register(store)
    for day in range(1, 10):
        store.add_measurement(signal.signal_id, measurement(signal.definition, day=day, value=day))
    card = client.get(PATH).json()["items"][0]
    assert [p["values"][0]["value"] for p in card["trend"]["points"]] == list(range(3, 10))


def test_openapi_has_typed_briefing_and_query_contract(api):
    _, client = api
    schema = client.get("/openapi.json").json()
    operation = schema["paths"][PATH]["get"]
    assert operation["tags"] == ["signals"]
    assert "브리핑" in operation["summary"]
    assert {p["name"] for p in operation["parameters"]} == {"status", "limit", "offset"}
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SignalBriefingList"
    }
