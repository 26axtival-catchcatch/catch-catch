"""Verify real model recommendations and durable HTTP alerts over approved synthetic sources.

Run: uv run --project backend python scripts/verify-signal-alerts-live.py --mode bedrock
Provider credentials are loaded only in the temporary Backend via uv --env-file.
"""

import argparse
import json
import os
import socket
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=["bedrock", "gemini", "fixture"], default="bedrock"
    )
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--port", type=int, default=8017)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "data/live-validation/signal-alerts"
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    artifacts = Path(
        tempfile.mkdtemp(prefix="alert-artifacts-", dir=args.output)
    ).resolve()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", args.port))
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("LANGSMITH_", "LANGCHAIN_", "LANGFUSE_"))
    }
    env.update(
        AGENT_MODE=args.mode,
        ARTIFACT_DIRECTORY=str(artifacts),
        JOURNAL_PATH=str(artifacts / "journal.sqlite3"),
        DATABASE_PATH=str(artifacts / "synthetic.duckdb"),
        ONBOARDED_SOURCES_DIR=str(
            ROOT / "data/seeding/hackathon-2week/onboarded-sources"
        ),
        SIGNAL_SCHEDULER_ENABLED="false",
    )
    client = httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=90)

    @contextmanager
    def server():
        # Third-party startup/provider logs are deliberately neither printed nor saved.
        proc = subprocess.Popen(
            [
                "uv",
                "run",
                "--env-file",
                str(args.env_file.resolve()),
                "--project",
                "backend",
                "uvicorn",
                "customer_signal.api:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.port),
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(300):
                if proc.poll() is not None:
                    raise RuntimeError(
                        "Temporary Backend startup failed; provider logs withheld"
                    )
                try:
                    if client.get("/health", timeout=1).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("Temporary Backend startup timed out")
            yield
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    def request(method, path, **kwargs):
        result = client.request(method, path, **kwargs)
        if result.status_code != 200:
            raise RuntimeError(
                f"HTTP verification failed: {method} {path} ({result.status_code})"
            )
        return result.json(), result.headers

    payload = {
        "title": "합성 검증: 부가서비스 반복 검색",
        "description": "승인된 합성 데이터에서 하루 반복 검색 고객의 변화를 관찰합니다.",
        "start_at": "2026-09-04T00:00:00+09:00",
        "end_at": "2026-09-05T00:00:00+09:00",
        "definition": {
            "source_ids": ["hackathon_search_history"],
            "cohort_sql": "SELECT DISTINCT customer_id FROM hackathon_search_history WHERE topic = '부가서비스 조회/해지' AND dim_query_type = 'repeat'",
            "denominator_sql": "SELECT DISTINCT customer_id FROM hackathon_search_history WHERE topic = '부가서비스 조회/해지'",
            "population_description": "부가서비스 조회/해지 검색 고객",
            "normal_comparison": "반복하지 않은 검색 고객과 비교합니다.",
            "metrics": [],
        },
    }
    with server():
        signal, headers = request("POST", "/api/signals", json=payload)
        recs = signal["alert_recommendations"]
        assert recs and recs["status"] == "ready", "No validated model recommendations"
        assert recs["source"] == ("fixture" if args.mode == "fixture" else "model")
        root = "/api/signals/" + signal["signal_id"]
        rules, _ = request("GET", root + "/alert-rules")
        assert not rules["items"]
        baseline, _ = request("GET", "/api/signal-alert-events")
        assert baseline["next_cursor"] == 0
        # Select the generated condition with a test threshold guaranteed to expose transitions
        # for common positive synthetic metrics; this is explicit user selection, not model output.
        rec = next(
            (r for r in recs["items"] if r["operator"] in ["gte", "gt"]),
            recs["items"][0],
        )
        threshold = (
            (0 if rec["kind"] == "value" else -1000000)
            if rec["operator"] in ["gte", "gt"]
            else (
                100
                if rec["kind"] == "value" and rec["metric_unit"] in ["percent", "%"]
                else 1000000
            )
        )
        rules, _ = request(
            "PUT",
            root + "/alert-rules",
            json={
                "revision": 0,
                "items": [
                    {
                        "recommendation_id": rec["recommendation_id"],
                        "threshold": threshold,
                    }
                ],
            },
        )
        window = {
            "start_at": "2026-09-05T00:00:00+09:00",
            "end_at": "2026-09-06T00:00:00+09:00",
        }
        measured, _ = request("POST", root + "/measurements", json=window)
        assert measured["status"] == "success"
        page, _ = request("GET", "/api/signal-alert-events?after=0&limit=1")
        assert len(page["items"]) == 1, "Synthetic selected condition did not cross"
        repeated, _ = request("POST", root + "/measurements", json=window)
        assert repeated["measurement_id"] == measured["measurement_id"]
        assert (
            request("GET", "/api/signal-alert-events?after=0")[0]["items"]
            == page["items"]
        )
        assert request("GET", "/api/signal-alert-events")[0]["items"] == []
        report = {
            "mode": args.mode,
            "signal_id": signal["signal_id"],
            "trace_id": headers.get("X-Langfuse-Trace-Id"),
            "recommendations": recs,
            "selected_rule": rules["items"][0],
            "event": page["items"][0],
            "duplicate_suppressed": True,
        }
    with server():
        assert request("GET", root + "/alert-rules")[0] == rules
        assert request("GET", root + "/alert-recommendations")[0] == recs
        assert (
            request("GET", "/api/signal-alert-events?after=0")[0]["items"]
            == page["items"]
        )
        assert (
            request(
                "GET", "/api/signal-alert-events?after=" + str(page["next_cursor"])
            )[0]["items"]
            == []
        )
        report["restart_verified"] = True
    client.close()
    (args.output / f"{args.mode}-verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in [
                    "mode",
                    "signal_id",
                    "trace_id",
                    "duplicate_suppressed",
                    "restart_verified",
                ]
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
