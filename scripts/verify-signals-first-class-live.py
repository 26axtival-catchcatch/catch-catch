"""Verify first-class Signal APIs against seeded data; leave the test Signal paused."""

import json
from pathlib import Path

import httpx

DIRECT = {
    "title": "직접 등록 검증 · 부가서비스 반복 검색",
    "description": "반복 검색의 관측 비율. 정상 탐색과 헤맴을 단독 판정하지 않음",
    "start_at": "2026-09-04T00:00:00+09:00",
    "end_at": "2026-09-11T00:00:00+09:00",
    "definition": {
        "source_ids": ["hackathon_search_history"],
        "cohort_sql": "SELECT DISTINCT customer_id FROM hackathon_search_history WHERE topic = '부가서비스 조회/해지' AND dim_query_type = 'repeat'",
        "denominator_sql": "SELECT DISTINCT customer_id FROM hackathon_search_history WHERE topic = '부가서비스 조회/해지'",
        "population_description": "부가서비스 조회/해지 검색 고객",
        "normal_comparison": "반복하지 않은 검색 고객과 비교. 정상 탐색 여부를 별도로 판정하지 않음",
        "metrics": [],
    },
}
RUN_ID = "7b70bd65-cdde-4060-85d5-b39549c0919d"
directory = Path("data/live-validation/2026-09-10/signals-first-class")
directory.mkdir(parents=True, exist_ok=True)
traces = {}

with httpx.Client(base_url="http://localhost:8000", timeout=120) as client:
    def get(path):
        response = client.get(path)
        response.raise_for_status()
        return response.json()

    def post(path, body, operation):
        response = client.post(path, json=body)
        response.raise_for_status()
        traces[operation] = response.headers["X-Langfuse-Trace-Id"]
        return response.json()

    before = get("/api/signals")["items"]
    proposals = get(f"/api/signal-proposals?run_id={RUN_ID}")["items"]
    assert len(proposals) == 3
    assert len(get("/api/signal-proposals")["items"]) >= 6
    proposal = next(p for p in proposals if "부가서비스" in p["title"])
    assert get(f'/api/signal-proposals/{proposal["proposal_id"]}') == proposal
    old = post("/api/signals", {"proposal_id": proposal["proposal_id"]}, "proposal_registration")
    assert old["signal_id"] in {s["signal_id"] for s in before}
    signal = post("/api/signals", DIRECT, "direct_registration")
    assert signal["origin"] == "user_defined" and signal["proposal_id"] is None
    repeated = post("/api/signals", DIRECT, "direct_retry")
    assert repeated["signal_id"] == signal["signal_id"]
    signal_id = signal["signal_id"]
    base_history = get(f"/api/signals/{signal_id}/measurements")["items"]
    assert base_history[0]["values"][0]["value"] == 120
    measurement = post(f"/api/signals/{signal_id}/measurements", {
        "start_at": DIRECT["start_at"], "end_at": "2026-09-07T00:00:00+09:00",
    }, "measurement")
    assert measurement["values"][0]["value"] == 52
    history = get(f"/api/signals/{signal_id}/measurements")
    assert len(history["items"]) == 2 and not history["comparable"]
    count = len(get("/api/signals")["items"])
    invalid = {**DIRECT, "definition": {**DIRECT["definition"], "cohort_sql": "SELECT 1"}}
    assert client.post("/api/signals", json=invalid).status_code == 422
    assert len(get("/api/signals")["items"]) == count
    client.patch(f"/api/signals/{signal_id}", json={"status": "paused"}).raise_for_status()
    assert get(f"/api/signals/{signal_id}")["status"] == "paused"
    schema = get("/openapi.json")
    for path in ("/api/signal-proposals", "/api/signal-proposals/{proposal_id}"):
        assert schema["paths"][path]["get"]["tags"] == ["signals"]
        assert schema["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    summary = {
        "signal_id": signal_id, "origin": signal["origin"], "status": "paused",
        "analysis_proposals": len(proposals), "history_count": len(history["items"]),
        "values": [m["values"] for m in history["items"]], "traces": traces,
        "checks": ["global_candidates", "old_registration", "direct_registration", "idempotence",
                   "server_measurement", "invalid_no_write", "swagger", "pause"],
    }
    (directory / "verification.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
