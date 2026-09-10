import importlib
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from customer_signal.agent.contracts import RunRequest
from customer_signal.investigation.data import InvestigationData
from test_investigation_data import event


def test_user_selection_registration_measurement_history_and_swagger(tmp_path):
    try:
        create_router = importlib.import_module("customer_signal.signals.api").create_router
    except ModuleNotFoundError:
        pytest.fail("Signal API must expose registration and measurement history")
    from customer_signal.signals.contracts import Proposal, SignalDefinition
    from customer_signal.signals.measurement import measure_definition
    from customer_signal.signals.store import SignalStore

    store = SignalStore(tmp_path / "signals.sqlite3")
    run_id = str(uuid4())
    completed = {run_id: True}

    def load(request):
        events = [event(1), event(2)]
        return InvestigationData(
            request=request,
            events=[e for e in events if request.start_at <= e.occurred_at < request.end_at],
            manifests=[],
            snapshot_id="ignored-random-id",
        )

    request = RunRequest(
        question="헤맨 고객",
        start_at="2026-09-04T00:00:00Z",
        end_at="2026-09-11T00:00:00Z",
        enabled_sources=["app"],
    )
    data = load(request)
    definition = SignalDefinition(
        source_ids=["app"],
        cohort_sql="SELECT customer_id FROM events",
        denominator_sql="SELECT customer_id FROM events",
        population_description="탐색 고객",
        normal_comparison="정상 완료 고객 비교",
    )
    try:
        measurement = measure_definition(data, definition)
    finally:
        data.close()
    proposal = Proposal(
        proposal_id=str(uuid4()),
        run_id=run_id,
        candidate_id="a",
        title="반복 탐색",
        description="같은 의도로 반복 탐색",
        definition=definition,
        measurement=measurement,
        created_at=datetime.now(timezone.utc),
        limitations=[],
    )
    store.save_proposal(proposal)
    app = FastAPI()
    app.include_router(
        create_router(
            store=store, is_completed=lambda rid: completed.get(rid, False), load_data=load
        )
    )
    with TestClient(app) as client:
        assert client.get("/api/signals").json()["items"] == []
        completed[run_id] = False
        assert (
            client.post("/api/signals", json={"proposal_id": proposal.proposal_id}).status_code
            == 409
        )
        completed[run_id] = True
        proposals = client.get(f"/api/runs/{run_id}/signal-proposals").json()["items"]
        assert len(proposals) == 1
        response = client.post("/api/signals", json={"proposal_id": proposal.proposal_id})
        assert response.status_code == 200, response.text
        signal_id = response.json()["signal_id"]
        assert (
            client.post("/api/signals", json={"proposal_id": proposal.proposal_id}).json()[
                "signal_id"
            ]
            == signal_id
        )
        assert len(client.get("/api/signals").json()["items"]) == 1
        payload = {"start_at": "2026-09-11T00:00:00Z", "end_at": "2026-09-18T00:00:00Z"}
        result = client.post(f"/api/signals/{signal_id}/measurements", json=payload)
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "unavailable"  # empty denominator is not 0 percent
        assert (
            client.patch(f"/api/signals/{signal_id}", json={"status": "paused"}).json()["status"]
            == "paused"
        )
        history = client.get(f"/api/signals/{signal_id}/measurements").json()
        assert len(history["items"]) == 2
        assert "cohort_customer_ids" not in str(history)
        assert client.get("/api/signals/unknown").status_code == 404
        schema = client.get("/openapi.json").json()
        for path, methods in schema["paths"].items():
            for method in methods.values():
                assert method["tags"] == ["signals"]
                assert any("\uac00" <= c <= "\ud7a3" for c in method["summary"])
                assert method["responses"]["200"]["content"]["application/json"]["schema"]
    reopened = SignalStore(tmp_path / "signals.sqlite3")
    assert reopened.get_signal(signal_id).status == "paused"
    assert len(reopened.list_measurements(signal_id)) == 2
