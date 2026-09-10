"""Verify one real model/tool role and its Langfuse trace using synthetic data only."""

import asyncio
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from customer_signal.agent.contracts import RunRequest
from customer_signal.config import Settings
from customer_signal.domain.models import CustomerEvent
from customer_signal.investigation.activity import ActivityStream
from customer_signal.investigation.contracts import Narrative
from customer_signal.investigation.data import InvestigationData
from customer_signal.investigation.model import (
    BedrockInvestigationModel,
    GeminiInvestigationModel,
)
from customer_signal.observability.langfuse import (
    LangfuseRunContext,
    agent_observation,
    bind_langfuse_run,
    flush_langfuse,
)


async def main():
    settings = Settings()
    if settings.resolved_agent_mode == "bedrock":
        model = BedrockInvestigationModel(
            api_key=settings.aws_bearer_token_bedrock.get_secret_value(),
            model=settings.bedrock_model,
            region=settings.aws_region,
            timeout_seconds=60,
        )
    elif settings.resolved_agent_mode == "gemini":
        model = GeminiInvestigationModel(
            api_key=settings.gemini_api_key.get_secret_value(),
            primary_model=settings.gemini_model,
            fallback_model=settings.gemini_fallback_model,
            timeout_seconds=60,
        )
    else:
        raise RuntimeError("Select a configured bedrock or gemini provider")
    run_id = str(uuid4())
    request = RunRequest(
        question="합성 데이터 목록을 확인하고 공개 요약을 작성합니다.",
        start_at="2026-09-04T00:00:00Z",
        end_at="2026-09-11T00:00:00Z",
        enabled_sources=["app"],
    )
    data = InvestigationData(
        request=request,
        events=[
            CustomerEvent(
                event_id="event-smoke",
                evidence_id="evidence-smoke",
                source_id="app",
                occurred_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
                event_type="menu_view",
                action="메뉴 탐색",
                topic="서비스",
                outcome="조회",
                text="합성 메뉴 조회 이벤트",
                canonical_customer_id="synthetic-activity-smoke",
            )
        ],
        manifests=[],
        snapshot_id="activity-live-smoke",
    )
    events = []

    async def emit(event):
        events.append(event.model_dump(mode="json"))

    stream = ActivityStream(emit)
    node = await stream.agent("reporter", "task-activity-smoke", 0, [])
    trace = LangfuseRunContext(run_id, "generic", request.question, ("app",))
    try:
        with (
            bind_langfuse_run(trace),
            agent_observation(
                role="reporter",
                task_id=node.task_id,
                input={"purpose": "synthetic_activity_smoke"},
                round_index=0,
            ),
            stream.bind(node),
        ):
            await stream.publish(node, "started")
            async with asyncio.timeout(120):
                result = await model.run_role(
                    role="reporter",
                    task_id=node.task_id,
                    instruction="catalog_data를 한 번 호출한 후 finish로 한국어 headline, summary, display_summary를 제출합니다. 추가 조사는 필요 없습니다.",
                    context={"catalog": data.catalog()},
                    data=data,
                    result_type=Narrative,
                )
            await stream.publish(
                node, "completed", text=result.display_summary or result.summary[:1000]
            )
    finally:
        data.close()
        flush_langfuse()
    kinds = Counter(e["payload"]["kind"] for e in events)
    assert kinds["model"] >= 2 and kinds["tool"] >= 4
    auth = (os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])
    async with httpx.AsyncClient(
        base_url=os.environ["LANGFUSE_BASE_URL"], auth=auth, timeout=10
    ) as client:
        observations = []
        for _ in range(15):
            response = await client.get(f"/api/public/traces/{trace.trace_id}")
            if response.status_code == 200:
                observations = response.json().get("observations", [])
                counts = Counter(o.get("type") for o in observations)
                if (
                    counts["GENERATION"] >= kinds["model"] // 2
                    and counts["TOOL"] >= kinds["tool"] // 2
                    and counts["AGENT"] >= 2
                ):
                    break
            await asyncio.sleep(2)
        assert any(o.get("type") == "GENERATION" for o in observations), (
            "No generation ingested"
        )
        assert counts["GENERATION"] >= kinds["model"] // 2, "Missing generations"
        assert counts["TOOL"] >= kinds["tool"] // 2 and counts["AGENT"] >= 2, (
            "Missing tool/agent spans"
        )
        projects = (await client.get("/api/public/projects")).json()["data"]
    safe = {
        "run_id": run_id,
        "trace_id": trace.trace_id,
        "provider": model.agent_mode,
        "projects": [{"id": p["id"], "name": p["name"]} for p in projects],
        "activity_counts": dict(kinds),
        "observation_counts": dict(Counter(o.get("type") for o in observations)),
        "observations": [
            {k: o.get(k) for k in ("name", "type", "startTime", "parentObservationId")}
            for o in observations
        ],
        "events": events,
    }
    directory = Path("data/live-validation/agent-activity")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{run_id}.json").write_text(
        json.dumps(safe, ensure_ascii=False, indent=2)
    )
    print(
        json.dumps(
            {k: v for k, v in safe.items() if k not in {"events", "observations"}},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
