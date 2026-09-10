"""Verify the real daily worker over approved synthetic sources, including process restart.

Run from the repository root: uv run --project backend python scripts/verify-signal-daily-live.py
Starts temporary uvicorn processes on --port and keeps only sanitized verification evidence.
"""

import argparse
import json
import os
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument(
        "--sources-dir", type=Path, default=ROOT / "data/investigation-demo-sources"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/live-validation/2026-09-10/signals-daily",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    artifacts = args.output.resolve() / (
        "artifacts-" + datetime.now(timezone.utc).strftime("%H%M%S")
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("LANGSMITH_", "LANGCHAIN_", "LANGFUSE_"))
    }
    environment.update(
        ARTIFACT_DIRECTORY=str(artifacts),
        ONBOARDED_SOURCES_DIR=str(args.sources_dir.resolve()),
        JOURNAL_PATH=str(artifacts / "event-journal.sqlite3"),
        SIGNAL_SCHEDULER_ENABLED="true",
        SIGNAL_SCHEDULER_POLL_SECONDS="0.2",
        API_PORT=str(args.port),
    )
    base = f"http://127.0.0.1:{args.port}"
    with httpx.Client(base_url=base, timeout=120) as client:
        try:
            client.get("/health", timeout=1)
        except httpx.ConnectError:
            pass
        else:
            raise RuntimeError("Verification port is already in use")

        @contextmanager
        def server():
            # Startup logs are not forwarded or saved: third-party libraries may log config.
            with tempfile.TemporaryFile() as log:
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
                    env=environment,
                    stdout=log,
                    stderr=log,
                )
                try:
                    for _ in range(200):
                        if proc.poll() is not None:
                            raise RuntimeError(
                                "Verification Backend startup failed (logs withheld)"
                            )
                        try:
                            if client.get("/health", timeout=1).status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("Verification Backend did not become ready")
                    yield
                finally:
                    proc.terminate()
                    try:
                        proc.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)

        def get(path, **params):
            response = client.get(path, params=params)
            response.raise_for_status()
            return response.json()

        def mutate(method, path, body):
            for _ in range(200):
                response = client.request(method, path, json=body)
                if response.status_code != 409:
                    response.raise_for_status()
                    return response.json()
                time.sleep(0.05)
            raise RuntimeError("Schedule remained busy")

        def wait_for_days(root, count):
            for _ in range(300):
                rows = get(root + "/daily-results")["items"]
                completed = [r for r in rows if r["status"] != "running"]
                if len(completed) >= count:
                    return completed
                time.sleep(0.1)
            raise RuntimeError("Daily worker did not finish expected windows")

        payload = {
            "title": "일별 자동 측정 검증 · 부가서비스 반복 검색",
            "description": "승인된 합성 데이터의 동일 기준 일별 비교 검증",
            "start_at": "2026-09-04T00:00:00+09:00",
            "end_at": "2026-09-05T00:00:00+09:00",
            "definition": {
                "source_ids": ["hackathon_search_history"],
                "cohort_sql": "SELECT DISTINCT customer_id FROM hackathon_search_history WHERE topic = '부가서비스 조회/해지' AND dim_query_type = 'repeat'",
                "denominator_sql": "SELECT DISTINCT customer_id FROM hackathon_search_history WHERE topic = '부가서비스 조회/해지'",
                "population_description": "부가서비스 조회/해지 검색 고객",
                "normal_comparison": "반복하지 않은 검색 고객과 비교. 정상 탐색 여부를 별도로 판정하지 않음",
                "metrics": [],
            },
        }
        with server():
            signal = mutate("POST", "/api/signals", payload)
            sid = signal["signal_id"]
            root = "/api/signals/" + sid
            initial = get(root + "/schedule")
            assert initial["enabled"] and initial["interval"] == "daily"
            mutate(
                "PUT",
                root + "/schedule",
                {"enabled": True, "next_run_at": "2026-09-05T00:00:00+09:00"},
            )
            wait_for_days(root, 3)
            mutate("PUT", root + "/schedule", {"enabled": False})
            daily = get(root + "/daily-results")["items"]
            assert all(r["status"] == "success" for r in daily)
            assert all(
                r["measurement"]["pipeline_version"] == "signal-sql-v1" for r in daily
            )
            assert len({r["measurement"]["definition_fingerprint"] for r in daily}) == 1
            old, new = sorted(daily, key=lambda r: r["end_at"])[:2]
            comparison = get(
                root + "/comparison",
                baseline_measurement_id=old["measurement"]["measurement_id"],
                target_measurement_id=new["measurement"]["measurement_id"],
            )
            assert comparison["comparable"], comparison["comparison_limitations"]
            replay = mutate(
                "POST",
                root + "/measurements",
                {"start_at": old["start_at"], "end_at": old["end_at"]},
            )
            assert replay["measurement_id"] == old["measurement"]["measurement_id"]
            assert replay["values"] == old["measurement"]["values"]
            schema = get("/openapi.json")
            for suffix in ["/schedule", "/daily-results", "/comparison"]:
                path = "/api/signals/{signal_id}" + suffix
                for method in schema["paths"][path].values():
                    assert method["tags"] == ["signals"]
                    assert method["responses"]["200"]["content"]["application/json"][
                        "schema"
                    ]
            assert client.get("/docs").status_code == 200
            first_page = get(root + "/daily-results", limit=1)
            second_page = get(
                root + "/daily-results", limit=1, before=first_page["next_before"]
            )
            assert (
                first_page["items"][0]["execution_id"]
                != second_page["items"][0]["execution_id"]
            )
            before_ids = [r["execution_id"] for r in daily]
            history_ids = [
                m["measurement_id"] for m in get(root + "/measurements")["items"]
            ]
        with server():
            assert [
                r["execution_id"] for r in get(root + "/daily-results")["items"]
            ] == before_ids
            assert [
                m["measurement_id"] for m in get(root + "/measurements")["items"]
            ] == history_ids
            assert not get(root + "/schedule")["enabled"]
            # Rewind one completed boundary. Persistent execution and content dedup survive restart.
            mutate(
                "PUT",
                root + "/schedule",
                {"enabled": True, "next_run_at": old["end_at"]},
            )
            for _ in range(100):
                if get(root + "/schedule")["next_run_at"] != old["end_at"]:
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("Worker did not resume after restart")
            mutate("PUT", root + "/schedule", {"enabled": False})
            after = get(root + "/daily-results")["items"]
            assert len([r for r in after if r["end_at"] == old["end_at"]]) == 1
            assert (
                len(
                    [
                        m
                        for m in get(root + "/measurements")["items"]
                        if m["measurement_id"] == replay["measurement_id"]
                    ]
                )
                == 1
            )
            assert all(
                r["execution_id"] in {r2["execution_id"] for r2 in after} for r in daily
            )
        evidence = {
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "signal_id": sid,
            "artifacts": str(artifacts),
            "base_url": base,
            "daily_count": len(daily),
            "days": [
                {
                    "end_at": r["end_at"],
                    "execution_id": r["execution_id"],
                    "measurement_id": r["measurement"]["measurement_id"],
                    "trace_id": r["measurement"]["trace_id"],
                    "values": r["measurement"]["values"],
                }
                for r in daily
            ],
            "comparison": comparison["metrics"],
            "checks": [
                "real_uvicorn",
                "automatic_worker",
                "same_sql_pipeline",
                "korean_daily_windows",
                "manual_matches_automatic",
                "comparison",
                "swagger",
                "pagination",
                "process_restart",
                "schedule_preserved",
                "restart_deduplication",
            ],
            "limitations": [
                "Backfill was used instead of a real 24-hour wait.",
                "Synthetic source data; no LLM calls are required for fixed measurement.",
            ],
        }
        (args.output / "verification.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2)
        )
        print(json.dumps(evidence, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
