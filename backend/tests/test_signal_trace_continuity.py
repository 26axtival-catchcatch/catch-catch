from uuid import uuid4

import pytest

from customer_signal.investigation.contracts import Candidate, Decision
from customer_signal.investigation.data import query_owner
from customer_signal.observability import langfuse as tracing
from customer_signal.signals.contracts import Proposal
from customer_signal.signals.service import SignalService
from customer_signal.signals.store import SignalStore
from customer_signal.signals.workbench import SignalWorkbench
from test_langfuse_observability import _FakeClient
from test_signals import definition, make_data


@pytest.mark.parametrize("has_definition", [True, False])
@pytest.mark.parametrize("pending_verdict", [None, "candidate", "rejected", "reinvestigate"])
def test_analysis_groups_every_pattern_and_registration_resumes_selected_pattern(
    tmp_path, monkeypatch, pending_verdict, has_definition
):
    client = _FakeClient()
    monkeypatch.setattr(tracing, "_get_client", lambda: client)
    store = SignalStore(tmp_path / "signals.sqlite3")
    data = make_data()
    run_id = str(uuid4())
    context = tracing.LangfuseRunContext(run_id, "generic", "합성 질문", ("app",))
    wb = SignalWorkbench(data=data, store=store, run_id=run_id)
    candidates, decisions = [], []
    try:
        with tracing.bind_langfuse_run(context):
            for action in ["close", "done"]:
                d = definition(
                    cohort_sql=f"SELECT customer_id FROM events WHERE action = '{action}'"
                )
                token = query_owner.set("task-investigator")
                try:
                    if action == "close" or has_definition:
                        measured = wb.measure(d)
                        wb.propose(action, measured["measurement_id"])
                    cohort = data.query(d.cohort_sql)["query_id"]
                    candidates.append(
                        Candidate(
                            candidate_id=action,
                            title=action,
                            intent="탐색",
                            cohort_query_id=cohort,
                            evidence_query_ids=[cohort],
                            representative_customer_ids=data.cohort(cohort),
                            behavior_evidence="반복 행동",
                            normal_comparison="정상 완료",
                            resolution="미관측",
                            recommendation="진입점 개선",
                            limitations=["합성 표본"],
                        )
                    )
                finally:
                    query_owner.reset(token)
                verdict = "confirmed" if action == "close" else pending_verdict
                if verdict is not None:
                    token = query_owner.set("task-verifier")
                    try:
                        if action == "close" or has_definition:
                            wb.measure(d)
                        verified = data.query(d.cohort_sql)["query_id"]
                        decisions.append(
                            Decision(
                                candidate_id=action,
                                verdict=verdict,
                                reason="독립 검증 결과",
                                cohort_query_id=verified,
                                evidence_query_ids=[verified],
                            )
                        )
                    finally:
                        query_owner.reset(token)
            proposals = wb.persist(candidates, decisions)
        assert [call["name"] for call in client.calls] == [
            "customer_signal.turn",
            "customer_signal.signals",
            "customer_signal.signal",
            "customer_signal.signal",
        ]
        root, collection, first, second = client.spans
        assert client.calls[1]["trace_context"]["parent_span_id"] == root.id
        assert all(
            call["trace_context"] == {"trace_id": context.trace_id, "parent_span_id": collection.id}
            for call in client.calls[2:]
        )
        assert all(call["metadata"]["operation"] == "pattern" for call in client.calls[2:])
        assert client.calls[2]["input"]["title"] == "close"
        assert ("definition" in client.calls[3]["input"]) is has_definition
        assert (second.updates[-1]["output"]["measurement"] is not None) is has_definition
        first_output = first.updates[-1]["output"]
        assert first_output["verdict"] == "confirmed"
        assert first_output["measurement"]["values"]
        assert first_output["evidence"]["behavior"] == "반복 행동"
        assert second.updates[-1]["output"]["verdict"] == (pending_verdict or "candidate")
        summary = collection.updates[-1]["output"]
        assert summary["pattern_count"] == 2
        assert summary["proposal_count"] == 1
        assert len(summary["patterns"]) == 2
        assert len(proposals) == 1
        assert proposals[0].observation_id == first.id
        assert proposals[0].trace_id == context.trace_id
        assert proposals[0].measurement.trace_id == context.trace_id
        assert (
            SignalStore(store.path).get_proposal(proposals[0].proposal_id).observation_id
            == first.id
        )
        assert store.list_signals() == []

        service = SignalService(store=store, load_data=lambda _: pytest.fail("must not remeasure"))
        selected = service.register_proposal(proposals[0], trace_run_id=str(uuid4()))
        assert len(client.calls) == 6
        assert client.calls[-2]["metadata"]["operation"] == "registration"
        assert client.calls[-2]["trace_context"] == {
            "trace_id": context.trace_id,
            "parent_span_id": first.id,
        }
        assert client.spans[-2].updates[-1]["output"]["signal_id"] == selected.signal_id
        assert client.calls[-1]["name"] == "customer_signal.alert_recommendation"
        assert client.calls[-1]["trace_context"] == {
            "trace_id": context.trace_id, "parent_span_id": client.spans[-2].id,
        }
        assert client.spans[-1].updates[-1]["output"]["status"] == "ready"
    finally:
        data.close()


def test_legacy_proposal_registration_uses_original_trace_without_new_workflow(
    tmp_path, monkeypatch
):
    client = _FakeClient()
    monkeypatch.setattr(tracing, "_get_client", lambda: client)
    store = SignalStore(tmp_path / "signals.sqlite3")
    data = make_data()
    try:
        from customer_signal.signals.measurement import measure_definition

        proposal = Proposal(
            proposal_id="legacy",
            run_id=str(uuid4()),
            candidate_id="old",
            title="기존 후보",
            description="기존 설명",
            definition=definition(),
            measurement=measure_definition(data, definition()),
        )
        store.save_proposal(proposal)
        # Existing rows predate both optional provenance fields.
        import json
        import sqlite3

        with sqlite3.connect(store.path) as db:
            payload = proposal.model_dump(mode="json")
            payload.pop("observation_id")
            payload.pop("trace_id")
            db.execute(
                "UPDATE signal_proposals SET payload = ? WHERE proposal_id = ?",
                (json.dumps(payload), proposal.proposal_id),
            )
        service = SignalService(store=store, load_data=lambda _: None)
        service.register_proposal(store.get_proposal("legacy"))
        assert len(client.calls) == 2
        assert client.calls[0]["name"] == "customer_signal.signal"
        assert client.calls[0]["trace_context"] == {"trace_id": proposal.run_id.replace("-", "")}
        assert client.calls[1]["name"] == "customer_signal.alert_recommendation"
        assert client.calls[1]["trace_context"]["parent_span_id"] == client.spans[0].id
    finally:
        data.close()
