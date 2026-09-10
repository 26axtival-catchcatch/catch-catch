from __future__ import annotations

import asyncio
import json
import threading
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langsmith.utils import get_env_var, tracing_is_enabled
from pydantic import ValidationError

from customer_signal.investigation.contracts import (
    Coordination,
    InvestigationResult,
    Narrative,
    Task,
    Verification,
)
from customer_signal.investigation.model import GeminiInvestigationError, GeminiInvestigationModel


class ScriptedProvider:
    def __init__(self, responses):
        self.responses = defaultdict(list, responses)
        self.models = []
        self.calls = []
        self.tools = []

    def __call__(self, **kwargs):
        self.models.append(kwargs)
        provider = self

        class Chat:
            def bind_tools(self, tools, **binding):
                provider.tools = tools
                self.binding = binding
                return self

            async def ainvoke(self, messages, config):
                provider.calls.append(
                    {"messages": list(messages), "config": config, "binding": self.binding}
                )
                value = provider.responses[kwargs["model"]].pop(0)
                if isinstance(value, BaseException):
                    raise value
                if callable(value):
                    return await value()
                return value

        return Chat()


def call(name, **args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "call-1"}])


def finish(headline="검증 결과", summary="공개 근거 요약"):
    return call("finish", document=json.dumps({"headline": headline, "summary": summary}))


query_owner = ContextVar("test_query_owner", default=None)


class Data:
    def __init__(self):
        self.calls = []

    def catalog(self):
        self.calls.append(("catalog",))
        return {"columns": ["customer_id"], "tables": ["events"]}

    def query(self, sql):
        self.calls.append(("query", sql, threading.get_ident(), query_owner.get()))
        return {"query_id": "query-1", "rows": [{"customer_id": "customer-1"}]}

    def journey(self, customer_id):
        self.calls.append(("journey", customer_id))
        return {"customer_id": customer_id, "events": []}


class ReferenceData(Data):
    def __init__(self):
        super().__init__()
        self.queries = {
            "query-small": {"owner": "task-research", "rows": [{"customer_id": "customer-1"}]},
            "query-empty": {"owner": "task-research", "rows": []},
            "query-full": {
                "owner": "task-verifier",
                "rows": [{"customer_id": "customer-1"}, {"customer_id": "customer-2"}],
            },
        }
        self.journey_reads = {}

    def cohort(self, query_id):
        if query_id not in self.queries:
            raise ValueError("private database detail")
        return [row["customer_id"] for row in self.queries[query_id]["rows"]]

    def query(self, sql):
        self.queries["query-fixed"] = {
            "owner": query_owner.get(),
            "rows": self.queries["query-full"]["rows"],
        }
        return {"query_id": "query-fixed", **self.queries["query-fixed"]}

    def journey(self, customer_id):
        self.journey_reads.setdefault(query_owner.get(), set()).add(customer_id)
        return super().journey(customer_id)


def investigation_candidate(**changes):
    return {
        "candidate_id": "candidate-1",
        "title": "관찰된 탐색",
        "intent": "동일 목표 찾기",
        "cohort_query_id": "query-full",
        "evidence_query_ids": ["query-full"],
        "representative_customer_ids": ["customer-1", "customer-2"],
        "behavior_evidence": "반복 조회",
        "normal_comparison": "정상 탐색과 비교",
        "resolution": "최종 해결",
        "recommendation": "추가 확인",
        **changes,
    }


async def run(model, data=None):
    return await model.run_role(
        role="research",
        task_id="task-research",
        instruction="전체 공간 조사",
        context={"question": "반복 탐색을 설명해줘"},
        data=data or Data(),
        result_type=Narrative,
        round_index=1,
    )


def test_contracts_reject_extra_fields_and_invalid_tasks():
    assert Coordination(tasks=[Task(task_id="task-research", question="합성 질문")], summary="계획")
    for document in (
        {"task_id": "wrong-id", "question": "질문"},
        {"task_id": "task-research", "question": "질문", "private": "hidden"},
        {"task_id": "task-research", "question": "x" * 1001},
    ):
        with pytest.raises(ValidationError):
            Task.model_validate(document)
    with pytest.raises(ValidationError):
        Coordination(tasks=[], summary="계획")
    with pytest.raises(ValidationError):
        Narrative(headline="x" * 301, summary="공개 요약")


async def test_tool_loop_runs_authorized_data_queries_off_thread_and_finishes():
    provider = ScriptedProvider(
        {
            "primary": [
                call("catalog_data"),
                call("query_data", sql="SELECT customer_id FROM events"),
                call("customer_journey", customer_id="customer-1"),
                finish(),
            ]
        }
    )
    model = GeminiInvestigationModel(
        api_key="test-key",
        primary_model="primary",
        fallback_model="fallback",
        model_factory=provider,
    )
    data = Data()
    token = query_owner.set("task-research")
    try:
        result = await run(model, data)
    finally:
        query_owner.reset(token)
    assert result == Narrative(headline="검증 결과", summary="공개 근거 요약")
    assert data.calls[0] == ("catalog",)
    assert data.calls[1][0:2] == ("query", "SELECT customer_id FROM events")
    assert data.calls[1][2] != threading.get_ident()
    assert data.calls[1][3] == "task-research"
    assert data.calls[2] == ("journey", "customer-1")
    assert len(provider.calls) == 4
    assert {tool["name"] for tool in provider.tools} == {
        "catalog_data",
        "query_data",
        "customer_journey",
        "finish",
    }
    assert provider.models[0]["retries"] == 1
    assert provider.models[0]["request_timeout"] <= 55
    config = provider.calls[0]["config"]
    assert config["run_name"] == "customer_signal.research"
    assert config["metadata"]["stage"] == "research"
    assert config["metadata"]["task_id"] == "task-research"
    assert config["metadata"]["round_index"] == 1
    messages = provider.calls[-1]["messages"]
    assert sum(isinstance(message, ToolMessage) for message in messages) == 3
    assert "untrusted" in messages[0].content.lower()


async def test_invalid_finish_recovers_with_bounded_feedback_without_private_values():
    provider = ScriptedProvider(
        {
            "primary": [
                call(
                    "finish",
                    document=json.dumps({"headline": "x" * 350, "private-secret": "private-value"}),
                ),
                finish(),
            ]
        }
    )
    model = GeminiInvestigationModel(
        api_key="test-key",
        primary_model="primary",
        fallback_model="fallback",
        model_factory=provider,
    )
    assert isinstance(await run(model), Narrative)
    feedback = provider.calls[1]["messages"][-1].content
    assert "validation" in feedback.lower()
    assert "private-value" not in feedback
    assert "private-secret" not in feedback
    assert len(feedback) < 1500


async def test_tool_failure_is_safe_feedback_and_can_recover():
    class FailingData(Data):
        def query(self, sql):
            raise ValueError("private provider or database detail")

    provider = ScriptedProvider({"primary": [call("query_data", sql="invalid SQL"), finish()]})
    model = GeminiInvestigationModel(
        api_key="test-key",
        primary_model="primary",
        fallback_model="fallback",
        model_factory=provider,
    )
    assert isinstance(await run(model, FailingData()), Narrative)
    feedback = provider.calls[1]["messages"][-1].content
    assert "private" not in feedback
    assert "query_failed" in feedback


class NotFoundError(RuntimeError):
    code = "NOT_FOUND"


@pytest.mark.parametrize(
    "error, fallback",
    [(NotFoundError("private response"), True), (RuntimeError("private response"), False)],
)
async def test_fallback_only_on_typed_not_found_and_safe_provider_errors(error, fallback):
    provider = ScriptedProvider({"primary": [error], "fallback": [finish()]})
    model = GeminiInvestigationModel(
        api_key="test-key",
        primary_model="primary",
        fallback_model="fallback",
        model_factory=provider,
    )
    if fallback:
        assert isinstance(await run(model), Narrative)
        assert model.model_name == "fallback"
    else:
        with pytest.raises(GeminiInvestigationError) as caught:
            await run(model)
        assert caught.value.code == "gemini_provider_failed"
        assert "private" not in str(caught.value)
        assert len(provider.models) == 1


async def test_role_turn_budget_is_bounded_and_forces_finish_on_final_three_calls():
    provider = ScriptedProvider({"primary": [AIMessage(content="진행 중") for _ in range(32)]})
    model = GeminiInvestigationModel(
        api_key="test-key",
        primary_model="primary",
        fallback_model="fallback",
        model_factory=provider,
    )
    with pytest.raises(GeminiInvestigationError) as caught:
        await run(model)
    assert caught.value.code == "gemini_turn_limit"
    assert len(provider.calls) == 32
    assert all(record["binding"] == {} for record in provider.calls[:29])
    for record in provider.calls[-3:]:
        assert "finish" in record["messages"][-1].content
        assert record["binding"] == {"tool_choice": "finish"}


async def test_last_turn_can_repair_finish_after_extended_investigation():
    provider = ScriptedProvider(
        {
            "primary": [
                *[call("catalog_data") for _ in range(30)],
                call("finish", document='{"headline":"제목"}'),
                finish(),
            ]
        }
    )
    model = GeminiInvestigationModel(
        api_key="test-key",
        primary_model="primary",
        fallback_model="fallback",
        model_factory=provider,
    )
    assert isinstance(await run(model), Narrative)
    assert len(provider.calls) == 32
    feedback = json.loads(provider.calls[-1]["messages"][-2].content)
    assert feedback["issues"] == [
        {"loc": ["summary"], "type": "missing", "message": "Required field is missing."}
    ]


async def test_nested_finish_feedback_and_spans_expose_only_contract_paths_and_constraints(
    monkeypatch,
):
    spans = []

    @contextmanager
    def observation(**kwargs):
        record = {**kwargs, "outputs": []}
        spans.append(record)

        class Span:
            def update(self, *, output):
                record["outputs"].append(output)

        yield Span()

    monkeypatch.setattr("customer_signal.investigation.model.public_observation", observation)
    candidate = {
        "candidate_id": "candidate-1",
        "title": "관찰된 탐색",
        "intent": "동일 목표 찾기",
        "cohort_query_id": "query-1",
        "evidence_query_ids": ["query-2"],
        "representative_customer_ids": ["customer-1", "customer-2", "customer-3"],
        "behavior_evidence": "x" * 1001,
        "normal_comparison": "정상 탐색과 비교",
        "resolution": "최종 해결",
        "recommendation": "추가 확인",
        "private-key": "private-value",
    }
    invalid = {"candidates": [candidate], "limitations": []}
    valid = {"candidates": [], "limitations": ["현재 근거가 부족합니다."]}
    provider = ScriptedProvider(
        {
            "primary": [
                call("finish", document=json.dumps(invalid)),
                call("finish", document=json.dumps(valid)),
            ]
        }
    )
    model = GeminiInvestigationModel(
        api_key="test-key",
        primary_model="primary",
        fallback_model="fallback",
        model_factory=provider,
    )
    result = await model.run_role(
        role="research",
        task_id="task-research",
        instruction="조사",
        context={},
        data=Data(),
        result_type=InvestigationResult,
    )
    feedback = json.loads(provider.calls[1]["messages"][-1].content)
    issues = {tuple(issue["loc"]): issue for issue in feedback["issues"]}
    assert (
        issues[("candidates", 0, "representative_customer_ids")]["message"]
        == "Use at most 2 items."
    )
    assert (
        issues[("candidates", 0, "behavior_evidence")]["message"] == "Use at most 1000 characters."
    )
    assert issues[("candidates", 0, "[extra_field]")]["type"] == "extra_forbidden"
    assert len(json.dumps(feedback)) < 1500
    assert len(spans) == 2
    assert all(span["name"] == "customer_signal.tool.finish" for span in spans)
    assert spans[0]["outputs"] == [feedback]
    assert spans[1]["outputs"] == [result.model_dump(mode="json")]
    serialized = json.dumps({"spans": spans, "feedback": feedback})
    assert "private-key" not in serialized and "private-value" not in serialized
    assert "x" * 100 not in serialized


async def test_finish_argument_validation_is_also_traced_without_raw_document(monkeypatch):
    spans = []

    @contextmanager
    def observation(**kwargs):
        record = dict(kwargs)
        spans.append(record)

        class Span:
            def update(self, *, output):
                record["output"] = output

        yield Span()

    monkeypatch.setattr("customer_signal.investigation.model.public_observation", observation)
    provider = ScriptedProvider(
        {"primary": [call("finish", document={"private-key": "private-value"}), finish()]}
    )
    model = GeminiInvestigationModel(
        api_key="test-key",
        primary_model="primary",
        fallback_model="fallback",
        model_factory=provider,
    )
    await run(model)
    assert spans[0]["output"]["issues"][0]["loc"] == ["document"]
    assert spans[0]["output"]["issues"][0]["type"] == "string_type"
    assert "private-value" not in json.dumps(spans)


async def test_timeout_and_cancellation_are_preserved():
    async def pending():
        await asyncio.Future()

    provider = ScriptedProvider({"primary": [pending, pending]})
    model = GeminiInvestigationModel(
        api_key="test-key",
        primary_model="primary",
        fallback_model="fallback",
        model_factory=provider,
        timeout_seconds=0.01,
    )
    with pytest.raises(GeminiInvestigationError) as caught:
        await run(model)
    assert caught.value.code == "gemini_timeout"
    task = asyncio.create_task(run(model))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.parametrize(
    "changes, problem",
    [
        ({"cohort_query_id": "query-missing"}, "cohort_invalid"),
        ({"cohort_query_id": "query-empty"}, "cohort_empty"),
        ({"cohort_query_id": "query-small"}, "representative_outside_cohort"),
        ({"evidence_query_ids": ["query-missing"]}, "evidence_query_unknown"),
    ],
)
async def test_finish_rejects_invalid_investigation_references_with_safe_feedback(changes, problem):
    model = GeminiInvestigationModel(
        api_key="test-key", primary_model="primary", fallback_model="fallback"
    )
    result = await model._run_tool(
        name="finish",
        arguments={
            "document": json.dumps(
                {"candidates": [investigation_candidate(**changes)], "limitations": []}
            )
        },
        data=ReferenceData(),
        result_type=InvestigationResult,
        task_id="task-research",
    )
    assert result["error"] == "result_reference_invalid"
    assert result["issues"][0]["candidate_id"] == "candidate-1"
    assert result["issues"][0]["problem"] == problem
    assert "SELECT DISTINCT customer_id" in result["issues"][0]["instruction"]
    assert "private database detail" not in json.dumps(result)


async def test_investigator_can_fix_cohort_reference_in_same_role_and_trace_failure(monkeypatch):
    finish_outputs = []

    @contextmanager
    def observation(**kwargs):
        class Span:
            def update(self, *, output):
                if kwargs["name"] == "customer_signal.tool.finish":
                    finish_outputs.append(output)

        yield Span()

    monkeypatch.setattr("customer_signal.investigation.model.public_observation", observation)
    wrong = {
        "candidates": [investigation_candidate(cohort_query_id="query-small")],
        "limitations": [],
    }
    fixed = {
        "candidates": [
            investigation_candidate(
                cohort_query_id="query-fixed", evidence_query_ids=["query-fixed"]
            )
        ],
        "limitations": [],
    }
    provider = ScriptedProvider(
        {
            "primary": [
                call("finish", document=json.dumps(wrong)),
                call("query_data", sql="SELECT DISTINCT customer_id FROM events"),
                call("finish", document=json.dumps(fixed)),
            ]
        }
    )
    model = GeminiInvestigationModel(
        api_key="test-key",
        primary_model="primary",
        fallback_model="fallback",
        model_factory=provider,
    )
    result = await model.run_role(
        role="research",
        task_id="task-research",
        instruction="조사",
        context={},
        data=ReferenceData(),
        result_type=InvestigationResult,
    )
    assert len(provider.calls) == 3
    assert result.candidates[0].cohort_query_id == "query-fixed"
    assert finish_outputs[0]["error"] == "result_reference_invalid"
    assert finish_outputs[1] == result.model_dump(mode="json")


async def test_verifier_can_review_required_representatives_then_finish():
    document = {
        "decisions": [
            {
                "candidate_id": "candidate-1",
                "verdict": "confirmed",
                "reason": "검증 결과",
                "cohort_query_id": "query-full",
                "evidence_query_ids": ["query-full"],
            }
        ],
        "limitations": [],
    }
    provider = ScriptedProvider(
        {
            "primary": [
                call("finish", document=json.dumps(document)),
                call("customer_journey", customer_id="customer-1"),
                call("customer_journey", customer_id="customer-2"),
                call("finish", document=json.dumps(document)),
            ]
        }
    )
    model = GeminiInvestigationModel(
        api_key="test-key",
        primary_model="primary",
        fallback_model="fallback",
        model_factory=provider,
    )
    data = ReferenceData()
    token = query_owner.set("task-verifier")
    try:
        result = await model.run_role(
            role="verification",
            task_id="task-verifier",
            instruction="독립 검증",
            context={"candidates": [investigation_candidate()]},
            data=data,
            result_type=Verification,
        )
    finally:
        query_owner.reset(token)
    assert len(provider.calls) == 4
    feedback = json.loads(provider.calls[1]["messages"][-1].content)
    assert feedback["issues"][0]["problem"] == "representative_not_reviewed"
    assert feedback["issues"][0]["representative_customer_ids"] == ["customer-1", "customer-2"]
    assert "customer_journey" in feedback["issues"][0]["instruction"]
    assert result.decisions[0].verdict == "confirmed"


@pytest.mark.parametrize(
    "changes, problem",
    [
        ({"cohort_query_id": "query-small"}, "cohort_not_independent"),
        ({"evidence_query_ids": ["query-small"]}, "evidence_not_independent"),
    ],
)
async def test_verifier_reference_failures_can_be_downgraded(changes, problem):
    decision = {
        "candidate_id": "candidate-1",
        "verdict": "confirmed",
        "reason": "검증 결과",
        "cohort_query_id": "query-full",
        "evidence_query_ids": ["query-full"],
        **changes,
    }
    pending = {**decision, "verdict": "candidate"}
    provider = ScriptedProvider(
        {
            "primary": [
                call("finish", document=json.dumps({"decisions": [decision], "limitations": []})),
                call("finish", document=json.dumps({"decisions": [pending], "limitations": []})),
            ]
        }
    )
    model = GeminiInvestigationModel(
        api_key="test-key",
        primary_model="primary",
        fallback_model="fallback",
        model_factory=provider,
    )
    data = ReferenceData()
    data.journey_reads["task-verifier"] = {"customer-1", "customer-2"}
    result = await model.run_role(
        role="verification",
        task_id="task-verifier",
        instruction="독립 검증",
        context={"candidates": [investigation_candidate()]},
        data=data,
        result_type=Verification,
    )
    assert len(provider.calls) == 2
    feedback = json.loads(provider.calls[1]["messages"][-1].content)
    assert feedback["issues"][0]["problem"] == problem
    assert "candidate" in feedback["issues"][0]["instruction"]
    assert result.decisions[0].verdict == "candidate"


async def test_verifier_cannot_replace_original_representatives_with_different_sample():
    data = ReferenceData()
    data.queries["query-other"] = {
        "owner": "task-verifier",
        "rows": [{"customer_id": "customer-3"}],
    }
    data.journey_reads["task-verifier"] = {"customer-3"}
    document = {
        "decisions": [
            {
                "candidate_id": "candidate-1",
                "verdict": "confirmed",
                "reason": "검증 결과",
                "cohort_query_id": "query-other",
                "evidence_query_ids": ["query-other"],
            }
        ],
        "limitations": [],
    }
    model = GeminiInvestigationModel(
        api_key="test-key", primary_model="primary", fallback_model="fallback"
    )
    feedback = await model._run_tool(
        name="finish",
        arguments={"document": json.dumps(document)},
        data=data,
        result_type=Verification,
        task_id="task-verifier",
        context={"candidates": [investigation_candidate()]},
    )
    assert feedback["issues"][0]["problem"] == "representative_outside_verified_cohort"
    assert feedback["issues"][0]["representative_customer_ids"] == ["customer-1", "customer-2"]


@pytest.mark.parametrize("enabled_flag", ["LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"])
@pytest.mark.parametrize("provider_fails", [False, True])
async def test_invoke_disables_langsmith_restores_global_state_and_keeps_langfuse(
    monkeypatch, enabled_flag, provider_fails
):
    observed = []
    sentinel_handler = object()
    monkeypatch.setattr(
        "customer_signal.observability.langfuse._new_callback_handler", lambda: sentinel_handler
    )

    async def response():
        observed.append(tracing_is_enabled())
        if provider_fails:
            raise RuntimeError("private provider detail")
        return finish()

    provider = ScriptedProvider({"primary": [response]})
    model = GeminiInvestigationModel(
        api_key="test-key",
        primary_model="primary",
        fallback_model="fallback",
        model_factory=provider,
    )
    try:
        with monkeypatch.context() as environment:
            for name in (
                "LANGSMITH_TRACING",
                "LANGSMITH_TRACING_V2",
                "LANGCHAIN_TRACING",
                "LANGCHAIN_TRACING_V2",
            ):
                environment.delenv(name, raising=False)
            environment.setenv(enabled_flag, "true")
            get_env_var.cache_clear()
            assert tracing_is_enabled() is True
            if provider_fails:
                with pytest.raises(GeminiInvestigationError):
                    await run(model)
            else:
                assert isinstance(await run(model), Narrative)
            assert tracing_is_enabled() is True
            assert observed == [False]
            assert provider.calls[0]["config"]["callbacks"] == [sentinel_handler]
    finally:
        get_env_var.cache_clear()
