"""Replay saved synthetic investigation candidates; invoke only the real verifier.

No new investigation/report model calls, signal registration, or external messages.
Reinvestigate decisions are recorded verbatim and treated as pending for this one-pass
benchmark. This is a verifier comparison, not an end-to-end report quality test.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from compose import LOCAL, ROOT, read_env


def prepare_env():
    selected = read_env(LOCAL / "backend.env")
    for key in list(os.environ):
        if key.startswith(("LANGSMITH_", "LANGCHAIN_", "LANGFUSE_")):
            os.environ.pop(key)
    os.environ.update(selected)
    os.environ["LANGFUSE_BASE_URL"] = read_env(LOCAL / "stack.env")["LANGFUSE_URL"]


async def benchmark(args):
    # Selected environment must precede LangChain/Langfuse imports.
    prepare_env()
    from customer_signal.config import Settings
    from customer_signal.agent.contracts import RunRequest
    from customer_signal.data.source_registry import SourceRegistry
    from customer_signal.onboarding.adapter import (
        CompositeEvidenceProvider,
        load_onboarded_adapters,
    )
    from customer_signal.investigation.data import InvestigationData, query_owner
    from customer_signal.investigation.model import BedrockInvestigationModel
    from customer_signal.investigation.runner import InvestigationRunner
    import customer_signal.investigation.runner as runner_module
    from customer_signal.investigation.verification import message_bytes
    from customer_signal.signals.contracts import SignalDefinition, Measurement
    from customer_signal.signals.store import SignalStore
    from customer_signal.observability.langfuse import (
        LangfuseRunContext,
        bind_langfuse_run,
        flush_langfuse,
        update_langfuse_workflow,
    )

    settings = Settings(_env_file=None)
    if args.concurrency is not None:
        # Isolated benchmark process override; the running API is unaffected.
        runner_module.VERIFIER_CONCURRENCY = args.concurrency
    original = json.loads(args.artifacts.joinpath("investigation.json").read_text())
    proposals = json.loads(args.artifacts.joinpath("proposals.json").read_text())[
        "items"
    ]
    sources = ROOT / "data/seeding/hackathon-2week/onboarded-sources"
    source_ids = sorted(p.name for p in sources.iterdir() if p.is_dir())
    request = RunRequest.model_validate(
        original["request"] | {"enabled_sources": source_ids}
    )
    adapters = load_onboarded_adapters(sources)
    registry = SourceRegistry(
        adapters, evidence=CompositeEvidenceProvider(None, adapters)
    )
    run_id = str(uuid4())
    directory = LOCAL / f"verifier-benchmark-{run_id}"
    directory.mkdir(mode=0o700)
    calls, feedback, raw_decisions = [], [], []
    verification_windows = []

    class MeasuredModel(BedrockInvestigationModel):
        async def _invoke_model(self, model_name, messages, **kw):
            started = time.monotonic()
            response = await super()._invoke_model(model_name, messages, **kw)
            calls.append(
                {
                    "task_id": kw["task_id"],
                    "seconds": round(time.monotonic() - started, 3),
                    "context_bytes": message_bytes(messages),
                    "model": model_name,
                    "usage": response.usage_metadata,
                }
            )
            return response

        async def _run_tool(self, **kw):
            output = await super()._run_tool(**kw)
            if isinstance(output, dict) and output.get("error"):
                feedback.append(
                    {
                        "task_id": kw["task_id"],
                        "tool": kw["name"],
                        "error": output["error"],
                        "issues": [i.get("problem") for i in output.get("issues", [])],
                    }
                )
            return output

    actual = MeasuredModel(
        api_key=settings.aws_bearer_token_bedrock.get_secret_value(),
        model=settings.bedrock_model,
        investigator_model=settings.bedrock_investigator_model,
        verifier_model=args.model,
        region=settings.aws_region,
        timeout_seconds=120,
    )

    class Replay:
        model_name = args.model
        agent_mode = "bedrock"

        async def run_role(self, **kw):
            kind = kw["role"]
            if kind == "verifier":
                phase_started = time.monotonic()
                try:
                    result = await actual.run_role(**kw)
                finally:
                    verification_windows.append((phase_started, time.monotonic()))
                raw_decisions.extend(
                    d.model_dump(mode="json") for d in result.decisions
                )
                return result.model_copy(
                    update={
                        "decisions": [
                            d.model_copy(
                                update={
                                    "verdict": "candidate",
                                    "reason": "One-pass benchmark: " + d.reason[:900],
                                }
                            )
                            if d.verdict == "reinvestigate"
                            else d
                            for d in result.decisions
                        ]
                    }
                )
            if kind == "coordinator":
                result = {
                    "tasks": [{"task_id": "task-replay", "question": request.question}],
                    "summary": "저장된 합성 후보의 독립 검증 비교",
                }
            elif kind == "investigator":
                data = kw["data"]
                records = {q["query_id"]: q for q in original["queries"]}
                referenced = {
                    q
                    for c in original["candidates"]
                    for q in [c["cohort_query_id"], *c["evidence_query_ids"]]
                }
                mapping = {
                    q: data.query(records[q]["sql"])["query_id"]
                    for q in sorted(referenced)
                }
                candidates = [
                    c
                    | {
                        "cohort_query_id": mapping[c["cohort_query_id"]],
                        "evidence_query_ids": [
                            mapping[q] for q in c["evidence_query_ids"]
                        ],
                    }
                    for c in original["candidates"]
                ]
                wb = data.signal_workbench
                # The investigator is replayed, including its already measured proposal.
                for p in proposals:
                    definition = SignalDefinition.model_validate(p["definition"])
                    measurement = Measurement.model_validate(p["measurement"])
                    wb.measurements[measurement.measurement_id] = (
                        query_owner.get(),
                        definition,
                        measurement,
                    )
                    wb.propose(p["candidate_id"], measurement.measurement_id)
                result = {"candidates": candidates, "limitations": []}
            else:
                result = {
                    "headline": "검증 단계 비교",
                    "summary": "원래 조사 후보를 한 번 독립 검증했습니다.",
                }
            return kw["result_type"].model_validate(result)

    async def emit(event):
        pass

    started = time.monotonic()
    with bind_langfuse_run(
        LangfuseRunContext(
            run_id=run_id,
            run_kind="generic",
            question=request.question,
            source_ids=tuple(request.enabled_sources),
        )
    ):
        outcome = await InvestigationRunner(
            model=Replay(),
            data_factory=lambda r: InvestigationData.load(registry, r),
            artifact_directory=directory,
            signal_store=SignalStore(directory / "signals.sqlite3"),
            investigation_seconds=570,
            total_seconds=600,
        ).run(request, emit=emit)
        update_langfuse_workflow(
            output={"status": outcome.status, "benchmark": "verifier-only"}
        )
    flush_langfuse()
    audit = json.loads(next((directory / "investigations").glob("*.json")).read_text())
    summary = {
        "run_id": run_id,
        "model": args.model,
        "concurrency": runner_module.VERIFIER_CONCURRENCY,
        "status": outcome.status,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "verification_seconds": round(
            max(end for _, end in verification_windows)
            - min(start for start, _ in verification_windows),
            3,
        )
        if verification_windows
        else 0,
        "calls": len(calls),
        "input_tokens": sum((c["usage"] or {}).get("input_tokens", 0) for c in calls),
        "max_input_tokens": max(
            ((c["usage"] or {}).get("input_tokens", 0) for c in calls), default=0
        ),
        "max_context_bytes": max((c["context_bytes"] for c in calls), default=0),
        "decisions": raw_decisions,
        "accepted_decisions": audit.get("decisions"),
        "verdict_counts": dict(Counter(d["verdict"] for d in raw_decisions)),
        "roles": [
            {
                k: r.get(k)
                for k in ("role", "task_id", "elapsed_seconds", "status", "error_code")
            }
            for r in audit["roles"]
        ],
        "feedback": feedback,
        "call_metadata": calls,
        "trace_url": f"http://localhost:3210/project/catch-catch-local/traces/{run_id.replace('-', '')}",
    }
    (directory / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "run_id",
                    "model",
                    "status",
                    "elapsed_seconds",
                    "verification_seconds",
                    "calls",
                    "max_input_tokens",
                    "max_context_bytes",
                    "verdict_counts",
                    "trace_url",
                )
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    print("summary_path", directory / "summary.json", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--concurrency", type=int, choices=range(1, 7))
    args = parser.parse_args()
    asyncio.run(benchmark(args))
