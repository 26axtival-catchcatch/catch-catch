"""Run one Bedrock utterance and attach selected registration to its pattern trace."""

import argparse
import json
import time
from pathlib import Path

import httpx

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--question", default="최근 일주일간 앱에서 원하는 문제를 해결하기 위해 곧바로 못 찾고 헤맨 고객 찾아줘")
parser.add_argument("--output-dir", default="data/live-validation/2026-09-10/signals-one-utterance")
args = parser.parse_args()
out = Path(args.output_dir)
out.mkdir(parents=True, exist_ok=True)
request = {
    "question": args.question,
    "start_at": "2026-09-04T00:00:00+09:00", "end_at": "2026-09-11T00:00:00+09:00",
    "enabled_sources": ["hackathon_search_history", "hackathon_search_feedback", "hackathon_voc",
                        "hackathon_app_behavior", "hackathon_vas_subscription",
                        "hackathon_billing_profile", "hackathon_roaming_usage"],
}


def save(name, data):
    (out / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))


with httpx.Client(base_url="http://localhost:8000", timeout=30) as client:
    before = client.get("/api/signals").json()["items"]
    response = client.post("/api/runs?mode=bedrock", json=request)
    response.raise_for_status()
    accepted = response.json()
    save("accepted", accepted)
    run_id = accepted["run_id"]
    trace_id = run_id.replace("-", "")
    print(json.dumps({"run_id": run_id, "trace_id": trace_id}), flush=True)
    started = time.monotonic()
    last = None
    while True:
        response = client.get(f"/api/runs/{run_id}")
        response.raise_for_status()
        run = response.json()
        state = (run["status"], len(run.get("facts", [])))
        if state != last:
            print(json.dumps({"status": state[0], "facts": state[1],
                              "seconds": round(time.monotonic()-started)}), flush=True)
            last = state
        if state[0] in {"completed", "failed", "degraded"}:
            break
        time.sleep(3)
    save("run", run)
    assert run["status"] == "completed", run.get("error")
    response = client.get(f"/api/signal-proposals?run_id={run_id}")
    response.raise_for_status()
    proposals = response.json()["items"]
    save("proposals", proposals)
    assert proposals
    assert all(p["trace_id"] == trace_id and p["observation_id"] for p in proposals)
    after = client.get("/api/signals").json()["items"]
    own_proposals = {p["proposal_id"] for p in proposals}
    before_ids = {s["signal_id"] for s in before}
    assert not any(s["signal_id"] not in before_ids and s["proposal_id"] in own_proposals
                   for s in after)
    response = client.post("/api/signals", json={"proposal_id": proposals[0]["proposal_id"]})
    response.raise_for_status()
    assert response.headers["X-Langfuse-Trace-Id"] == trace_id
    registered = response.json()
    save("registered", registered)
    summary = {"run_id": run_id, "trace_id": trace_id,
               "proposal_count": len(proposals), "selected_signal_id": registered["signal_id"],
               "selected_pattern_observation_id": proposals[0]["observation_id"],
               "analysis_seconds": round(time.monotonic()-started),
               "patterns": [{"title": p["title"], "task_id": p["task_id"],
                             "observation_id": p["observation_id"],
                             "values": p["measurement"]["values"]} for p in proposals]}
    save("verification", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
