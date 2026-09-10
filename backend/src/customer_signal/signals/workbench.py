"""Run-local measured proposals; only independent confirmations become durable."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field

from customer_signal.investigation.data import query_owner
from customer_signal.observability.langfuse import current_run_id
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
        by_id = {c.candidate_id: c for c in candidates}
        for decision in decisions:
            query = self.data.queries.get(decision.cohort_query_id, {})
            measurement = self.verified_measurement(decision, query.get("owner", ""))
            candidate = by_id.get(decision.candidate_id)
            if measurement is None or candidate is None:
                continue
            proposal = Proposal(
                proposal_id=str(
                    uuid5(NAMESPACE_URL, f"signal:{self.run_id}:{candidate.candidate_id}")
                ),
                run_id=self.run_id,
                candidate_id=candidate.candidate_id,
                title=candidate.title,
                description=f"{candidate.intent}\n{candidate.behavior_evidence}\n{candidate.resolution}",
                definition=self.proposals[candidate.candidate_id],
                measurement=measurement,
                created_at=datetime.now(timezone.utc),
                limitations=candidate.limitations,
            )
            saved.append(self.store.save_proposal(proposal))
        return saved
