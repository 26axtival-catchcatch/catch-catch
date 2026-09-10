import asyncio
import json

import pytest
from pydantic import ValidationError

from customer_signal.agent.contracts import RunRequest
from customer_signal.investigation.runner import InvestigationRunner
from customer_signal.runtime.events import validate_generic_event
from customer_signal.packs.customer_signal import _emission_for
from customer_signal.runtime.wire_projection import wire_events_for
from test_investigation_runner import ScriptedModel, make_data
from test_journal_wire_replay import canonical


def request():
    return RunRequest(
        question="헤맨 고객",
        start_at="2026-09-04T00:00:00Z",
        end_at="2026-09-11T00:00:00Z",
        enabled_sources=["app"],
    )


async def collect(tmp_path, model=None, **kwargs):
    events = []

    async def emit(event):
        events.append(event)

    outcome = await InvestigationRunner(
        model=model or ScriptedModel(),
        data_factory=make_data,
        artifact_directory=tmp_path,
        **kwargs,
    ).run(request(), emit=emit)
    return outcome, events


async def test_actual_role_topology_reinvestigation_and_journal_projection(tmp_path):
    outcome, events = await collect(tmp_path)
    activity = [e for e in events if e.type == "agent_activity"]
    assert activity, "Actual role execution must be streamed before Fact projection"
    roles = [e.payload for e in activity if e.payload["kind"] == "agent"]
    queued = [p for p in roles if p["status"] == "queued"]
    completed = [p for p in roles if p["status"] == "completed"]
    assert len(queued) == len(completed) == 6
    assert len({p["node_id"] for p in queued}) == 6
    known = set()
    for p in queued:
        assert set(p["depends_on"]) <= known
        known.add(p["node_id"])
    followup = next(p for p in queued if p["role"] == "investigator" and p["round_index"] == 1)
    verifier = next(p for p in completed if p["role"] == "verifier" and p["round_index"] == 0)
    assert followup["depends_on"] == [verifier["node_id"]]
    for e in activity:
        payload = validate_generic_event(e.type, e.payload)
        emission = _emission_for(e)
        assert wire_events_for(canonical("activity.changed", emission.payload)) == [
            (e.type, payload)
        ]
    assert all(p["duration_ms"] >= 0 for p in completed)
    assessments = [e.payload for e in activity if e.payload["kind"] == "assessment"]
    assert assessments[-1]["details"]["decisions"][0]["verdict"] == "confirmed"
    assert outcome.status == "completed"


async def test_cancelled_roles_close_nodes(tmp_path):
    class Slow(ScriptedModel):
        async def run_role(self, **kwargs):
            if kwargs["role"] == "coordinator":
                await asyncio.sleep(10)
            return await super().run_role(**kwargs)

    _, events = await collect(tmp_path, Slow(), investigation_seconds=0.02)
    activity = [e.payload for e in events if e.type == "agent_activity"]
    assert any(p["status"] == "cancelled" for p in activity)
    opened = {p["node_id"] for p in activity if p["status"] == "started"}
    closed = {p["node_id"] for p in activity if p["status"] in {"completed", "failed", "cancelled"}}
    assert opened <= closed


async def test_model_and_tool_events_are_live_and_safe(tmp_path):
    from customer_signal.investigation.activity import ActivityStream
    from customer_signal.investigation.contracts import Narrative
    from customer_signal.investigation.model import GeminiInvestigationModel
    from test_investigation_model import ScriptedProvider, Data, call, finish

    events = []

    async def emit(event):
        events.append(event)

    async def provider_response():
        assert events[-1].payload["kind"] == "model"
        assert events[-1].payload["status"] == "started"
        return call("query_data", sql="SELECT 'private-marker' AS secret")

    provider = ScriptedProvider({"primary": [provider_response, finish()]})
    stream = ActivityStream(emit)
    node = await stream.agent("reporter", "task-reporting", 0, [])
    model = GeminiInvestigationModel(
        api_key="private-key",
        primary_model="primary",
        fallback_model="primary",
        model_factory=provider,
    )
    with stream.bind(node):
        await model.run_role(
            role="reporter",
            task_id="task-reporting",
            instruction="private-prompt",
            context={},
            data=Data(),
            result_type=Narrative,
        )
    tools = [e.payload for e in events if e.payload["kind"] == "tool"]
    assert [p["status"] for p in tools] == ["started", "completed", "started", "completed"]
    assert tools[1]["details"]["query_id"] == "query-1"
    assert all(p["parent_node_id"] == node.node_id for p in tools)
    wire = json.dumps([e.payload for e in events])
    for private in ("private-marker", "private-key", "private-prompt", "customer-1"):
        assert private not in wire
    for event in events:
        validate_generic_event(event.type, event.payload)


async def test_activity_rejects_untyped_internal_values(tmp_path):
    _, events = await collect(tmp_path)
    activity = next(e for e in events if e.type == "agent_activity")
    with pytest.raises(ValidationError):
        validate_generic_event(
            "agent_activity", {**activity.payload, "details": {"rows": [{"secret": "x"}]}}
        )


async def test_http_stream_replay_after_restart_and_swagger(tmp_path):
    from fastapi.testclient import TestClient
    from customer_signal.api import _default_dependencies, create_app
    from customer_signal.config import Settings

    settings = Settings(
        database_path=tmp_path / "db.duckdb",
        artifact_directory=tmp_path / "artifacts",
        onboarded_sources_dir=tmp_path / "sources",
        agent_mode="fixture",
    )
    deps = _default_dependencies(settings)
    from customer_signal.investigation.data import InvestigationData
    from test_investigation_data import event

    def api_data(req):
        return InvestigationData(
            request=req,
            events=[event(1, source="search_history")],
            manifests=[],
            snapshot_id="test-api",
        )

    deps.packs.get("customer_signal")._loops["fixture"] = InvestigationRunner(
        model=ScriptedModel(), data_factory=api_data, artifact_directory=tmp_path
    )

    def frames(text):
        return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]

    with TestClient(create_app(dependencies=deps)) as client:
        response = client.post(
            "/api/runs?mode=fixture",
            json={**request().model_dump(mode="json"), "enabled_sources": ["search_history"]},
        )
        assert response.status_code == 202
        url = response.json()["events_url"]
        original = client.get(url)
        values = frames(original.text)
        assert any(e["type"] == "agent_activity" for e in values)
        assert values[-1]["type"] == "done"
        assert values[-1]["payload"]["status"] == "completed"
        schema = client.get("/openapi.json").json()
        assert "AgentActivityPayload" in schema["components"]["schemas"]
    with TestClient(create_app(settings=settings)) as client:
        replay = client.get(url)
        assert frames(replay.text) == values
        assert frames(client.get(url, headers={"Last-Event-ID": "4"}).text) == values[4:]


async def test_parallel_operations_keep_their_own_parent_nodes():
    from customer_signal.investigation.activity import ActivityStream, operation

    events = []

    async def emit(event):
        events.append(event)

    stream = ActivityStream(emit)
    nodes = [await stream.agent("investigator", f"task-{i}", 0, []) for i in range(2)]
    ready = asyncio.Event()
    count = 0

    async def investigate(node):
        nonlocal count
        with stream.bind(node):
            async with operation("tool", "query_data"):
                count += 1
                if count == 2:
                    ready.set()
                await ready.wait()

    await asyncio.gather(*(investigate(node) for node in nodes))
    for event in events:
        if event.payload["kind"] == "tool":
            parent = next(n for n in nodes if n.task_id == event.payload["task_id"])
            assert event.payload["parent_node_id"] == parent.node_id
    assert len([e for e in events if e.payload["status"] == "completed"]) == 2


async def test_tool_repair_failure_is_visible_without_leaking_arguments():
    from customer_signal.investigation.activity import ActivityStream
    from customer_signal.investigation.contracts import Narrative
    from customer_signal.investigation.model import GeminiInvestigationModel
    from test_investigation_model import ScriptedProvider, Data, call, finish

    events = []

    async def emit(event):
        events.append(event)

    stream = ActivityStream(emit)
    node = await stream.agent("reporter", "task-repair", 0, [])
    provider = ScriptedProvider(
        {"model": [call("query_data", unknown="private-error-marker"), finish()]}
    )
    model = GeminiInvestigationModel(
        api_key="test", primary_model="model", fallback_model="model", model_factory=provider
    )
    with stream.bind(node):
        await model.run_role(
            role="reporter",
            task_id=node.task_id,
            instruction="",
            context={},
            data=Data(),
            result_type=Narrative,
        )
    failed = [e.payload for e in events if e.payload["status"] == "failed"]
    assert failed[0]["details"]["error_code"] == "validation_failed"
    assert events[-1].payload["status"] == "completed"
    assert "private-error-marker" not in json.dumps([e.payload for e in events])


async def test_parallel_verifier_activity_keeps_candidate_followup_and_report_dependencies(
    tmp_path,
):
    from customer_signal.investigation.verification import verifier_task_id
    from test_verification_context import SplitModel

    outcome, events = await collect(tmp_path, model=SplitModel(followup=True))
    assert outcome.status == "completed"
    queued = [
        e.payload
        for e in events
        if e.type == "agent_activity"
        and e.payload["kind"] == "agent"
        and e.payload["status"] == "queued"
    ]
    verifiers = [e for e in queued if e["role"] == "verifier"]
    original = next(e for e in verifiers if e["task_id"] == verifier_task_id("pattern-0", 0))
    followup = next(e for e in queued if e["role"] == "investigator" and e["round_index"] == 1)
    assert followup["depends_on"] == [original["node_id"]]
    reporter = next(e for e in queued if e["role"] == "reporter")
    assert set(reporter["depends_on"]) == {e["node_id"] for e in verifiers}


@pytest.mark.parametrize(
    "name,label",
    [
        ("read_query_result", "질의 결과 추가 조회"),
        ("recheck_candidate", "후보 근거 재검증"),
    ],
)
async def test_verifier_helpers_have_tool_activity_labels(name, label):
    from customer_signal.investigation.activity import ActivityStream, operation

    events = []

    async def emit(event):
        events.append(event.payload)

    stream = ActivityStream(emit)
    node = await stream.agent("verifier", "task-verifier", 0, [])
    with stream.bind(node):
        async with operation("tool", name):
            pass
    assert events[-1]["kind"] == "tool"
    assert events[-1]["display_text"] == label
