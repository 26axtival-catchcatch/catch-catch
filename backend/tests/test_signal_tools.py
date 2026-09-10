import importlib
from uuid import uuid4

import pytest

from customer_signal.agent.contracts import RunRequest
from customer_signal.investigation.data import InvestigationData, query_owner
from customer_signal.investigation.contracts import Candidate, Decision
from test_investigation_data import event


def workbench_type():
    try:
        return importlib.import_module("customer_signal.signals.workbench").SignalWorkbench
    except ModuleNotFoundError:
        pytest.fail(
            "SignalWorkbench must implement measured proposals and independent verification"
        )


def test_only_independently_remeasured_confirmed_proposal_can_be_persisted(tmp_path):
    Workbench = workbench_type()
    from customer_signal.signals.store import SignalStore
    from customer_signal.signals.contracts import SignalDefinition

    store = SignalStore(tmp_path / "signals.sqlite3")
    request = RunRequest(
        question="헤맨 고객",
        start_at="2026-09-04T00:00:00Z",
        end_at="2026-09-11T00:00:00Z",
        enabled_sources=["app"],
    )
    data = InvestigationData(
        request=request, events=[event(1), event(2)], manifests=[], snapshot_id="a"
    )
    wb = Workbench(data=data, store=store, run_id=str(uuid4()))
    definition = SignalDefinition(
        source_ids=["app"],
        cohort_sql="SELECT customer_id FROM events",
        population_description="앱 탐색 고객",
        normal_comparison="정상 완료와 비교",
    )
    try:
        token = query_owner.set("task-search")
        measured = wb.measure(definition)
        wb.propose("search-loop", measured["measurement_id"])
        cohort = data.query("SELECT DISTINCT customer_id FROM events")["query_id"]
        candidate = Candidate(
            candidate_id="search-loop",
            title="반복 탐색",
            intent="서비스 찾기",
            cohort_query_id=cohort,
            evidence_query_ids=[cohort],
            representative_customer_ids=data.cohort(cohort)[:1],
            behavior_evidence="반복 문의",
            normal_comparison="정상 완료 비교",
            resolution="미관측",
            recommendation="진입점 개선",
        )
        query_owner.reset(token)
        decision = Decision(
            candidate_id="search-loop",
            verdict="confirmed",
            reason="검증",
            cohort_query_id=cohort,
            evidence_query_ids=[cohort],
        )
        assert wb.verified_measurement(decision, "task-verification-0") is None
        assert store.list_signals() == []
        token = query_owner.set("task-verification-0")
        verified = wb.measure(definition)
        verified_cohort = data.query("SELECT DISTINCT customer_id FROM events")["query_id"]
        decision = decision.model_copy(update={"cohort_query_id": verified_cohort})
        assert (
            wb.verified_measurement(decision, "task-verification-0").measurement_id
            == verified["measurement_id"]
        )
        query_owner.reset(token)
        wb.persist([candidate], [decision])
        proposals = store.list_proposals(wb.run_id)
        assert len(proposals) == 1
        assert store.list_signals() == []
        assert store.register(proposals[0].proposal_id).title == "반복 탐색"
        with pytest.raises(ValueError):
            wb.propose("fake", "invented-measurement")
    finally:
        data.close()


def test_unconfirmed_proposals_do_not_persist(tmp_path):
    Workbench = workbench_type()
    from customer_signal.signals.store import SignalStore

    store = SignalStore(tmp_path / "signals.sqlite3")
    request = RunRequest(
        question="헤맨 고객",
        start_at="2026-09-04T00:00:00Z",
        end_at="2026-09-11T00:00:00Z",
        enabled_sources=["app"],
    )
    data = InvestigationData(request=request, events=[event(1)], manifests=[], snapshot_id="a")
    try:
        wb = Workbench(data=data, store=store, run_id=str(uuid4()))
        wb.persist([], [])
        assert store.list_proposals(wb.run_id) == []
    finally:
        data.close()


async def test_runner_persists_measured_proposal_without_registering(tmp_path):
    Workbench = workbench_type()
    from customer_signal.signals.store import SignalStore
    from customer_signal.signals.contracts import SignalDefinition
    from customer_signal.investigation.runner import InvestigationRunner
    from test_investigation_runner import ScriptedModel, make_data

    store = SignalStore(tmp_path / "signals.sqlite3")

    class Model(ScriptedModel):
        async def run_role(self, **kwargs):
            result = await super().run_role(**kwargs)
            if kwargs["role"] in {"investigator", "verifier"}:
                wb = kwargs["data"].signal_workbench
                assert isinstance(wb, Workbench)
                measured = wb.measure(
                    SignalDefinition(
                        source_ids=["app"],
                        cohort_sql="SELECT DISTINCT customer_id FROM events",
                        population_description="앱 탐색 고객",
                        normal_comparison="정상 완료 고객 비교",
                    )
                )
                if kwargs["role"] == "investigator":
                    wb.propose("search-loop", measured["measurement_id"])
            return result

    request = RunRequest(
        question="헤맨 고객",
        start_at="2026-09-04T00:00:00Z",
        end_at="2026-09-11T00:00:00Z",
        enabled_sources=["app"],
    )

    async def emit(event):
        pass

    outcome = await InvestigationRunner(
        model=Model(), data_factory=make_data, artifact_directory=tmp_path, signal_store=store
    ).run(request, emit=emit)
    assert outcome.status == "completed"
    assert store.list_signals() == []
    import json

    audit = json.loads(next((tmp_path / "investigations").glob("*.json")).read_text())
    proposals = store.list_proposals(audit["run_id"])
    assert len(proposals) == 1
    assert proposals[0].measurement.values[0].value == 1


async def test_unmeasurable_analysis_candidate_remains_pending(tmp_path):
    from customer_signal.signals.store import SignalStore
    from customer_signal.investigation.runner import InvestigationRunner
    from customer_signal.investigation.model import _reference_feedback
    from test_investigation_runner import ScriptedModel, make_data

    store = SignalStore(tmp_path / "signals.sqlite3")

    class Model(ScriptedModel):
        async def run_role(self, **kwargs):
            result = await super().run_role(**kwargs)
            if kwargs["role"] == "investigator":
                assert (
                    _reference_feedback(
                        result,
                        data=kwargs["data"],
                        task_id=kwargs["task_id"],
                        context=kwargs["context"],
                    )
                    is None
                )
            return result

    request = RunRequest(
        question="헤맨 고객",
        start_at="2026-09-04T00:00:00Z",
        end_at="2026-09-11T00:00:00Z",
        enabled_sources=["app"],
    )

    async def emit(e):
        pass

    outcome = await InvestigationRunner(
        model=Model(), data_factory=make_data, artifact_directory=tmp_path, signal_store=store
    ).run(request, emit=emit)
    assert outcome.status == "completed"
    assert not outcome.report.findings
    assert store.list_signals() == []
    assert any("재측정" in s for s in outcome.report.limitations)
