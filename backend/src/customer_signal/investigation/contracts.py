"""Public contracts exchanged by the investigation roles."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


ShortId = Annotated[str, Field(min_length=1, max_length=80)]
Limitation = Annotated[str, Field(min_length=1, max_length=1000)]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _RoleResult(_Contract):
    display_summary: str | None = Field(default=None, min_length=1, max_length=500)


class Task(_Contract):
    task_id: str = Field(pattern=r"^task-[a-z0-9-]+$", max_length=80)
    question: str = Field(min_length=1, max_length=1000)


class Coordination(_RoleResult):
    tasks: list[Task] = Field(min_length=1, max_length=3)
    summary: str = Field(min_length=1, max_length=1000)


class Candidate(_Contract):
    candidate_id: ShortId
    title: str = Field(min_length=1, max_length=180)
    intent: str = Field(min_length=1, max_length=500)
    cohort_query_id: ShortId
    evidence_query_ids: list[ShortId]
    representative_customer_ids: list[ShortId] = Field(min_length=1, max_length=2)
    behavior_evidence: str = Field(min_length=1, max_length=1000)
    normal_comparison: str = Field(min_length=1, max_length=1000)
    resolution: str = Field(min_length=1, max_length=500)
    recommendation: str = Field(min_length=1, max_length=500)
    limitations: list[Limitation] = Field(default_factory=list)


class InvestigationResult(_RoleResult):
    candidates: list[Candidate] = Field(max_length=6)
    limitations: list[Limitation]


class Decision(_Contract):
    candidate_id: ShortId
    verdict: Literal["confirmed", "candidate", "rejected", "reinvestigate"]
    reason: str = Field(min_length=1, max_length=1000)
    cohort_query_id: ShortId | None = None
    evidence_query_ids: list[ShortId] = Field(default_factory=list)
    followup_question: str | None = Field(default=None, max_length=1000)


class Verification(_RoleResult):
    decisions: list[Decision] = Field(max_length=18)
    limitations: list[Limitation]


class Narrative(_RoleResult):
    headline: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=2000)
