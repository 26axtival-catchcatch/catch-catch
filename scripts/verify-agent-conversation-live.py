"""Verify public conversation replay and local Langfuse metadata for an existing Run."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import httpx


def public_history(stream: str) -> str:
    """Ignore transport keep-alive comments, preserving IDs, types and payloads."""
    return "\n".join(line for line in stream.splitlines()
                     if line.startswith(("id:", "event:", "data:")))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--expect-commentary", action="store_true")
    args = parser.parse_args()
    local = Path(__file__).resolve().parents[1] / ".local/compose/stack.env"
    settings = dict(line.split("=", 1) for line in local.read_text().splitlines()
                    if line and not line.startswith("#"))
    base = settings["APP_URL"] + "/backend/api/runs/" + args.run_id
    with httpx.Client(timeout=900, trust_env=False) as client:
        response = client.get(base + "/events")
        response.raise_for_status()
        events = [json.loads(line[6:]) for line in response.text.splitlines()
                  if line.startswith("data: ")]
        activities = [event["payload"] for event in events if event["type"] == "agent_activity"]
        assert activities, "Run has no public agent_activity messages"
        commentaries = [item for item in activities if item.get("message_kind") == "commentary"]
        if args.expect_commentary:
            assert commentaries, "Run has no public model commentary"
            assert all(item["kind"] == "model" and item["status"] == "completed" for item in commentaries)
            assert all(item["display_text"] == "모델 응답 생성" and item.get("message_text") for item in commentaries), "Chat text must remain separate from execution labels"
        assert events[-1]["type"] == "done", "Replay did not reach the terminal event"
        snapshot = client.get(base).json()
        assert snapshot["status"] in {"completed", "degraded"}, "Analysis did not complete"
        replay = client.get(base + "/events")
        replay.raise_for_status()
        history = public_history(response.text)
        assert public_history(replay.text) == history, "Public history changed between replays"
        trace_id = args.run_id.replace("-", "")
        trace_response = client.get(
            settings["LANGFUSE_URL"] + f"/api/public/traces/{trace_id}",
            auth=(settings["LANGFUSE_PUBLIC_KEY"], settings["LANGFUSE_SECRET_KEY"]),
        )
        trace_response.raise_for_status()
        trace = trace_response.json()
        observations = trace.get("observations", [])
        assert any(item.get("type") == "GENERATION" for item in observations)
        assert any(item.get("type") == "AGENT" for item in observations)
        safe = {
            "run_id": args.run_id, "status": snapshot["status"],
            "event_count": len(events), "activity_count": len(activities),
            "commentary_count": len(commentaries),
            "summary_count": sum(item.get("message_kind") == "summary" for item in activities),
            "agents": len({item["node_id"] for item in activities if item["kind"] == "agent"}),
            "roles": dict(Counter(item["role"] for item in activities)),
            "kinds": dict(Counter(item["kind"] for item in activities)),
            "first_message_at": activities[0]["occurred_at"],
            "last_message_at": activities[-1]["occurred_at"],
            "history_sha256": hashlib.sha256(history.encode()).hexdigest(),
            "trace_id": trace_id, "trace_name": trace.get("name"),
            "trace_timestamp": trace.get("timestamp"),
            "observation_types": dict(Counter(item.get("type") for item in observations)),
            "observation_names": sorted({item["name"] for item in observations}),
            "stages": sorted({str(item.get("metadata", {}).get("stage")) for item in observations
                              if item.get("metadata", {}).get("stage")}),
        }
        directory = Path("data/live-validation/agent-conversation")
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{args.run_id}.json"
        if target.exists():
            previous = json.loads(target.read_text())
            assert previous["history_sha256"] == safe["history_sha256"], "Persisted replay changed"
        target.write_text(json.dumps(safe, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(safe, ensure_ascii=False))


if __name__ == "__main__":
    main()
