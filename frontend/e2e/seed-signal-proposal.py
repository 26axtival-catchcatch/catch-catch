"""Seed only an analysis candidate, measured by real SQL, for the browser test.

The fixture planner does not propose SQL signals. Its completed HTTP Run remains
unchanged; registration, rules, daily analysis and alert events all use real APIs.
"""

import argparse
import json
from pathlib import Path
from uuid import uuid4

from customer_signal.data.source_registry import SourceRegistry
from customer_signal.investigation.data import InvestigationData
from customer_signal.onboarding.adapter import CompositeEvidenceProvider, load_onboarded_adapters
from customer_signal.runtime.artifact_store import ArtifactStore
from customer_signal.signals.contracts import Proposal, SignalDefinition
from customer_signal.signals.measurement import measure_definition
from customer_signal.signals.store import SignalStore

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--artifacts", type=Path, required=True)
parser.add_argument("--sources", type=Path, required=True)
parser.add_argument("--run-id", required=True)
args = parser.parse_args()
artifact = ArtifactStore(args.artifacts).load(args.run_id)
assert artifact.status == "completed"
definition = SignalDefinition(
    source_ids=["hackathon_search_history"],
    cohort_sql="SELECT DISTINCT customer_id FROM events WHERE topic='부가서비스 조회/해지' AND dim_query_type='repeat'",
    denominator_sql="SELECT DISTINCT customer_id FROM events WHERE topic='부가서비스 조회/해지'",
    population_description=f"부가서비스 검색 고객 (E2E {args.run_id})",
    normal_comparison="반복하지 않은 검색 고객",
)
adapters = load_onboarded_adapters(args.sources)
registry = SourceRegistry(adapters, evidence=CompositeEvidenceProvider(None, adapters))
request = artifact.request.model_copy(update={"enabled_sources": definition.source_ids})
data = InvestigationData.load(registry, request)
try:
    measurement = measure_definition(data, definition)
finally:
    data.close()
assert measurement.status == "success"
proposal = Proposal(
    proposal_id=str(uuid4()), run_id=args.run_id, candidate_id="browser-notification-e2e",
    title="부가서비스 반복 검색", description="실제 SQL로 측정한 반복 검색 고객",
    definition=definition, measurement=measurement,
)
SignalStore(args.artifacts / "signals.sqlite3").save_proposal(proposal)
print(json.dumps({"proposal_id": proposal.proposal_id, "values": measurement.model_dump(mode="json")["values"]}))
