"""Exercise synthetic analysis -> selected registration -> fixed-period measurements."""

import argparse
import json
import time
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default="http://127.0.0.1:8000")
parser.add_argument("--run-id")
parser.add_argument("--output-dir", default="data/live-validation/2026-09-10/signals")
parser.add_argument("--mode", default="bedrock", choices=["bedrock", "gemini"])
args = parser.parse_args()
out = Path(args.output_dir)
out.mkdir(parents=True, exist_ok=True)
request = {
    "question": "최근 일주일간 앱에서 원하는 문제를 해결하기 위해 곧바로 못 찾고 헤맨 고객 찾아줘",
    "start_at": "2026-09-04T00:00:00+09:00",
    "end_at": "2026-09-11T00:00:00+09:00",
    "enabled_sources": [
        "hackathon_search_history",
        "hackathon_search_feedback",
        "hackathon_voc",
        "hackathon_app_behavior",
        "hackathon_vas_subscription",
        "hackathon_billing_profile",
        "hackathon_roaming_usage",
    ],
}


def save(name, value):
    (out / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2))


with httpx.Client(base_url=args.base_url, timeout=None) as client:

    def get(path):
        response = client.get(path)
        response.raise_for_status()
        return response.json()

    def post(path, body):
        response = client.post(path, json=body)
        response.raise_for_status()
        return response.json()

    before = get("/api/signals")["items"]
    save("before", before)
    if args.run_id:
        run_id = args.run_id
    else:
        accepted = post("/api/runs?mode=" + args.mode, request)
        run_id = accepted["run_id"]
        save("accepted", accepted)
    print(json.dumps({"run_id": run_id, "mode": args.mode}), flush=True)
    started, last = time.monotonic(), None
    while True:
        run = get("/api/runs/" + run_id)
        state = (run["status"], len(run.get("facts", [])))
        if state != last:
            print(
                json.dumps(
                    {
                        "elapsed": round(time.monotonic() - started),
                        "status": state[0],
                        "facts": state[1],
                    }
                ),
                flush=True,
            )
            last = state
        if run["status"] in {"completed", "failed", "degraded"}:
            break
        time.sleep(3)
    save("run-" + run_id, run)
    assert run["status"] == "completed", run.get("error")
    proposals = get(f"/api/runs/{run_id}/signal-proposals")["items"]
    save("proposals-" + run_id, proposals)
    assert proposals, "No independently measured proposal found"
    before_ids = {s["signal_id"] for s in before}
    proposal_ids = {p["proposal_id"] for p in proposals}
    assert not any(
        s["signal_id"] not in before_ids and s["proposal_id"] in proposal_ids
        for s in get("/api/signals")["items"]
    ), "Analysis must not register signals"
    selected = proposals[0]
    registered = post("/api/signals", {"proposal_id": selected["proposal_id"]})
    assert (
        post("/api/signals", {"proposal_id": selected["proposal_id"]})["signal_id"]
        == registered["signal_id"]
    )
    sid = registered["signal_id"]
    save("registered", registered)
    initial = get(f"/api/signals/{sid}/measurements")
    same = post(
        f"/api/signals/{sid}/measurements",
        {k: request[k] for k in ["start_at", "end_at"]},
    )
    assert same["measurement_id"] == selected["measurement"]["measurement_id"], (
        "Same data/window should reuse initial measurement"
    )
    other_window = {
        "start_at": "2026-09-04T00:00:00+09:00",
        "end_at": "2026-09-07T00:00:00+09:00",
    }
    second = post(f"/api/signals/{sid}/measurements", other_window)
    history = get(f"/api/signals/{sid}/measurements")
    assert {m["measurement_id"] for m in history["items"]} == (
        {m["measurement_id"] for m in initial["items"]} | {second["measurement_id"]}
    )
    assert second["measurement_id"] in {m["measurement_id"] for m in history["items"]}
    save("history", history)
    save(
        "verification",
        {
            "run_id": run_id,
            "signal_id": sid,
            "proposal_count": len(proposals),
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "initial_values": selected["measurement"]["values"],
            "second_values": second["values"],
            "second_status": second["status"],
            "same_measurement_reused": True,
            "comparison_limitations": history["comparison_limitations"],
        },
    )
    print(
        json.dumps(
            {
                "completed": True,
                "run_id": run_id,
                "signal_id": sid,
                "proposal_count": len(proposals),
                "values": selected["measurement"]["values"],
                "history_count": len(history["items"]),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
