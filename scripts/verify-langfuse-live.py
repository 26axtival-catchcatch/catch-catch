"""Inspect public execution metadata only; credentials and model messages stay private."""

import argparse
import json
import os
from collections import Counter
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("run_id")
args = parser.parse_args()
base = os.environ["LANGFUSE_BASE_URL"].rstrip("/")
auth = (os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])
trace_id = args.run_id.replace("-", "")
with httpx.Client(base_url=base, auth=auth, timeout=30) as client:
    response = client.get(f"/api/public/traces/{trace_id}")
    print("Langfuse HTTP status:", response.status_code)
    response.raise_for_status()
    trace = response.json()
observations = trace.get("observations", [])
by_id = {o["id"]: o for o in observations}
role_ids = {
    o["id"]
    for o in observations
    if o.get("type") == "AGENT" and o.get("name") != "customer_signal.turn"
}


def under_role(observation):
    parent = observation.get("parentObservationId")
    visited = set()
    while parent and parent not in visited:
        if parent in role_ids:
            return True
        visited.add(parent)
        parent = by_id.get(parent, {}).get("parentObservationId")
    return False


nesting = {
    kind: sum(o.get("type") == kind and under_role(o) for o in observations)
    for kind in ("GENERATION", "TOOL")
}
safe = {
    "run_id": args.run_id,
    "trace_id": trace_id,
    "trace_name": trace.get("name"),
    "timestamp": trace.get("timestamp"),
    "observation_counts": dict(Counter(o.get("type") for o in observations)),
    "nested_under_role": nesting,
    "observations": [
        {
            key: o.get(key)
            for key in (
                "id",
                "type",
                "name",
                "parentObservationId",
                "startTime",
                "endTime",
                "level",
            )
        }
        for o in observations
    ],
}
directory = Path("data/live-validation/2026-09-10")
directory.mkdir(parents=True, exist_ok=True)
(directory / f"langfuse-{args.run_id}.json").write_text(
    json.dumps(safe, ensure_ascii=False, indent=2)
)
print(
    json.dumps(
        {
            "run_id": args.run_id,
            "trace_name": safe["trace_name"],
            "counts": safe["observation_counts"],
            "nested_under_role": nesting,
            "roles": [o for o in safe["observations"] if o["type"] == "AGENT"],
        },
        ensure_ascii=False,
    )
)
