"""Run the approved synthetic demo through the existing HTTP contract."""

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("label", choices=["limited", "expanded"])
parser.add_argument("--base-url", default="http://127.0.0.1:8000")
parser.add_argument(
    "--run-id", help="Verify an existing completed run without another model call"
)
args = parser.parse_args()
sources = ["hackathon_search_history", "hackathon_search_feedback", "hackathon_voc"]
if args.label == "expanded":
    sources += [
        "hackathon_app_behavior",
        "hackathon_vas_subscription",
        "hackathon_billing_profile",
        "hackathon_roaming_usage",
    ]
request = {
    "question": "최근 일주일간 앱에서 원하는 문제를 해결하기 위해 곧바로 못 찾고 헤맨 고객 찾아줘",
    "start_at": "2026-09-04T00:00:00+09:00",
    "end_at": "2026-09-11T00:00:00+09:00",
    "enabled_sources": sources,
}
directory = Path("data/live-validation/2026-09-10")
directory.mkdir(parents=True, exist_ok=True)
with httpx.Client(base_url=args.base_url, timeout=60) as client:
    catalog = client.get("/api/sources")
    catalog.raise_for_status()
    if args.run_id:
        accepted = {
            "run_id": args.run_id,
            "status_url": f"/api/runs/{args.run_id}",
            "events_url": f"/api/runs/{args.run_id}/events",
        }
    else:
        response = client.post("/api/runs?mode=gemini", json=request)
        response.raise_for_status()
        accepted = response.json()
    run_id = accepted["run_id"]
    print(
        json.dumps({"label": args.label, "run_id": run_id}, ensure_ascii=False),
        flush=True,
    )
    (directory / f"{args.label}-accepted.json").write_text(
        json.dumps(accepted, indent=2)
    )
    started, last_status = time.monotonic(), None
    while True:
        snapshot_response = client.get(accepted["status_url"])
        snapshot_response.raise_for_status()
        snapshot = snapshot_response.json()
        state = (snapshot["status"], len(snapshot.get("facts", [])))
        if state != last_status:
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
            last_status = state
        if snapshot["status"] in {"completed", "failed", "degraded"}:
            break
        time.sleep(3)
    (directory / f"{args.label}-snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2)
    )
    assert snapshot["status"] == "completed", snapshot.get("error")
    report = snapshot["report"]
    assert report["report_kind"] == "customer_signal"
    if args.label == "expanded":
        assert report["findings"], (
            "Expanded run did not establish an evidence-backed pattern"
        )
    checked = []
    for fact in snapshot["facts"]:
        payload = fact["payload"]
        if payload["kind"] == "get_customer_journey":
            detail = client.get(
                f"/api/runs/{run_id}/customers/{payload['customer_id']}/journey"
            )
            detail.raise_for_status()
            checked.append("journey:" + payload["customer_id"])
        if payload["kind"] == "get_evidence" and payload["records"]:
            detail = client.get(
                f"/api/runs/{run_id}/evidence/{payload['records'][0]['evidence_id']}"
            )
            detail.raise_for_status()
            checked.append("evidence:" + payload["records"][0]["evidence_id"])
    for extension in ("json", "md"):
        downloaded = client.get(f"/api/run-artifacts/{run_id}/download.{extension}")
        downloaded.raise_for_status()
        (directory / f"{args.label}-report.{extension}").write_bytes(downloaded.content)
    stream = client.get(accepted["events_url"])
    stream.raise_for_status()
    assert "event: result" in stream.text and "event: done" in stream.text
    event_ids = [
        int(value) for value in re.findall(r"^id: (\d+)$", stream.text, re.MULTILINE)
    ]
    assert len(event_ids) >= 3
    replay = client.get(
        accepted["events_url"], headers={"Last-Event-ID": str(event_ids[-3])}
    )
    replay.raise_for_status()
    replay_ids = [
        int(value) for value in re.findall(r"^id: (\d+)$", replay.text, re.MULTILINE)
    ]
    assert replay_ids == event_ids[-2:]
    presentation = client.get(f"/api/runs/{run_id}/presentation")
    presentation.raise_for_status()
    checked.extend(["SSE-reconnect", "presentation"])
    (directory / f"{args.label}-events.txt").write_text(stream.text)
    analysis_elapsed = (
        datetime.fromisoformat(snapshot["updated_at"])
        - datetime.fromisoformat(snapshot["created_at"])
    ).total_seconds()
    summary = {
        "label": args.label,
        "run_id": run_id,
        "elapsed_seconds": round(analysis_elapsed, 2),
        "metrics": report["metrics"],
        "findings": len(report["findings"]),
        "checked": checked,
        "headline": report["headline"],
        "limitations": report["limitations"],
    }
    (directory / f"{args.label}-validation.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )
    print(json.dumps(summary, ensure_ascii=False), flush=True)
