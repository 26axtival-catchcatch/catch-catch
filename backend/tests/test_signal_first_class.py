from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from customer_signal.signals.api import create_router
from customer_signal.signals.contracts import Proposal
from customer_signal.signals.measurement import measure_definition
from customer_signal.signals.store import SignalStore
from test_signals import definition, make_data


@pytest.fixture
def registry(tmp_path):
    store = SignalStore(tmp_path / "signals.sqlite3")
    completed = {"done"}
    data = make_data()
    try:
        for run in ["done", "pending"]:
            store.save_proposal(
                Proposal(
                    proposal_id=run,
                    run_id=run,
                    candidate_id="pattern",
                    title="패턴",
                    description="패턴 설명",
                    definition=definition(),
                    measurement=measure_definition(data, definition()),
                )
            )
    finally:
        data.close()
    app = FastAPI()
    app.include_router(
        create_router(
            store=store,
            is_completed=completed.__contains__,
            load_data=lambda request: make_data(day=request.start_at.day),
        )
    )
    with TestClient(app) as client:
        yield store, client


def direct_payload():
    return dict(
        title="직접 정의",
        description="사용자가 등록한 정의",
        definition=definition().model_dump(mode="json"),
        start_at="2026-09-01T00:00:00Z",
        end_at="2026-09-02T00:00:00Z",
    )


def test_global_proposals_only_expose_completed_runs(registry):
    _, client = registry
    response = client.get("/api/signal-proposals")
    assert response.status_code == 200
    assert [p["proposal_id"] for p in response.json()["items"]] == ["done"]
    assert client.get("/api/signal-proposals?run_id=pending").status_code == 409
    assert client.get("/api/signal-proposals/done").json()["run_id"] == "done"
    assert client.get("/api/signal-proposals/pending").status_code == 409
    assert client.get("/api/signal-proposals/missing").status_code == 404


def test_direct_registration_measures_and_deduplicates_with_proposals(registry):
    store, client = registry
    response = client.post("/api/signals", json=direct_payload())
    assert response.status_code == 200, response.text
    signal = response.json()
    assert signal["proposal_id"] is None
    assert signal["origin"] == "user_defined"
    signal_id = signal["signal_id"]
    assert store.list_measurements(signal_id)[0].values[0].value == 1
    assert client.post("/api/signals", json=direct_payload()).json()["signal_id"] == signal_id
    assert (
        client.post("/api/signals", json={"proposal_id": "done"}).json()["signal_id"] == signal_id
    )
    assert len(store.list_signals()) == 1
    assert len(store.list_measurements(signal_id)) == 1
    assert SignalStore(store.path).get_signal(signal_id).proposal_id is None


@pytest.mark.parametrize(
    "change",
    [
        {"values": [{"key": "affected_customer_count", "value": 100}]},
        {"title": "   "},
        {"description": " \n\t "},
        {"proposal_id": "done"},
        {"end_at": "2026-08-01T00:00:00Z"},
        {"start_at": "2026-09-01T00:00:00"},
        {"definition": definition(cohort_sql="SELECT missing FROM events").model_dump(mode="json")},
    ],
)
def test_invalid_direct_registration_never_persists(registry, change):
    store, client = registry
    response = client.post("/api/signals", json=direct_payload() | change)
    assert response.status_code == 422
    assert store.list_signals() == []


def test_registration_and_remeasurement_emit_signal_identity(registry, monkeypatch):
    from customer_signal.signals import service

    store, client = registry
    spans = []

    @contextmanager
    def observe(**kwargs):
        span = dict(kwargs)
        spans.append(span)
        yield SimpleNamespace(id=f"span-{len(spans)}", update=lambda **values: span.update(values))

    monkeypatch.setattr(service, "signal_observation", observe)
    signal_id = client.post("/api/signals", json=direct_payload()).json()["signal_id"]
    client.post("/api/signals", json={"proposal_id": "done"})
    client.post(
        f"/api/signals/{signal_id}/measurements",
        json={"start_at": "2026-09-02T00:00:00Z", "end_at": "2026-09-03T00:00:00Z"},
    )
    assert [s["operation"] for s in spans] == ["direct_registration", "registration", "measurement"]
    assert all(s["output"]["signal_id"] == signal_id for s in spans)
    assert spans[1]["proposal_id"] == "done"
    assert spans[1]["candidate_id"] == "pattern"
    assert spans[2]["signal_id"] == signal_id
    assert all(s["output"]["measurement"]["values"] for s in spans)
    persisted_ids = {m.measurement_id for m in store.list_measurements(signal_id)}
    assert all(s["output"]["measurement_id"] in persisted_ids for s in spans)


def test_legacy_schema_migration_preserves_ids_and_foreign_keys(registry):
    import sqlite3

    store, _ = registry
    original = store.register("done")
    measurement = store.list_measurements(original.signal_id)[0]
    # Reproduce the pre-extension NOT NULL schema without discarding related data.
    with sqlite3.connect(store.path) as db:
        db.executescript("""
            CREATE TABLE legacy_signals (
                signal_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
                proposal_id TEXT NOT NULL REFERENCES signal_proposals(proposal_id),
                payload TEXT NOT NULL);
            INSERT INTO legacy_signals SELECT * FROM signals;
            DROP TABLE signals;
            ALTER TABLE legacy_signals RENAME TO signals;
        """)
    reopened = SignalStore(store.path)
    assert reopened.get_signal(original.signal_id) == original
    assert reopened.register("done").signal_id == original.signal_id
    assert (
        reopened.list_measurements(original.signal_id)[0].measurement_id
        == measurement.measurement_id
    )
    with sqlite3.connect(store.path) as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert (
            next(
                row for row in db.execute("PRAGMA table_info(signals)") if row[1] == "proposal_id"
            )[3]
            == 0
        )
    assert SignalStore(store.path).get_signal(original.signal_id) == original


def test_same_investigator_task_keeps_two_distinct_verified_patterns(tmp_path, monkeypatch):
    from customer_signal.investigation.contracts import Candidate, Decision
    from customer_signal.investigation.data import query_owner
    from customer_signal.signals import workbench

    spans = []

    @contextmanager
    def observe(**kwargs):
        span = dict(kwargs)
        spans.append(span)
        yield SimpleNamespace(id=f"span-{len(spans)}", update=lambda **values: span.update(values))

    monkeypatch.setattr(workbench, "signal_observation", observe, raising=False)
    store = SignalStore(tmp_path / "signals.sqlite3")
    data = make_data()
    wb = workbench.SignalWorkbench(data=data, store=store, run_id="run")
    candidates, decisions = [], []
    try:
        for action in ["close", "done"]:
            d = definition(cohort_sql=f"SELECT customer_id FROM events WHERE action = '{action}'")
            token = query_owner.set("task-shared")
            try:
                measurement = wb.measure(d)
                wb.propose(action, measurement["measurement_id"])
                cohort = data.query(d.cohort_sql)["query_id"]
                candidates.append(
                    Candidate(
                        candidate_id=action,
                        title=action,
                        intent="의도",
                        cohort_query_id=cohort,
                        evidence_query_ids=[cohort],
                        representative_customer_ids=data.cohort(cohort),
                        behavior_evidence="행동",
                        normal_comparison="정상",
                        resolution="미관측",
                        recommendation="제안",
                    )
                )
            finally:
                query_owner.reset(token)
            token = query_owner.set("task-verifier")
            try:
                wb.measure(d)
                verified = data.query(d.cohort_sql)["query_id"]
                decisions.append(
                    Decision(
                        candidate_id=action,
                        verdict="confirmed",
                        reason="검증",
                        cohort_query_id=verified,
                        evidence_query_ids=[verified],
                    )
                )
            finally:
                query_owner.reset(token)
        proposals = wb.persist(candidates, decisions)
        assert len(proposals) == 2
        assert all(p.task_id == "task-shared" for p in proposals)
        assert store.list_signals() == []
        assert len({store.register(p.proposal_id).signal_id for p in proposals}) == 2
        assert spans[0]["operation"] == "collection"
        spans = spans[1:]
        assert {s["candidate_id"] for s in spans} == {"close", "done"}
        assert all(s["task_id"] == "task-shared" for s in spans)
        assert {s["proposal_id"] for s in spans} == {p.proposal_id for p in proposals}
    finally:
        data.close()


def test_direct_attempts_have_new_traces_and_proposal_registration_uses_analysis_trace(registry):
    store, client = registry
    created = client.post("/api/signals", json=direct_payload())
    trace_id = created.headers.get("X-Langfuse-Trace-Id")
    assert trace_id and len(trace_id) == 32
    signal_id = created.json()["signal_id"]
    retried = client.post("/api/signals", json=direct_payload())
    assert retried.headers["X-Langfuse-Trace-Id"] != trace_id
    assert store.list_measurements(signal_id)[0].trace_id == trace_id
    registered = client.post("/api/signals", json={"proposal_id": "done"})
    from customer_signal.observability.langfuse import LangfuseRunContext

    assert (
        registered.headers["X-Langfuse-Trace-Id"]
        == LangfuseRunContext("done", "generic", "", ("app",)).trace_id
    )
    retried_proposal = client.post("/api/signals", json={"proposal_id": "done"})
    assert (
        retried_proposal.headers["X-Langfuse-Trace-Id"] == registered.headers["X-Langfuse-Trace-Id"]
    )
    measured = client.post(
        f"/api/signals/{signal_id}/measurements",
        json={"start_at": "2026-09-02T00:00:00Z", "end_at": "2026-09-03T00:00:00Z"},
    )
    assert measured.headers["X-Langfuse-Trace-Id"] == measured.json()["trace_id"]


def test_direct_registration_transaction_rolls_back_if_measurement_conflicts(registry):
    store, client = registry
    original = client.post("/api/signals", json={"proposal_id": "done"}).json()
    first = store.list_measurements(original["signal_id"])[0]
    data = make_data()
    other = definition(cohort_sql="SELECT customer_id FROM events WHERE action = 'done'")
    try:
        conflicting = measure_definition(data, other).model_copy(
            update={"measurement_id": first.measurement_id}
        )
    finally:
        data.close()
    with pytest.raises(ValueError, match="measurement_id"):
        store.register_definition(
            title="다른 정의", description="충돌", definition=other, measurement=conflicting
        )
    assert len(store.list_signals()) == 1
    assert store.list_measurements(original["signal_id"])[0].measurement_id == first.measurement_id


def test_direct_registration_source_load_failure_returns_422_without_persistence(tmp_path):
    store = SignalStore(tmp_path / "signals.sqlite3")

    def fail_load(request):
        raise RuntimeError("private provider failure")

    app = FastAPI()
    app.include_router(create_router(store=store, is_completed=lambda _: True, load_data=fail_load))
    with TestClient(app) as client:
        response = client.post("/api/signals", json=direct_payload())
    assert response.status_code == 422
    assert "private provider failure" not in response.text
    assert store.list_signals() == []
    assert store.list_proposals() == []
