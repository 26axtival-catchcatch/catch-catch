import asyncio
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from customer_signal.agent.contracts import RunRequest
from customer_signal.investigation.runner import InvestigationRunner
from customer_signal.investigation.data import query_owner
from test_investigation_runner import ScriptedModel, make_data


REQUEST = RunRequest(
    question="헤맨 고객",
    start_at="2026-09-04T00:00:00Z",
    end_at="2026-09-11T00:00:00Z",
    enabled_sources=["app"],
)


class SplitModel(ScriptedModel):
    def __init__(self, *, fail=None, followup=False):
        super().__init__()
        self.active = self.peak = 0
        self.verifications = []
        self.fail = fail
        self.followup = followup

    async def run_role(self, **kw):
        if kw["role"] == "verifier":
            assert len(kw["context"]["candidates"]) == 1
            candidate = kw["context"]["candidates"][0]
            cid = candidate["candidate_id"]
            self.verifications.append((cid, kw["round_index"], kw["task_id"]))
            assert query_owner.get() == kw["task_id"]
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                await asyncio.sleep(0.02)
                if cid == self.fail:
                    raise RuntimeError("synthetic task failure")
                q = kw["data"].query("SELECT DISTINCT customer_id FROM events")
                kw["data"].journey(candidate["representative_customer_ids"][0])
                decision = {
                    "candidate_id": cid,
                    "verdict": "confirmed",
                    "reason": "직접 확인",
                    "cohort_query_id": q["query_id"],
                    "evidence_query_ids": [q["query_id"]],
                }
                if self.followup and cid == "pattern-0" and kw["round_index"] == 0:
                    decision.update(verdict="reinvestigate", followup_question="해결 확인")
                return kw["result_type"].model_validate(
                    {"decisions": [decision], "limitations": []}
                )
            finally:
                self.active -= 1
        result = await super().run_role(**kw)
        if kw["role"] == "investigator":
            if kw["round_index"]:
                assert len(kw["context"]["prior_candidates"]) == 1
                cid = kw["context"]["prior_candidates"][0]["candidate_id"]
                return result.model_copy(
                    update={
                        "candidates": [
                            result.candidates[0].model_copy(update={"candidate_id": cid})
                        ]
                    }
                )
            return result.model_copy(
                update={
                    "candidates": [
                        result.candidates[0].model_copy(update={"candidate_id": f"pattern-{i}"})
                        for i in range(6)
                    ]
                }
            )
        return result


async def execute(model, tmp_path):
    async def emit(e):
        pass

    return await InvestigationRunner(
        model=model, data_factory=make_data, artifact_directory=tmp_path
    ).run(REQUEST, emit=emit)


async def test_verifiers_receive_one_candidate_and_run_with_bounded_concurrency(tmp_path):
    model = SplitModel()
    outcome = await execute(model, tmp_path)
    assert outcome.status == "completed"
    assert len(outcome.report.findings) == 6
    assert model.peak == 6
    assert len({task for _, _, task in model.verifications}) == 6
    assert outcome.report.metrics[0].value == 1  # overlapping cohorts still deduplicate


async def test_failed_verifier_does_not_discard_confirmed_siblings(tmp_path):
    outcome = await execute(SplitModel(fail="pattern-2"), tmp_path)
    assert len(outcome.report.findings) == 5
    assert outcome.report.metrics[1].value == 1
    assert any("pattern-2" in x for x in outcome.limitations)


async def test_followup_only_rechecks_changed_candidate(tmp_path):
    model = SplitModel(followup=True)
    outcome = await execute(model, tmp_path)
    assert len(outcome.report.findings) == 6
    assert [(cid, r) for cid, r, _ in model.verifications if r] == [("pattern-0", 1)]


def test_query_page_recovers_rows_without_granting_query_ownership():
    data = make_data(REQUEST)
    try:
        owner = query_owner.set("task-investigator")
        q = data.query("SELECT range AS n FROM range(150)")
        query_owner.reset(owner)
        owner = query_owner.set("task-verifier")
        try:
            page = data.read_query_result(q["query_id"], offset=100, limit=20)
            assert page["rows"] == [{"n": n} for n in range(100, 120)]
            assert page["next_offset"] == 120
            assert data.queries[q["query_id"]]["owner"] == "task-investigator"
            with pytest.raises(ValueError):
                data.read_query_result("unknown")
        finally:
            query_owner.reset(owner)
    finally:
        data.close()


async def test_verifier_query_tool_returns_only_credited_preview_rows():
    from customer_signal.investigation.contracts import Verification
    from customer_signal.investigation.model import GeminiInvestigationModel

    data = make_data(REQUEST)
    try:
        model = GeminiInvestigationModel(
            api_key="test", primary_model="test", fallback_model="test"
        )
        output = await model._run_tool(
            name="query_data",
            arguments={"sql": "SELECT range AS n FROM range(150)"},
            data=data,
            result_type=Verification,
            task_id="task-verifier",
        )
        assert output["rows"] == [{"n": n} for n in range(20)]
        assert output["truncated"] is True
        assert len(data.queries[output["query_id"]]["rows"]) == 150
    finally:
        data.close()


async def test_verifier_must_receive_tool_batch_before_finishing():
    from customer_signal.investigation.contracts import Verification
    from customer_signal.investigation.model import GeminiInvestigationModel
    from test_investigation_model import (
        ReferenceData,
        ScriptedProvider,
        call,
        investigation_candidate,
    )
    from test_investigation_model import query_owner as reference_owner

    document = json.dumps(
        {
            "decisions": [
                {
                    "candidate_id": "candidate-1",
                    "verdict": "confirmed",
                    "reason": "검증 완료",
                    "cohort_query_id": "query-full",
                    "evidence_query_ids": ["query-full"],
                }
            ],
            "limitations": [],
        }
    )
    batch = AIMessage(
        content="",
        tool_calls=[
            {"name": "customer_journey", "args": {"customer_id": "customer-1"}, "id": "one"},
            {"name": "customer_journey", "args": {"customer_id": "customer-2"}, "id": "two"},
            {"name": "finish", "args": {"document": document}, "id": "finish"},
        ],
    )
    provider = ScriptedProvider({"test": [batch, call("finish", document=document)]})
    model = GeminiInvestigationModel(
        api_key="test", primary_model="test", fallback_model="test", model_factory=provider
    )
    token = reference_owner.set("task-verifier")
    try:
        result = await model.run_role(
            role="verifier",
            task_id="task-verifier",
            instruction="검증",
            context={"candidates": [investigation_candidate()]},
            data=ReferenceData(),
            result_type=Verification,
        )
    finally:
        reference_owner.reset(token)
    assert result.decisions[0].verdict == "confirmed"
    assert len(provider.calls) == 2
    assert (
        json.loads(provider.calls[1]["messages"][-1].content)["error"]
        == "finish_requires_separate_turn"
    )


def test_journey_review_credits_only_delivered_rows_and_owned_pages():
    data = make_data(REQUEST)
    try:
        customer_id = sorted(data.customer_ids)[0]
        token = query_owner.set("task-verifier")
        try:
            # The actual customer appears beyond the five-row verifier preview.
            q = data.query(
                "SELECT 'event-' || range AS event_id, "
                f"CASE WHEN range = 5 THEN '{customer_id}' ELSE 'unknown' END AS customer_id, "
                "'2026-09-05' AS occurred_at, 'view' AS action FROM range(6) ORDER BY range",
                preview_limit=5,
            )
            assert len(q["rows"]) == 5
            assert customer_id not in data.journey_reads.get("task-verifier", set())
            other = query_owner.set("task-other-verifier")
            try:
                data.read_query_result(q["query_id"], offset=5, limit=1)
                assert not data.journey_reads.get("task-other-verifier")
            finally:
                query_owner.reset(other)
            page = data.read_query_result(q["query_id"], offset=5, limit=1)
            assert page["rows"][0]["customer_id"] == customer_id
            assert customer_id in data.journey_reads["task-verifier"]
        finally:
            query_owner.reset(token)
    finally:
        data.close()


def test_reusable_cohort_table_is_complete_and_scoped_to_its_verifier(tmp_path):
    from customer_signal.signals.contracts import SignalDefinition
    from customer_signal.signals.store import SignalStore
    from customer_signal.signals.workbench import SignalWorkbench

    data = make_data(REQUEST)
    try:
        token = query_owner.set("verifier-one")
        try:
            q = data.query("SELECT DISTINCT customer_id FROM events", expose_cohort=True)
            table = q["cohort_table"]
            result = data.query(
                f'SELECT count(*) AS n FROM events JOIN "{table}" USING (customer_id)'
            )
            assert result["rows"] == [{"n": 2}]
            assert data.queries[result["query_id"]]["owner"] == "verifier-one"
            other = query_owner.set("verifier-two")
            try:
                # Case or CTE aliases must not bypass the ownership boundary.
                for sql in [
                    f'SELECT * FROM "{table}"',
                    f'SELECT * FROM "{table.upper()}"',
                    f'WITH c AS (SELECT * FROM "{table}") SELECT * FROM c',
                    f'SELECT * FROM temp.main."{table}"',
                ]:
                    with pytest.raises(ValueError, match="another task"):
                        data.query(sql)
                with pytest.raises(ValueError):
                    data.query(f"SELECT * FROM \"query_table\"('{table}')")
                for macro in ("histogram", "histogram_values"):
                    with pytest.raises(ValueError, match="table function"):
                        data.query(f"SELECT * FROM {macro}('{table}', customer_id)")
                assert data.query(f"SELECT '{table}' AS label")["rows"] == [{"label": table}]
            finally:
                query_owner.reset(other)
            with pytest.raises(ValueError):
                data.query(f'DROP TABLE "{table}"')
            plain = data.query("SELECT DISTINCT customer_id FROM events")
            assert "cohort_table" not in plain
            wb = SignalWorkbench(
                data=data, store=SignalStore(tmp_path / "signals.sqlite3"), run_id="test"
            )
            measurement = wb.measure(
                SignalDefinition(
                    source_ids=["app"],
                    cohort_sql=f'SELECT customer_id FROM "{table}"',
                    population_description="전체",
                    normal_comparison="성공과 비교",
                )
            )
            assert measurement["status"] != "success"
        finally:
            query_owner.reset(token)
    finally:
        data.close()


def test_context_compacts_old_rows_and_keeps_reference_and_recent_evidence():
    from customer_signal.investigation.verification import bound_messages, message_bytes

    messages = [SystemMessage(content="system"), HumanMessage(content="assignment")]
    for i in range(8):
        messages += [
            AIMessage(
                content="public narration" * 100,
                tool_calls=[
                    {
                        "name": "query_data",
                        "args": {"sql": "SELECT * FROM events"},
                        "id": f"call-{i}",
                    }
                ],
            ),
            ToolMessage(
                content=json.dumps(
                    {
                        "query_id": f"query-{i}",
                        "row_count": 100,
                        "rows": [{"text": str(i) * 2000} for _ in range(10)],
                    }
                ),
                tool_call_id=f"call-{i}",
                name="query_data",
            ),
        ]
    bounded = bound_messages(messages, budget=50000)
    assert message_bytes(bounded) <= 50000
    assert "query-0" in "\n".join(str(m.content) for m in bounded)
    assert "777777777" in bounded[-1].content
    assert len(bounded) == len(messages)  # no orphan tool calls
    assert len(messages[3].content) > 10000  # original trace content unchanged


def test_context_limit_fails_closed_instead_of_truncating_assignment():
    from customer_signal.investigation.verification import bound_messages, VerificationContextLimit

    with pytest.raises(VerificationContextLimit):
        bound_messages([SystemMessage(content="x" * 1000)], budget=100)


def test_context_limit_preserves_all_undelivered_tool_results_in_current_batch():
    from customer_signal.investigation.verification import bound_messages, VerificationContextLimit

    messages = [
        SystemMessage(content="system"),
        HumanMessage(content="assignment"),
        AIMessage(
            content="",
            tool_calls=[{"name": "customer_journey", "args": {}, "id": str(i)} for i in range(3)],
        ),
    ]
    messages.extend(
        ToolMessage(
            content=json.dumps({"customer_id": str(i), "events": [{"text": "x" * 40000}]}),
            tool_call_id=str(i),
            name="customer_journey",
        )
        for i in range(3)
    )
    with pytest.raises(VerificationContextLimit):
        bound_messages(messages)


def test_archiving_completed_batches_removes_sql_arguments_but_keeps_references():
    from customer_signal.investigation.verification import bound_messages, message_bytes

    messages = [SystemMessage(content="system"), HumanMessage(content="assignment")]
    for i in range(5):
        messages += [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "query_data", "args": {"sql": "SELECT " + "x" * 15000}, "id": str(i)}
                ],
            ),
            ToolMessage(
                content=json.dumps(
                    {"query_id": f"query-{i}", "rows": [], "row_count": 0, "owner": "task-verifier"}
                ),
                tool_call_id=str(i),
            ),
        ]
    bounded = bound_messages(messages, budget=25000)
    assert message_bytes(bounded) <= 25000
    assert bounded[:2] == messages[:2]
    assert bounded[-2:] == messages[-2:]
    archive = json.dumps([m.content for m in bounded])
    assert all(f"query-{i}" in archive for i in range(5))
    calls = {c["id"] for m in bounded if isinstance(m, AIMessage) for c in m.tool_calls}
    assert calls == {m.tool_call_id for m in bounded if isinstance(m, ToolMessage)}


def test_compaction_keeps_small_aggregate_facts_to_avoid_requery_loops():
    from customer_signal.investigation.verification import bound_messages

    messages = [SystemMessage(content="system"), HumanMessage(content="assignment")]
    for i in range(5):
        messages += [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "query_data", "args": {"sql": "SELECT " + "x" * 15000}, "id": str(i)}
                ],
            ),
            ToolMessage(
                content=json.dumps(
                    {
                        "query_id": f"query-{i}",
                        "row_count": 1,
                        "columns": ["normal_customers", "negative_feedback"],
                        "owner": "task-verifier",
                        "rows": [{"normal_customers": 84, "negative_feedback": 84}],
                    }
                ),
                tool_call_id=str(i),
            ),
        ]
    bounded = bound_messages(messages, budget=25000)
    archived = json.loads(bounded[2].content)["archived_observations"]
    assert archived[0]["rows"] == [{"normal_customers": 84, "negative_feedback": 84}]
    assert archived[0]["columns"] == ["normal_customers", "negative_feedback"]


def test_bundled_recheck_executes_owned_evidence_without_automatic_confirmation(tmp_path):
    from customer_signal.investigation.verification import recheck_candidate
    from customer_signal.signals.contracts import SignalDefinition
    from customer_signal.signals.store import SignalStore
    from customer_signal.signals.workbench import SignalWorkbench

    data = make_data(REQUEST)
    wb = SignalWorkbench(data=data, store=SignalStore(tmp_path / "signals.sqlite3"), run_id="test")
    data.signal_workbench = wb
    try:
        q = data.query("SELECT DISTINCT customer_id FROM events")
        definition = SignalDefinition(
            source_ids=["app"],
            cohort_sql=q["sql"],
            population_description="전체",
            normal_comparison="완료와 비교",
        )
        wb.propose("assigned", wb.measure(definition)["measurement_id"])
        context = {
            "candidates": [
                {
                    "candidate_id": "assigned",
                    "cohort_query_id": q["query_id"],
                    "evidence_query_ids": [q["query_id"]],
                    "representative_customer_ids": sorted(data.customer_ids),
                }
            ]
        }
        token = query_owner.set("task-verifier")
        try:
            result = recheck_candidate(data, context)
            assert "verdict" not in result
            assert result["cohort"]["query_id"] != q["query_id"]
            assert result["cohort"]["owner"] == "task-verifier"
            assert result["evidence"][0]["query_id"] == result["cohort"]["query_id"]
            assert result["measurement"]["status"] == "success"
            assert "queries" not in result["measurement"]
            assert {j["customer_id"] for j in result["journeys"]} == data.journey_reads[
                "task-verifier"
            ]

            # A later measurement failure must still deliver the already credited journeys.
            def fail_measure(_):
                raise ValueError("private error")

            wb.measure = fail_measure
            failed_owner = query_owner.set("task-failed-verifier")
            try:
                partial = recheck_candidate(data, context)
            finally:
                query_owner.reset(failed_owner)
            assert partial["measurement"]["error"] == "measurement_failed"
            assert partial["journeys"] == result["journeys"]
            assert "private" not in json.dumps(partial, default=str)
            from customer_signal.investigation.contracts import Decision

            decision = Decision(
                candidate_id="assigned",
                verdict="confirmed",
                reason="검증",
                cohort_query_id=partial["cohort"]["query_id"],
                evidence_query_ids=[partial["cohort"]["query_id"]],
            )
            assert wb.verified_measurement(decision, "task-failed-verifier") is None
            with pytest.raises(ValueError):
                recheck_candidate(data, {"candidates": context["candidates"] * 2})
        finally:
            query_owner.reset(token)
    finally:
        data.close()


def test_verifier_model_has_independent_override():
    from customer_signal.investigation.model import BedrockInvestigationModel

    model = BedrockInvestigationModel(
        api_key="test", model="opus", investigator_model="sonnet", verifier_model="haiku"
    )
    assert model._model_for_role("verifier") == "haiku"
    assert model._model_for_role("investigator") == "sonnet"
    assert model._model_for_role("reporter") == "opus"


async def test_verifier_cannot_confirm_using_sibling_evidence(tmp_path):
    class SiblingEvidence(SplitModel):
        async def run_role(self, **kw):
            result = await super().run_role(**kw)
            if kw["role"] == "verifier":
                # A readable query with a different owner must never count as independent.
                token = query_owner.set("task-other-verifier")
                try:
                    q = kw["data"].query("SELECT DISTINCT customer_id FROM events")
                finally:
                    query_owner.reset(token)
                result = result.model_copy(
                    update={
                        "decisions": [
                            d.model_copy(update={"evidence_query_ids": [q["query_id"]]})
                            for d in result.decisions
                        ]
                    }
                )
            return result

    outcome = await execute(SiblingEvidence(), tmp_path)
    assert not outcome.report.findings
    assert outcome.report.metrics[1].value == 1


async def test_completed_verification_survives_global_deadline(tmp_path):
    class SlowVerifier(SplitModel):
        async def run_role(self, **kw):
            if (
                kw["role"] == "verifier"
                and kw["context"]["candidates"][0]["candidate_id"] == "pattern-2"
            ):
                await asyncio.sleep(2)
            return await super().run_role(**kw)

    async def emit(e):
        pass

    outcome = await InvestigationRunner(
        model=SlowVerifier(),
        data_factory=make_data,
        artifact_directory=tmp_path,
        investigation_seconds=0.3,
    ).run(REQUEST, emit=emit)
    assert len(outcome.report.findings) == 5
    assert outcome.report.metrics[1].value == 1


def test_signal_context_contains_only_assigned_definition_and_compact_measurement(tmp_path):
    from customer_signal.signals.workbench import SignalWorkbench
    from customer_signal.signals.store import SignalStore
    from customer_signal.signals.contracts import SignalDefinition

    data = make_data(REQUEST)
    wb = SignalWorkbench(data=data, store=SignalStore(tmp_path / "signals.sqlite3"), run_id="test")
    try:
        definition = SignalDefinition(
            source_ids=["app"],
            cohort_sql="SELECT customer_id FROM events",
            population_description="전체",
            normal_comparison="성공과 비교",
        )
        m = wb.measure(definition)
        wb.propose("assigned", m["measurement_id"])
        wb.propose("unrelated", m["measurement_id"])
        context = wb.context(candidate_ids={"assigned"}, compact=True)
        assert [x["candidate_id"] for x in context] == ["assigned"]
        assert "queries" not in context[0]["measurement"]
        assert context[0]["measurement"]["values"] == m["values"]
        assert context[0]["definition"] == definition.model_dump(mode="json")
    finally:
        data.close()
