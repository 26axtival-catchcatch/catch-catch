"""Verify a synthetic app run and actual Langfuse ingestion; emit public metadata only."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import re
import time

import httpx

from compose import LOCAL, compose, read_env


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["fixture", "gemini", "bedrock"], default="fixture")
    parser.add_argument("--run-id", help="Recheck persisted results without another analysis")
    args = parser.parse_args()
    settings = read_env(LOCAL / "stack.env")
    started_at = datetime.now(timezone.utc)
    app_url = settings["APP_URL"]
    api_url = app_url + "/backend"
    auth = (settings["LANGFUSE_PUBLIC_KEY"], settings["LANGFUSE_SECRET_KEY"])
    with httpx.Client(timeout=30, trust_env=False) as client:
        for url in (app_url, app_url + "/legacy", api_url + "/health", api_url + "/docs",
                    settings["LANGFUSE_URL"] + "/api/public/health"):
            require(client.get(url).is_success, "Service health/UI check failed")
        catalog = client.get(api_url + "/api/sources")
        require(catalog.is_success, "Source catalog failed")
        schema = client.get(api_url + "/openapi.json")
        require(schema.is_success and "/api/runs" in schema.json().get("paths", {}),
                "Swagger OpenAPI schema is unavailable")
        require("/backend/openapi.json" in client.get(api_url + "/docs").text,
                "Swagger UI points to the wrong schema URL")
        if args.run_id:
            run_id = args.run_id
        else:
            response = client.post(api_url + f"/api/runs?mode={args.mode}", json={
                "question": "최근 부정 피드백이 많은 Topic과 관련 고객 Segment를 알려줘.",
                "start_at": "2026-07-20T00:00:00+09:00",
                "end_at": "2026-08-19T00:00:00+09:00",
                "enabled_sources": ["search_history", "search_feedback", "digital_behavior",
                                    "subscription", "voc"],
            })
            require(response.is_success, "Synthetic run was not accepted")
            run_id = response.json()["run_id"]
        print(json.dumps({"run_id": run_id, "mode": args.mode}), flush=True)
        streamed_while_active = False
        if not args.run_id:
            # Open immediately after acceptance, before waiting for completion.
            with client.stream("GET", api_url + f"/api/runs/{run_id}/events", timeout=600) as live:
                require(live.is_success, "Live SSE connection failed")
                require(live.headers.get("x-accel-buffering") == "no",
                        "Proxy streaming header is missing")
                checked_active = False
                for line in live.iter_lines():
                    if line.startswith("event:") and not checked_active:
                        state = client.get(api_url + f"/api/runs/{run_id}").json()["status"]
                        streamed_while_active = state not in {"completed", "failed", "degraded"}
                        checked_active = True
                    if line == "event: done":
                        break
            if args.mode != "fixture":
                require(streamed_while_active, "No SSE event arrived before run completion")
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            response = client.get(api_url + f"/api/runs/{run_id}")
            require(response.is_success, "Run snapshot failed")
            snapshot = response.json()
            if snapshot["status"] in {"completed", "failed", "degraded", "awaiting_clarification"}:
                break
            time.sleep(2)
        require(snapshot["status"] == "completed", "Run did not complete successfully")
        require(bool(snapshot.get("facts")), "Completed run has no facts")
        stream = client.get(api_url + f"/api/runs/{run_id}/events")
        require(stream.is_success, "SSE request failed")
        require("event: result" in stream.text and "event: done" in stream.text,
                "SSE result/done events are missing")
        ids = [int(value) for value in re.findall(r"^id: (\d+)$", stream.text, re.MULTILINE)]
        require(len(ids) >= 3, "SSE stream has too few events")
        replay = client.get(api_url + f"/api/runs/{run_id}/events",
                            headers={"Last-Event-ID": str(ids[-3])})
        replay_ids = [int(value) for value in re.findall(r"^id: (\d+)$", replay.text, re.MULTILINE)]
        require(replay.is_success and replay_ids == ids[-2:], "SSE replay failed")
        for extension in ("json", "md"):
            download = client.get(api_url + f"/api/run-artifacts/{run_id}/download.{extension}")
            require(download.is_success and bool(download.content), "Artifact download failed")
        trace_id = run_id.replace("-", "")
        deadline = time.monotonic() + 240
        observations = []
        while time.monotonic() < deadline:
            response = client.get(settings["LANGFUSE_URL"] + f"/api/public/traces/{trace_id}",
                                  auth=auth)
            if response.is_success:
                trace = response.json()
                observations = trace.get("observations", [])
                has_tools = any(o.get("name", "").startswith("customer_signal.tool.") for o in observations)
                has_generation = any(o.get("type") == "GENERATION" for o in observations)
                has_workflow = any(o.get("name") == "customer_signal.turn" and o.get("endTime")
                                   for o in observations)
                if has_tools and has_workflow and (args.mode == "fixture" or has_generation):
                    break
            elif response.status_code != 404:
                raise RuntimeError(f"Langfuse trace lookup returned HTTP {response.status_code}")
            time.sleep(3)
        require(bool(observations), "Fresh application trace was not ingested")
        require(trace.get("name") == "customer_signal.turn", "Wrong trace name")
        require(trace.get("id") == trace_id, "Wrong trace identity")
        if not args.run_id:
            timestamp = datetime.fromisoformat(trace["timestamp"].replace("Z", "+00:00"))
            require(timestamp >= started_at, "Trace is older than this verification")
        known_ids = {o["id"] for o in observations}
        # An explicit OTel trace ID can use an unrecorded remote parent span ID.
        # The workflow must be the sole recorded root, with no recorded parent.
        roots = [o for o in observations if o.get("name") == "customer_signal.turn"
                 and o.get("parentObservationId") not in known_ids]
        require(len(roots) == 1, "Expected one parent workflow span")
        require(roots[0].get("metadata", {}).get("provider") == "server",
                "Workflow provider metadata must identify the server")
        tools = [o for o in observations if o.get("name", "").startswith("customer_signal.tool.")]
        require(bool(tools), "Analysis tool spans are missing")
        require(all(o.get("parentObservationId") in known_ids for o in tools),
                "Analysis spans are not nested in the trace")
        stages = set()
        for observation in tools:
            metadata = observation.get("metadata") or {}
            require(metadata.get("stage") == "tool", "Tool stage metadata is missing")
            require(metadata.get("run_id") == run_id, "Tool run_id metadata does not match")
            stages.add(metadata["stage"])
        counts = dict(Counter(o.get("type") for o in observations))
        generation_errors = [o for o in observations
                             if o.get("type") == "GENERATION" and o.get("level") == "ERROR"]
        provider_error_types = sorted({
            kind for o in generation_errors
            for kind in re.findall(r"\b[A-Za-z]+(?:Error|Exception)\b", o.get("statusMessage") or "")
        })
        if args.mode != "fixture":
            require(counts.get("GENERATION", 0) > 0, "Model generation spans are missing")
            by_id = {o["id"]: o for o in observations}
            for observation in (o for o in observations if o.get("type") == "GENERATION"):
                metadata = observation.get("metadata") or {}
                stage = metadata.get("stage")
                require(bool(stage) and observation.get("name") == f"customer_signal.{stage}",
                        "Model generation name/stage mismatch")
                require(metadata.get("provider") == args.mode and metadata.get("run_id") == run_id,
                        "Model generation provider/run_id mismatch")
                stages.add(stage)
                parent, visited = observation.get("parentObservationId"), set()
                while parent in by_id and parent not in visited and parent != roots[0]["id"]:
                    visited.add(parent)
                    parent = by_id[parent].get("parentObservationId")
                require(parent == roots[0]["id"], "Model generation is outside the workflow root")
        # Inspect names/booleans only, never print Docker's resolved environment.
        inspection = compose("exec", "-T", "frontend", "node", "-e",
            "process.stdout.write(JSON.stringify(Object.keys(process.env).filter(k=>"
            "/^(LANGFUSE_|LANGSMITH_|LANGCHAIN_|GEMINI_|GOOGLE_|AWS_|BEDROCK_)/.test(k))))",
            capture_output=True, text=True)
        require(json.loads(inspection.stdout) == [], "Frontend received backend credentials")
        summary = {
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id, "mode": args.mode, "status": snapshot["status"],
            "existing_run_rechecked": bool(args.run_id),
            "facts": len(snapshot["facts"]), "sse_events": len(ids),
            "sse_replay": "passed", "downloads": "passed", "frontend_secret_isolation": "passed",
            "sse_observed_while_active": streamed_while_active if not args.run_id else None,
            "trace_id": trace_id, "trace_name": trace["name"], "timestamp": trace["timestamp"],
            "trace_url": settings["LANGFUSE_URL"] + f"/project/catch-catch-local/traces/{trace_id}",
            "observation_counts": counts, "stages": sorted(stages),
            "trace_ingestion": "passed",
            "model_execution": "partial" if generation_errors else (
                "not_applicable" if args.mode == "fixture" else "passed"),
            "generation_errors": len(generation_errors),
            "provider_error_types": provider_error_types,
            "models": sorted({o["model"] for o in observations
                              if o.get("type") == "GENERATION" and o.get("model")}),
            "observations": [
                {**{key: o.get(key) for key in
                    ("id", "type", "name", "parentObservationId", "startTime")},
                 "stage": (o.get("metadata") or {}).get("stage"),
                 "provider": (o.get("metadata") or {}).get("provider")}
                for o in observations
            ],
        }
        # This file deliberately excludes trace inputs/outputs and provider messages.
        suffix = "-rechecked" if args.run_id else ""
        output = LOCAL / f"verification-{run_id}{suffix}.json"
        output.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        print(json.dumps({key: value for key, value in summary.items() if key != "observations"},
                         ensure_ascii=False, indent=2))
        require(not generation_errors,
                "Trace ingestion passed, but provider errors caused a partial model execution")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # HTTP exceptions may contain URLs; never emit response bodies or credentials.
        print(f"Verification failed: {type(error).__name__}" +
              (f": {error}" if isinstance(error, RuntimeError) else ""), flush=True)
        raise SystemExit(1)
