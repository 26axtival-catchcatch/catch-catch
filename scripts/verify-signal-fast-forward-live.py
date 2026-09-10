"""Verify real HTTP fast-forward over approved synthetic sources in isolated storage.

uv run --project backend python scripts/verify-signal-fast-forward-live.py
The initial definition and daily measurements use real DuckDB SQL. Recommendations
use fixture mode; this smoke test makes no LLM calls and leaves existing signals alone.
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
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8021)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument(
        "--sources-dir", type=Path, default=ROOT / "data/investigation-demo-sources",
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "data/live-validation/signal-fast-forward",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    artifacts = Path(tempfile.mkdtemp(prefix="artifacts-", dir=args.output)).resolve()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", args.port))
    environment = {
        k: v for k, v in os.environ.items()
        if not k.startswith(("LANGSMITH_", "LANGCHAIN_", "LANGFUSE_"))
    }
    environment.update(
        AGENT_MODE="fixture", ARTIFACT_DIRECTORY=str(artifacts),
        JOURNAL_PATH=str(artifacts / "journal.sqlite3"),
        ONBOARDED_SOURCES_DIR=str(args.sources_dir.resolve()),
        SIGNAL_SCHEDULER_ENABLED="false", API_PORT=str(args.port),
    )
    with httpx.Client(base_url=f"http://127.0.0.1:{args.port}", timeout=120) as client:
        @contextmanager
        def server():
            process = subprocess.Popen([
                "uv", "run", "--env-file", str(args.env_file.resolve()), "--project", "backend",
                "uvicorn", "customer_signal.api:create_app", "--factory",
                "--host", "127.0.0.1", "--port", str(args.port),
            ], cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(300):
                    if process.poll() is not None:
                        raise RuntimeError("검증 Backend 시작 실패, 환경 원문 로그는 출력하지 않습니다.")
                    try:
                        if client.get("/health", timeout=1).status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("검증 Backend 준비 시간 초과")
                yield
            finally:
                process.terminate()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        with server():
            signal = request("POST", "/api/signals", json={
                "title": "빨리감기 검증: 부가서비스 반복 검색",
                "description": "승인된 합성 Source의 주간 분석 이후 다음 일자 측정",
                "start_at": "2026-09-04T00:00:00+09:00",
                "end_at": "2026-09-11T00:00:00+09:00",
                "definition": {
                    "source_ids": ["hackathon_search_history"],
                    "cohort_sql": "SELECT DISTINCT customer_id FROM events WHERE topic='부가서비스 조회/해지' AND dim_query_type='repeat'",
                    "denominator_sql": "SELECT DISTINCT customer_id FROM events WHERE topic='부가서비스 조회/해지'",
                    "population_description": "부가서비스 조회/해지 검색 고객",
                    "normal_comparison": "반복하지 않은 검색 고객",
                },
            })
            sid = signal["signal_id"]
            root = f"/api/signals/{sid}"
            rec = next(r for r in signal["alert_recommendations"]["items"]
                       if r["metric_key"] == "affected_customer_count")
            # Explicit smoke-test rule, evaluated against SQL results, never a forged event.
            request("PUT", root + "/alert-rules", json={
                "revision": 0, "items": [{"recommendation_id": rec["recommendation_id"],
                                           "threshold": 1}],
            })
            cursor = request("GET", "/api/signal-alert-events")["next_cursor"]
            body = {"request_id": str(uuid4()), "days": 1, "signal_ids": [sid]}
            started = time.monotonic()
            result = request("POST", "/api/signals/fast-forward", json=body)
            elapsed = round(time.monotonic() - started, 3)
            item = result["items"][0]
            day = item["daily_results"][0]
            measured = day["measurement"]
            assert measured["status"] == "success", measured["reason"]
            assert day["start_at"] == "2026-09-10T15:00:00Z"
            assert day["end_at"] == "2026-09-11T15:00:00Z"
            page = request("GET", "/api/signal-alert-events", params={"after": cursor})
            assert len(page["items"]) == 1
            assert page["items"] == item["alert_events"]
            assert page["items"][0]["measurement_id"] == measured["measurement_id"]
            assert page["items"][0]["metric_value"] == measured["values"][0]["value"]
            assert request("POST", "/api/signals/fast-forward", json=body) == result
            manual = request("POST", root + "/measurements", json={
                "start_at": day["start_at"], "end_at": day["end_at"],
            })
            assert manual["measurement_id"] == measured["measurement_id"]
            assert manual["values"] == measured["values"]
            assert measured["measurement_id"] in str(request("GET", "/api/signals/briefing"))
            assert request("GET", root + "/daily-results")["items"][0] == day
            assert client.get("/docs").status_code == 200
            assert "/api/signals/fast-forward" in request("GET", "/openapi.json")["paths"]

        with server():
            assert request("POST", "/api/signals/fast-forward", json=body) == result
            assert request("GET", "/api/signal-alert-events", params={"after": cursor}) == page
            assert not request("GET", "/api/signal-alert-events", params={
                "after": page["next_cursor"],
            })["items"]
            following = request("POST", "/api/signals/fast-forward", json={
                **body, "request_id": str(uuid4()),
            })["items"][0]
            assert following["daily_results"][0]["start_at"] == day["end_at"]

    evidence = {
        "signal_id": sid, "request_id": body["request_id"], "elapsed_seconds": elapsed,
        "start_at": day["start_at"], "end_at": day["end_at"],
        "measurement_id": measured["measurement_id"], "values": measured["values"],
        "trace_id": measured["trace_id"], "alert_count": len(page["items"]),
        "checks": ["real_http", "weekly_initial_sql", "daily_baseline", "next_day_sql",
                   "existing_polling_event", "manual_same_measurement", "briefing", "daily_history",
                   "swagger", "idempotency", "process_restart", "next_request_next_day"],
        "limitations": ["approved synthetic sources", "fixture recommendations", "no new LLM run"],
    }
    (args.output / "verification.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
