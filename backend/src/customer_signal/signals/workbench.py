"""Run-local measured proposals; only independent confirmations become durable."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field

from customer_signal.investigation.data import query_owner
from customer_signal.observability.langfuse import (
    LangfuseRunContext,
    current_run_id,
    signal_observation,
)
from customer_signal.signals.contracts import Proposal, SignalDefinition
from customer_signal.signals.measurement import definition_fingerprint, measure_definition


class MeasureArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    definition: SignalDefinition


class ProposeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str = Field(min_length=1, max_length=80)
    measurement_id: str = Field(min_length=1, max_length=80)


class SignalWorkbench:
    def __init__(self, *, data, store, run_id: str):
        self.data = data
        self.store = store
        self.run_id = run_id
        self.measurements = {}
        self.proposals = {}

    def find(self) -> dict:
        return {"items": [s.model_dump(mode="json") for s in self.store.list_signals()]}

    def measure(self, definition: SignalDefinition) -> dict:
        result = measure_definition(self.data, definition)
        if run_id := current_run_id():
            result = result.model_copy(update={"trace_id": run_id.replace("-", "")})
        self.measurements[result.measurement_id] = (query_owner.get(), definition, result)
        return result.model_dump(mode="json")

    def propose(self, candidate_id: str, measurement_id: str) -> dict:
        item = self.measurements.get(measurement_id)
        if item is None or item[0] != query_owner.get() or item[2].status != "success":
            raise ValueError("a successful measurement executed by this task is required")
        if query_owner.get() in {"task-reporting", "task-coordination"}:
            raise ValueError("only investigator and verifier may propose")
        self.proposals[candidate_id] = item[1]
        return {
            "candidate_id": candidate_id,
            "measurement_id": measurement_id,
            "status": "proposed",
            "instruction": "User selection is required for registration.",
        }

    def context(self) -> list[dict]:
        items = []
        for cid, definition in self.proposals.items():
            fingerprint = definition_fingerprint(definition)
            measurement = next(
                (
                    m
                    for _, _, m in reversed(list(self.measurements.values()))
                    if m.definition_fingerprint == fingerprint and m.status == "success"
                ),
                None,
            )
            items.append(
                {
                    "candidate_id": cid,
                    "definition": definition.model_dump(mode="json"),
                    "measurement": measurement.model_dump(mode="json") if measurement else None,
                }
            )
        return items

    def verified_measurement(self, decision, owner: str):
        definition = self.proposals.get(decision.candidate_id)
        if definition is None or decision.verdict != "confirmed":
            return None
        try:
            cohort = set(self.data.cohort(decision.cohort_query_id))
        except (ValueError, TypeError):
            return None
        fingerprint = definition_fingerprint(definition)
        for task, _, measurement in reversed(list(self.measurements.values())):
            if (
                task == owner
                and measurement.status == "success"
                and measurement.definition_fingerprint == fingerprint
                and set(measurement.cohort_customer_ids) == cohort
            ):
                return measurement
        return None

    def persist(self, candidates, decisions) -> list[Proposal]:
        saved = []
        summaries = []
        by_id = {d.candidate_id: d for d in decisions}
        with signal_observation(
            operation="collection", input={"run_id": self.run_id}
        ) as collection:
            for candidate in candidates:
                decision = by_id.get(candidate.candidate_id)
                definition = self.proposals.get(candidate.candidate_id)
                task_id = self.data.queries.get(candidate.cohort_query_id, {}).get("owner")
                measurement = None
                if decision is not None:
                    verifier = self.data.queries.get(decision.cohort_query_id, {}).get("owner")
                    if verifier and verifier != task_id:
                        measurement = self.verified_measurement(decision, verifier)
                latest_measurement = measurement
                if latest_measurement is None and definition is not None:
                    fingerprint = definition_fingerprint(definition)
                    latest_measurement = next(
                        (
                            m
                            for _, _, m in reversed(list(self.measurements.values()))
                            if m.definition_fingerprint == fingerprint
                        ),
                        None,
                    )
                proposal_id = (
                    str(uuid5(NAMESPACE_URL, f"signal:{self.run_id}:{candidate.candidate_id}"))
                    if measurement is not None
                    else None
                )
                with signal_observation(
                    operation="pattern",
                    proposal_id=proposal_id,
                    candidate_id=candidate.candidate_id,
                    task_id=task_id,
                    input={
                        "run_id": self.run_id,
                        "title": candidate.title,
                        "intent": candidate.intent,
                        **(
                            {"definition": definition.model_dump(mode="json")}
                            if definition is not None
                            else {}
                        ),
                    },
                ) as observation:
                    if measurement is not None:
                        proposal = Proposal(
                            proposal_id=proposal_id,
                            run_id=self.run_id,
                            candidate_id=candidate.candidate_id,
                            task_id=task_id,
                            trace_id=LangfuseRunContext(
                                self.run_id, "generic", "", tuple(definition.source_ids)
                            ).trace_id,
                            observation_id=observation.id,
                            title=candidate.title,
                            description=(
                                f"{candidate.intent}\n{candidate.behavior_evidence}"
                                f"\n{candidate.resolution}"
                            ),
                            definition=definition,
                            measurement=measurement,
                            created_at=datetime.now(timezone.utc),
                            limitations=candidate.limitations,
                        )
                        saved.append(self.store.save_proposal(proposal))
                    verdict = decision.verdict if decision is not None else "candidate"
                    summary = {
                        "title": candidate.title,
                        "candidate_id": candidate.candidate_id,
                        "task_id": task_id,
                        "proposal_id": proposal_id,
                        "verdict": verdict,
                        "reason": decision.reason if decision is not None else "독립 검증 대기",
                        "registration_ready": measurement is not None,
                        "measurement": (
                            latest_measurement.model_dump(mode="json")
                            if latest_measurement is not None
                            else None
                        ),
                        "evidence": {
                            "behavior": candidate.behavior_evidence,
                            "normal_comparison": candidate.normal_comparison,
                            "resolution": candidate.resolution,
                            "query_ids": candidate.evidence_query_ids,
                            "verification_query_ids": (
                                decision.evidence_query_ids if decision is not None else []
                            ),
                        },
                        "recommendation": candidate.recommendation,
                        "limitations": candidate.limitations,
                    }
                    observation.update(output=summary)
                    summaries.append(summary)
            collection.update(
                output={
                    "run_id": self.run_id,
                    "pattern_count": len(summaries),
                    "proposal_count": len(saved),
                    "patterns": summaries,
                }
            )
        return saved
