import asyncio
import json

import pytest
from botocore.exceptions import ClientError
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from customer_signal.config import Settings
from customer_signal.investigation import model as investigation_model
from customer_signal.investigation.contracts import Narrative
from test_investigation_model import Data, ScriptedProvider, call, finish


def test_bedrock_token_selects_auto_and_is_secret():
    settings = Settings(
        agent_mode="auto",
        aws_bearer_token_bedrock="bedrock-test-secret",
        gemini_api_key="gemini-test-key",
        _env_file=None,
    )
    assert settings.resolved_agent_mode == "bedrock"
    assert isinstance(settings.aws_bearer_token_bedrock, SecretStr)
    assert "bedrock-test-secret" not in settings.model_dump_json()
    assert settings.model_copy(update={"agent_mode": "fixture"}).resolved_agent_mode == "fixture"
    assert settings.model_copy(update={"agent_mode": "gemini"}).resolved_agent_mode == "gemini"


def test_bedrock_artifact_restores_provider_without_guessing_model_name():
    from customer_signal.runtime.run_store import RunStore
    from test_artifact_store import _artifact

    artifact = _artifact(status="completed")
    artifact.versions = artifact.versions.model_copy(update={
        "agent_mode": "bedrock", "model_version": "custom-inference-profile",
    })
    store = RunStore([artifact])
    assert store.get_snapshot(str(artifact.run_id)).agent_mode == "bedrock"
    assert store.get_requested_mode(str(artifact.run_id)) == "bedrock"


def make_model(provider, **kwargs):
    cls = getattr(investigation_model, "BedrockInvestigationModel", None)
    assert cls is not None, "Bedrock investigation adapter is missing"
    return cls(
        api_key="bedrock-test-secret",
        model="test-model",
        region="us-east-1",
        model_factory=provider,
        **kwargs,
    )


async def run_role(model):
    return await model.run_role(
        role="reporter",
        task_id="task-report",
        instruction="요약",
        context={},
        data=Data(),
        result_type=Narrative,
    )


async def test_bedrock_tool_roundtrip_and_provider_metadata():
    provider = ScriptedProvider({"test-model": [call("catalog_data"), finish()]})
    model = make_model(provider)
    result = await run_role(model)
    assert result.headline == "검증 결과"
    assert model.agent_mode == "bedrock"
    assert provider.models[0]["region_name"] == "us-east-1"
    assert provider.models[0]["api_key"].get_secret_value() == "bedrock-test-secret"
    config = provider.calls[0]["config"]
    assert config["run_name"] == "customer_signal.reporter"
    assert config["metadata"]["provider"] == "bedrock"
    assert "bedrock" in config["tags"]
    assert "bedrock-test-secret" not in json.dumps(config)


@pytest.mark.parametrize(
    "failure,code",
    [
        (
            ClientError(
                {"Error": {"Code": "AccessDeniedException", "Message": "private"}}, "Converse"
            ),
            "bedrock_access_denied",
        ),
        (TimeoutError("private"), "bedrock_timeout"),
    ],
)
async def test_bedrock_failure_is_safe_and_never_falls_back(failure, code):
    provider = ScriptedProvider({"test-model": [failure]})
    model = make_model(provider)
    with pytest.raises(RuntimeError) as caught:
        await run_role(model)
    assert caught.value.code == code
    assert "private" not in str(caught.value)
    assert len(provider.calls) == 1


async def test_bedrock_cancellation_propagates():
    model = make_model(ScriptedProvider({"test-model": [asyncio.CancelledError()]}))
    with pytest.raises(asyncio.CancelledError):
        await run_role(model)


async def test_bedrock_routes_concurrent_roles_to_their_configured_models():
    async def investigator_response():
        await asyncio.sleep(0)
        return AIMessage(content="investigator-result")

    provider = ScriptedProvider({
        "test-model": [AIMessage(content="base-result")] * 3,
        "investigator-profile": [investigator_response] * 2,
    })
    model = make_model(provider, investigator_model="investigator-profile")
    roles = ["investigator", "coordinator", "verifier", "investigator", "reporter"]
    results = await asyncio.gather(*(
        model._invoke([], role=role, task_id=f"task-{index}", round_index=0)
        for index, role in enumerate(roles)
    ))
    assert [result.content for result in results] == [
        "investigator-result" if role == "investigator" else "base-result" for role in roles
    ]
    assert {entry["model"] for entry in provider.models} == {"test-model", "investigator-profile"}
    assert len(provider.models) == 2
    for entry in provider.calls:
        metadata = entry["config"]["metadata"]
        assert metadata["model"] == (
            "investigator-profile" if metadata["role"] == "investigator" else "test-model"
        )
    assert model.model_name == "test-model"


async def test_investigator_failure_does_not_fall_back_to_base_model():
    provider = ScriptedProvider({"investigator-profile": [TimeoutError("private")]})
    model = make_model(provider, investigator_model="investigator-profile")
    with pytest.raises(investigation_model.BedrockInvestigationError) as caught:
        await model._invoke([], role="investigator", task_id="task-1", round_index=0)
    assert caught.value.code == "bedrock_timeout"
    assert [entry["model"] for entry in provider.models] == ["investigator-profile"]
    assert len(provider.calls) == 1


async def test_bedrock_allows_model_to_finish_after_many_turns():
    provider = ScriptedProvider({"test-model": [AIMessage(content="계속")] * 33 + [finish()]})
    await run_role(make_model(provider))
    assert len(provider.calls) == 34
    assert provider.calls[-1]["binding"] == {}


def test_api_wires_bedrock_and_exposes_mode_in_swagger(tmp_path):
    from customer_signal.api import _default_dependencies, create_app

    settings = Settings(
        agent_mode="bedrock",
        aws_bearer_token_bedrock="test-key",
        database_path=tmp_path / "db.duckdb",
        artifact_directory=tmp_path / "artifacts",
        onboarded_sources_dir=tmp_path / "sources",
        _env_file=None,
    )
    deps = _default_dependencies(settings)
    pack = deps.packs.get("customer_signal")
    assert pack._loops["bedrock"].model.agent_mode == "bedrock"
    assert pack._loops["bedrock"].model._model_for_role("investigator") == settings.bedrock_investigator_model
    assert pack._loops["bedrock"].model._model_for_role("reporter") == settings.bedrock_model
    assert deps.generic_default_mode == "bedrock"
    schema = create_app(dependencies=deps).openapi()
    parameter = next(
        p for p in schema["paths"]["/api/runs"]["post"]["parameters"] if p["name"] == "mode"
    )
    mode_schema = parameter["schema"]["anyOf"][0]
    if "$ref" in mode_schema:
        mode_schema = schema["components"]["schemas"][mode_schema["$ref"].split("/")[-1]]
    assert "bedrock" in mode_schema["enum"]


async def test_bedrock_outcome_and_events_keep_mode(tmp_path):
    from customer_signal.agent.contracts import RunRequest
    from customer_signal.investigation.runner import InvestigationRunner
    from customer_signal.runtime.events import validate_generic_event
    from test_investigation_runner import ScriptedModel, make_data

    model = ScriptedModel()
    model.agent_mode = "bedrock"
    events = []

    async def emit(event):
        events.append(event)

    outcome = await InvestigationRunner(
        model=model, data_factory=make_data, artifact_directory=tmp_path
    ).run(
        RunRequest(
            question="헤맨 고객",
            start_at="2026-09-04T00:00:00Z",
            end_at="2026-09-11T00:00:00Z",
            enabled_sources=["app"],
        ),
        emit=emit,
    )
    assert outcome.status == "completed"
    assert outcome.agent_mode == "bedrock"
    result = next(e for e in events if e.type == "result")
    assert result.payload["agent_mode"] == "bedrock"
    validate_generic_event(result.type, result.payload)
