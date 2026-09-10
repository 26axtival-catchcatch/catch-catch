"""Replay saved synthetic assignments through real investigation and verification.

Launch with uv run --env-file <path> --project backend. Coordinator assignments and
report narration are fixed for comparison; no signal is registered. Only public
contracts and execution metadata are saved, never credentials or model messages.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path
from time import monotonic
from uuid import uuid4

from customer_signal.agent.contracts import RunRequest
from customer_signal.config import Settings
from customer_signal.data.source_registry import SourceRegistry
from customer_signal.investigation.data import InvestigationData
from customer_signal.investigation.model import BedrockInvestigationModel
from customer_signal.investigation.runner import InvestigationRunner
from customer_signal.observability.langfuse import (
    LangfuseRunContext,
    bind_langfuse_run,
    flush_langfuse,
    update_langfuse_workflow,
)
from customer_signal.onboarding.adapter import CompositeEvidenceProvider, load_onboarded_adapters
from customer_signal.signals.store import SignalStore


async def benchmark(args):
    original = json.loads(args.audit.read_text())
    request = RunRequest.model_validate(original["request"])
    coordination = next(r["result"] for r in original["roles"] if r["role"] == "coordinator")
    settings = Settings(_env_file=None)
    if settings.aws_bearer_token_bedrock is None:
        raise SystemExit("Bedrock credential is not configured")
    adapters = load_onboarded_adapters(args.sources)
    registry = SourceRegistry(adapters, evidence=CompositeEvidenceProvider(None, adapters))
    run_id = str(uuid4())
    directory = args.output / run_id
    directory.mkdir(parents=True, mode=0o700)
    calls, feedback, decisions = [], [], []

    class MeasuredModel(BedrockInvestigationModel):
        async def _invoke_model(self, model_name, messages, **kw):
            from customer_signal.investigation.verification import message_bytes

            started = monotonic()
            response = await super()._invoke_model(model_name, messages, **kw)
            calls.append({
                "role": kw["role"], "task_id": kw["task_id"],
                "seconds": round(monotonic() - started, 3),
                "context_bytes": message_bytes(messages), "model": model_name,
                "input_tokens": (response.usage_metadata or {}).get("input_tokens", 0),
                "output_tokens": (response.usage_metadata or {}).get("output_tokens", 0),
                "tool_count": len(response.tool_calls),
            })
            print(json.dumps(calls[-1]), flush=True)
            return response

        async def _run_tool(self, **kw):
            output = await super()._run_tool(**kw)
            if isinstance(output, dict) and output.get("error"):
                feedback.append({
                    "task_id": kw["task_id"], "tool": kw["name"], "error": output["error"],
                    "problems": [i.get("problem") for i in output.get("issues", [])],
                })
            return output

    actual = MeasuredModel(
        api_key=settings.aws_bearer_token_bedrock.get_secret_value(),
        model=settings.bedrock_model,
        investigator_model=settings.bedrock_investigator_model,
        verifier_model=settings.bedrock_verifier_model,
        region=settings.aws_region,
        timeout_seconds=120,
    )

    class Replay:
        model_name = actual.model_name
        agent_mode = "bedrock"

        async def run_role(self, **kw):
            if kw["role"] == "coordinator":
                return kw["result_type"].model_validate(coordination)
            if kw["role"] == "reporter":
                return kw["result_type"].model_validate({
                    "headline": "조사 성능 비교", "summary": "합성 조사 결과의 독립 검증을 확인합니다."
                })
            result = await actual.run_role(**kw)
            if kw["role"] == "verifier":
                decisions.extend(d.model_dump(mode="json") for d in result.decisions)
                # One-pass comparison: record requests for more evidence verbatim,
                # and keep them pending rather than triggering a different workload.
                result = result.model_copy(update={"decisions": [
                    d.model_copy(update={"verdict": "candidate"})
                    if d.verdict == "reinvestigate" else d for d in result.decisions
                ]})
            return result

    async def emit(event):
        pass

    print(json.dumps({"run_id": run_id, "directory": str(directory)}), flush=True)
    started = monotonic()
    with bind_langfuse_run(LangfuseRunContext(
        run_id=run_id, run_kind="generic", question=request.question,
        source_ids=tuple(request.enabled_sources),
    )):
        outcome = await InvestigationRunner(
            model=Replay(), data_factory=lambda r: InvestigationData.load(registry, r),
            artifact_directory=directory, signal_store=SignalStore(directory / "signals.sqlite3"),
            investigation_seconds=720, total_seconds=750,
        ).run(request, emit=emit)
        update_langfuse_workflow(output={
            "status": outcome.status, "benchmark": "saved-investigation-assignments",
        })
    elapsed = monotonic() - started
    flush_langfuse()
    audit = json.loads(next((directory / "investigations").glob("*.json")).read_text())
    summary = {
        "run_id": run_id, "baseline_run_id": original["run_id"],
        "status": outcome.status, "elapsed_seconds": round(elapsed, 3),
        "coordinator_and_reporter_replayed": True, "verification_passes": 1,
        "roles": [{k: r.get(k) for k in (
            "role", "task_id", "elapsed_seconds", "status", "error_code"
        )} for r in audit["roles"]],
        "calls": calls, "feedback": feedback, "raw_decisions": decisions,
        "verdict_counts": dict(Counter(d["verdict"] for d in decisions)),
        "candidate_count": len(audit.get("candidates", [])),
        "finding_count": len(outcome.report.findings) if outcome.report else 0,
    }
    (directory / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k not in {"calls", "raw_decisions"}},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(benchmark(parser.parse_args()))
