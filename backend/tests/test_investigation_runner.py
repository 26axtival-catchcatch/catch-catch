from pathlib import Path
import asyncio

from customer_signal.agent.contracts import RunRequest
from customer_signal.investigation.data import InvestigationData
from customer_signal.investigation.runner import InvestigationRunner
from customer_signal.runtime.events import GENERIC_EVENT_ADAPTER
from test_investigation_data import event


class ScriptedModel:
    model_name = "scripted-gemini"

    async def classify_input(self, request):
        return {"action": "proceed", "reason": "supported", "question": "",
                "analysis_question": request.question}

    def __init__(self):
        self.calls = []
        self.query_id = None

    async def run_role(
        self, *, role, task_id, instruction, context, data, result_type, round_index=0
    ):
        self.calls.append((role, round_index))
        if role == "coordinator":
            output = {
                "tasks": [{"task_id": "task-search", "question": "탐색과 정상 이용 비교"}],
                "summary": "여정을 조사합니다.",
            }
        elif role == "investigator":
            q = data.query("SELECT DISTINCT customer_id FROM events")
            self.query_id = q["query_id"]
            output = {
                "candidates": [
                    {
                        "candidate_id": "search-loop",
                        "title": "반복 탐색",
                        "intent": "서비스 찾기",
                        "cohort_query_id": self.query_id,
                        "evidence_query_ids": [self.query_id],
                        "representative_customer_ids": data.cohort(self.query_id)[:1],
                        "behavior_evidence": "반복 뒤 문의",
                        "normal_comparison": "정상 완료와 비교",
                        "resolution": "문의로 해결",
                        "recommendation": "메뉴 진입점을 개선합니다.",
                    }
                ],
                "limitations": [],
            }
        elif role == "verifier":
            q = data.query("SELECT DISTINCT customer_id FROM events")
            data.journey(data.cohort(q["query_id"])[0])
            output = {
                "decisions": [
                    {
                        "candidate_id": "search-loop",
                        "verdict": "reinvestigate" if round_index == 0 else "confirmed",
                        "reason": "정상 탐색 반례를 추가 확인했습니다.",
                        "cohort_query_id": q["query_id"],
                        "evidence_query_ids": [q["query_id"]],
                        "followup_question": "최종 해결을 확인하세요.",
                    }
                ],
                "limitations": [],
            }
        else:
            output = {
                "headline": "반복 탐색 고객 조사",
                "summary": "최종 해결 전 반복 탐색을 확인했습니다.",
            }
        return result_type.model_validate(output)


def make_data(request):
    return InvestigationData(
        request=request, events=[event(1), event(2)], manifests=[], snapshot_id="test"
    )


async def test_reinvestigation_keeps_existing_wire_report_and_evidence(tmp_path):
    model = ScriptedModel()
    request = RunRequest(
        question="헤맨 고객",
        start_at="2026-09-04T00:00:00Z",
        end_at="2026-09-11T00:00:00Z",
        enabled_sources=["app"],
    )
    runner = InvestigationRunner(model=model, data_factory=make_data, artifact_directory=tmp_path)
    events = []

    async def emit(e):
        events.append(e)

    outcome = await runner.run(request, emit=emit)
    assert outcome.status == "completed"
    assert model.calls == [
        ("coordinator", 0),
        ("investigator", 0),
        ("verifier", 0),
        ("investigator", 1),
        ("verifier", 1),
        ("reporter", 0),
    ]
    assert outcome.report.report_kind == "customer_signal"
    assert len(outcome.report.findings) == 1
    assert outcome.report.findings[0].claim.target == 1
    assert any(f.primitive == "get_customer_journey" for f in outcome.facts)
    assert any(f.primitive == "get_evidence" for f in outcome.facts)
    assert events[-1].type == "result"
    for emitted in events:
        GENERIC_EVENT_ADAPTER.validate_json(emitted.model_dump_json())
    assert list(Path(tmp_path).glob("investigations/*.json"))


async def test_unverified_candidates_are_not_published_as_findings(tmp_path):
    class PendingModel(ScriptedModel):
        async def run_role(self, **kwargs):
            result = await super().run_role(**kwargs)
            if kwargs["role"] == "verifier":
                return result.model_copy(
                    update={
                        "decisions": [
                            d.model_copy(update={"verdict": "candidate"}) for d in result.decisions
                        ]
                    }
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
        model=PendingModel(), data_factory=make_data, artifact_directory=tmp_path
    ).run(request, emit=emit)
    assert outcome.status == "completed" and not outcome.report.findings
    assert any("미확정" in text for text in outcome.report.limitations)


async def test_finished_investigator_survives_sibling_timeout(tmp_path):
    class SlowSibling(ScriptedModel):
        async def run_role(self, **kwargs):
            if kwargs["task_id"] == "task-slow":
                await asyncio.sleep(3)
            result = await super().run_role(**kwargs)
            if kwargs["role"] == "coordinator":
                task = result.tasks[0].model_copy(update={"task_id": "task-slow"})
                return result.model_copy(update={"tasks": [*result.tasks, task]})
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
        model=SlowSibling(),
        data_factory=make_data,
        artifact_directory=tmp_path,
        investigation_seconds=1,
        total_seconds=7,
    ).run(request, emit=emit)
    assert outcome.status == "completed"
    assert outcome.report.metrics[1].value == 1
    assert any("시간 한계" in value for value in outcome.limitations)


async def test_reporter_timeout_retains_verified_findings(tmp_path):
    class SlowReporter(ScriptedModel):
        async def run_role(self, **kwargs):
            if kwargs["role"] == "reporter":
                await asyncio.sleep(3)
            return await super().run_role(**kwargs)

    request = RunRequest(
        question="헤맨 고객",
        start_at="2026-09-04T00:00:00Z",
        end_at="2026-09-11T00:00:00Z",
        enabled_sources=["app"],
    )

    async def emit(e):
        pass

    outcome = await InvestigationRunner(
        model=SlowReporter(), data_factory=make_data, artifact_directory=tmp_path, total_seconds=6
    ).run(request, emit=emit)
    assert outcome.status == "completed" and len(outcome.report.findings) == 1
    assert any("보고 요약" in value for value in outcome.limitations)


async def test_verifier_cannot_reuse_investigator_queries_as_own_evidence(tmp_path):
    class ReusedEvidence(ScriptedModel):
        async def run_role(self, **kwargs):
            result = await super().run_role(**kwargs)
            if kwargs["role"] == "verifier":
                decisions = [
                    d.model_copy(
                        update={"verdict": "confirmed", "evidence_query_ids": [self.query_id]}
                    )
                    for d in result.decisions
                ]
                return result.model_copy(update={"decisions": decisions})
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
        model=ReusedEvidence(), data_factory=make_data, artifact_directory=tmp_path
    ).run(request, emit=emit)
    assert outcome.status == "completed" and not outcome.report.findings
    assert any("직접 질의 근거" in value for value in outcome.limitations)


async def test_overlapping_patterns_reuse_public_journey_and_evidence(tmp_path):
    class Overlap(ScriptedModel):
        async def run_role(self, **kwargs):
            result = await super().run_role(**kwargs)
            if kwargs["role"] == "investigator":
                second = result.candidates[0].model_copy(
                    update={"candidate_id": "overlapping-pattern"}
                )
                result = result.model_copy(update={"candidates": [*result.candidates, second]})
            elif kwargs["role"] == "verifier":
                first = result.decisions[0].model_copy(update={"verdict": "confirmed"})
                second = first.model_copy(update={"candidate_id": "overlapping-pattern"})
                result = result.model_copy(update={"decisions": [first, second]})
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
        model=Overlap(), data_factory=make_data, artifact_directory=tmp_path
    ).run(request, emit=emit)
    assert outcome.status == "completed"
    assert len(outcome.report.findings) == 2
    assert all(finding.evidence_ids for finding in outcome.report.findings)
    assert sum(f.primitive == "get_customer_journey" for f in outcome.facts) == 1
    assert outcome.report.metrics[0].value == 1


async def test_reinvestigation_continues_until_verifier_finishes_without_round_cap(tmp_path):
    class MoreRounds(ScriptedModel):
        async def run_role(self, **kwargs):
            result = await super().run_role(**kwargs)
            if kwargs["role"] == "verifier" and kwargs.get("round_index", 0) < 3:
                result = result.model_copy(update={"decisions": [
                    d.model_copy(update={"verdict": "reinvestigate"})
                    for d in result.decisions
                ]})
            return result

    model = MoreRounds()
    request = RunRequest(question="헤맨 고객", start_at="2026-09-04T00:00:00Z",
        end_at="2026-09-11T00:00:00Z", enabled_sources=["app"])
    runner = InvestigationRunner(model=model, data_factory=make_data, artifact_directory=tmp_path)
    async def emit(e):
        pass
    outcome = await runner.run(request, emit=emit)
    assert outcome.status == "completed"
    assert ("verifier", 3) in model.calls
    assert len(outcome.report.findings) == 1
    assert runner.total_seconds is None and runner.investigation_seconds is None
