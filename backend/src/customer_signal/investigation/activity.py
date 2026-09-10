"""Replayable UI activity, projected from execution rather than model transcripts."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from time import monotonic
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

ShortText = Annotated[str, Field(max_length=1000)]
Identifier = Annotated[str, Field(min_length=1, max_length=128)]
Role = Literal["coordinator", "investigator", "verifier", "reporter"]


class PublicContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CandidatePreview(PublicContract):
    candidate_id: Identifier
    title: ShortText
    cohort_query_id: Identifier
    evidence_query_ids: list[Identifier]


class DecisionPreview(PublicContract):
    candidate_id: Identifier
    verdict: Literal["confirmed", "candidate", "rejected", "reinvestigate"]
    reason: ShortText
    cohort_query_id: Identifier | None = None
    evidence_query_ids: list[Identifier] = Field(default_factory=list)
    followup_question: ShortText | None = None


class ActivityDetails(PublicContract):
    """Explicit allowlist: no SQL, raw rows, prompts, provider payloads or customer lists."""

    query_id: Identifier | None = None
    row_count: int | None = Field(default=None, ge=0)
    event_count: int | None = Field(default=None, ge=0)
    customer_count: int | None = Field(default=None, ge=0)
    table_count: int | None = Field(default=None, ge=0)
    truncated: bool | None = None
    measurement_id: Identifier | None = None
    candidate_id: Identifier | None = None
    item_count: int | None = Field(default=None, ge=0)
    tool_count: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    candidates: list[CandidatePreview] = Field(default_factory=list, max_length=6)
    decisions: list[DecisionPreview] = Field(default_factory=list, max_length=18)
    limitations: list[ShortText] = Field(default_factory=list)
    error_code: Identifier | None = None


class AgentActivityPayload(PublicContract):
    schema_version: Literal[1] = 1
    node_id: Identifier
    parent_node_id: Identifier | None = None
    depends_on: list[Identifier] = Field(default_factory=list)
    kind: Literal["agent", "model", "tool", "assessment"]
    role: Role
    task_id: Identifier
    round_index: int = Field(ge=0)
    status: Literal["queued", "started", "completed", "failed", "cancelled"]
    name: Identifier
    display_text: str = Field(min_length=1, max_length=1000)
    occurred_at: AwareDatetime
    duration_ms: int | None = Field(default=None, ge=0)
    model: Identifier | None = None
    details: ActivityDetails = Field(default_factory=ActivityDetails)


_CURRENT: ContextVar[tuple | None] = ContextVar("investigation_activity", default=None)
_LABELS = {
    "coordinator": "조사 배분",
    "investigator": "가설 조사",
    "verifier": "독립 검증",
    "reporter": "보고서 작성",
}
_TOOLS = {
    "catalog_data": "데이터 목록 확인",
    "query_data": "데이터 질의",
    "customer_journey": "대표 여정 조회",
    "find_signals": "기존 패턴 조회",
    "measure_signal": "패턴 지표 측정",
    "propose_signal": "패턴 후보 제안",
    "finish": "역할 결과 제출",
}


class ActivityStream:
    def __init__(self, emit):
        self.emit = emit

    async def publish(self, node, status, *, text=None, details=None, duration_ms=None):
        from customer_signal.agent.contracts import AnalysisEvent

        value = node.model_copy(
            update={
                "status": status,
                "occurred_at": datetime.now(timezone.utc),
                "display_text": text or node.display_text,
                "duration_ms": duration_ms,
                "details": details or ActivityDetails(),
            }
        )
        await self.emit(AnalysisEvent(type="agent_activity", payload=value.model_dump(mode="json")))

    async def agent(self, role, task_id, round_index, depends_on, text=None):
        node = AgentActivityPayload(
            node_id=f"agent-{uuid4().hex}",
            depends_on=depends_on,
            kind="agent",
            role=role,
            task_id=task_id,
            round_index=round_index,
            status="queued",
            name=role,
            display_text=text or _LABELS[role],
            occurred_at=datetime.now(timezone.utc),
        )
        await self.publish(node, "queued")
        return node

    @contextmanager
    def bind(self, node):
        token = _CURRENT.set((self, node))
        try:
            yield
        finally:
            _CURRENT.reset(token)

    async def assessment(self, node, decisions):
        value = node.model_copy(
            update={
                "node_id": f"assessment-{uuid4().hex}",
                "parent_node_id": node.node_id,
                "depends_on": [node.node_id],
                "kind": "assessment",
                "name": "verification_policy",
            }
        )
        await self.publish(
            value,
            "completed",
            text="서버의 근거 검사를 반영한 후보별 판정입니다.",
            details=ActivityDetails(
                decisions=[DecisionPreview.model_validate(d.model_dump()) for d in decisions]
            ),
        )


class Operation:
    def __init__(self):
        self.details = ActivityDetails()
        self.failed = False


@asynccontextmanager
async def operation(kind, name, *, model=None):
    """Context stays local to each asyncio task; cancellation always closes an open node."""
    result = Operation()
    current = _CURRENT.get()
    if current is None:
        yield result
        return
    stream, parent = current
    node = parent.model_copy(
        update={
            "node_id": f"{kind}-{uuid4().hex}",
            "parent_node_id": parent.node_id,
            "depends_on": [],
            "kind": kind,
            "name": name,
            "model": model,
            "display_text": _TOOLS.get(name, "모델 응답 생성"),
        }
    )
    started = monotonic()
    await stream.publish(node, "started")
    status = "completed"
    try:
        yield result
        if result.failed:
            status = "failed"
    except asyncio.CancelledError:
        status = "cancelled"
        raise
    except Exception:
        status = "failed"
        result.details = ActivityDetails(error_code=f"{kind}_failed")
        raise
    finally:
        await stream.publish(
            node, status, details=result.details, duration_ms=int((monotonic() - started) * 1000)
        )


def tool_details(name, output):
    if isinstance(output, BaseModel):
        return ActivityDetails()
    if "error" in output:
        # Only server-created fixed error codes, never exception messages or repair drafts.
        codes = {
            "unknown_tool",
            "validation_failed",
            "result_reference_invalid",
            "query_failed",
            "data_tool_failed",
        }
        return ActivityDetails(
            error_code=output["error"] if output["error"] in codes else "tool_failed"
        )
    keys = (
        "query_id",
        "row_count",
        "event_count",
        "customer_count",
        "truncated",
        "measurement_id",
        "candidate_id",
    )
    details = {k: output[k] for k in keys if k in output}
    if name == "catalog_data":
        details["table_count"] = len(output.get("tables", []))
    if name == "customer_journey":
        details["event_count"] = len(output.get("events", []))
    if name == "find_signals":
        details["item_count"] = len(output.get("items", []))
    return ActivityDetails.model_validate(details)


def role_details(result):
    from customer_signal.investigation.contracts import InvestigationResult

    details = ActivityDetails(limitations=getattr(result, "limitations", []))
    if isinstance(result, InvestigationResult):
        details.candidates = [
            CandidatePreview(
                candidate_id=c.candidate_id,
                title=c.title,
                cohort_query_id=c.cohort_query_id,
                evidence_query_ids=c.evidence_query_ids,
            )
            for c in result.candidates
        ]
    # Verifier model verdicts are intentionally omitted: assessment publishes checked decisions.
    return details
