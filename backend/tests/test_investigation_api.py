from customer_signal.api import _default_dependencies
from customer_signal.config import Settings
from customer_signal.investigation.runner import InvestigationRunner


async def test_generic_details_use_immutable_facts_without_builtin_repository(tmp_path):
    from customer_signal.agent.contracts import RunRequest
    from test_investigation_runner import ScriptedModel, make_data

    deps = _default_dependencies(
        Settings(
            database_path=tmp_path / "db.duckdb",
            artifact_directory=tmp_path / "artifacts",
            onboarded_sources_dir=tmp_path / "sources",
            agent_mode="fixture",
        )
    )
    request = RunRequest(
        question="헤맨 고객",
        start_at="2026-09-04T00:00:00Z",
        end_at="2026-09-11T00:00:00Z",
        enabled_sources=["app"],
    )

    async def emit(e):
        pass

    outcome = await InvestigationRunner(
        model=ScriptedModel(), data_factory=make_data, artifact_directory=tmp_path
    ).run(request, emit=emit)
    snapshot = deps.store.create_run(request, run_kind="generic")
    await deps.store.mark_running(snapshot.run_id)
    await deps.store.mark_generic_terminal(snapshot.run_id, outcome)
    fact = next(f for f in outcome.facts if f.primitive == "get_customer_journey")
    journey = deps.coordinator.get_journey(snapshot.run_id, fact.payload.customer_id)
    assert journey.events[0].event_id == fact.payload.events[0].event_id
    evidence = deps.coordinator.get_evidence(snapshot.run_id, journey.evidence_ids[0])
    assert evidence.records[0].masked_customer_id == fact.payload.customer_id
    assert evidence.records[0].raw_fields == {}


def test_default_api_wires_gemini_to_investigation_and_keeps_fixture(tmp_path):
    deps = _default_dependencies(
        Settings(
            database_path=tmp_path / "db.duckdb",
            artifact_directory=tmp_path / "artifacts",
            onboarded_sources_dir=tmp_path / "sources",
            gemini_api_key="test-key",
            agent_mode="gemini",
        )
    )
    pack = deps.packs.get("customer_signal")
    assert isinstance(pack._loops["gemini"], InvestigationRunner)
    assert pack._loops["fixture"].__class__.__name__ == "AnalysisLoop"
    registry, ids = deps.refresh_sources()
    assert registry is not deps.registry
    assert ids == deps.source_ids
