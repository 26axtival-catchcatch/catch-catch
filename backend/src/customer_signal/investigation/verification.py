"""Small, recoverable verification context; evidence stays in the run data store."""

from __future__ import annotations

import json
from hashlib import sha256

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

VERIFIER_CONCURRENCY = 6
VERIFIER_CONTEXT_BYTES = 96_000
VERIFIER_PREVIEW_ROWS = 20


class VerificationContextLimit(RuntimeError):
    code = "verification_context_limit"


def verifier_task_id(candidate_id: str, round_index: int) -> str:
    return f"task-verification-{round_index}-{sha256(candidate_id.encode()).hexdigest()[:16]}"


def compact_measurement(value: dict) -> dict:
    return {
        k: v
        for k, v in value.items()
        if k
        not in {
            "queries",
            "query_results",
            "cohort_customer_ids",
            "source_versions",
        }
    }


def tool_preview(name: str, output: dict) -> dict:
    if name == "measure_signal":
        return compact_measurement(output)
    if name == "query_data" and "query_id" in output:
        rows = output.get("rows", [])[:VERIFIER_PREVIEW_ROWS]
        return {k: v for k, v in output.items() if k not in {"sql", "rows", "truncated"}} | {
            "rows": rows,
            "truncated": output.get("row_count", len(rows)) > len(rows),
            "next_offset": len(rows) if output.get("row_count", 0) > len(rows) else None,
            "instruction": "Full rows remain server-side. Use read_query_result(query_id, offset, limit) for evidence beyond this preview. Reading an existing query never grants independent ownership.",
        }
    return output


def recheck_candidate(data, context: dict) -> dict:
    """Batch mechanical checks under the caller's owner; never produce a verdict."""
    candidates = context.get("candidates", [])
    if len(candidates) != 1:
        raise ValueError("exactly one verification assignment is required")
    candidate = candidates[0]
    results = {}
    for original_id in dict.fromkeys(
        [candidate["cohort_query_id"], *candidate["evidence_query_ids"]]
    ):
        try:
            value = data.query(
                data.queries[original_id]["sql"],
                preview_limit=VERIFIER_PREVIEW_ROWS,
                expose_cohort=True,
            )
            results[original_id] = tool_preview("query_data", value) | {
                "original_query_id": original_id
            }
        except Exception:
            results[original_id] = {"original_query_id": original_id, "error": "query_failed"}
    journeys = []
    for customer_id in candidate["representative_customer_ids"]:
        try:
            journeys.append(data.journey(customer_id))
        except Exception:
            journeys.append({"customer_id": customer_id, "error": "journey_failed"})
    workbench = getattr(data, "signal_workbench", None)
    measurement = None
    if workbench is not None:
        try:
            measurement = compact_measurement(
                workbench.measure(workbench.proposals[candidate["candidate_id"]])
            )
        except Exception:
            measurement = {"error": "measurement_failed"}
    # Return each successful sub-result even after a later failure. A credited
    # journey must not disappear behind a generic bundle error.
    return {
        "candidate_id": candidate["candidate_id"],
        "cohort": results[candidate["cohort_query_id"]],
        "evidence": [results[q] for q in candidate["evidence_query_ids"]],
        "journeys": journeys,
        "measurement": measurement,
        "instruction": "Mechanical replay is not a verdict. Inspect SQL semantics and counterexamples. Reuse cohort_table in SELECT/JOIN instead of rewriting the cohort SQL. These task-owned tables contain the full customer set, not just preview rows. Never use temporary cohort tables in reusable signal definitions.",
    }


def _reference(value: dict) -> dict:
    if "cohort" in value and "journeys" in value:
        return {
            "candidate_id": value["candidate_id"],
            "cohort": _reference(value["cohort"]),
            "evidence": [_reference(q) for q in value["evidence"]],
            "journeys": [_reference(j) for j in value["journeys"]],
            "measurement": compact_measurement(value["measurement"])
            if value.get("measurement")
            else None,
        }
    if "query_id" in value:
        reference = {
            k: value[k]
            for k in (
                "query_id",
                "row_count",
                "columns",
                "owner",
                "snapshot_id",
                "error",
                "offset",
                "next_offset",
                "truncated",
                "original_query_id",
                "cohort_table",
            )
            if k in value
        }
        rows = value.get("rows")
        if (
            rows is not None
            and len(json.dumps(rows, ensure_ascii=False, default=str).encode()) <= 2048
        ):
            reference["rows"] = rows
        return reference
    if "customer_id" in value:
        reference = {
            k: value[k]
            for k in ("customer_id", "total_events", "error", "truncated", "window")
            if k in value
        }
        events = value.get("events")
        if (
            events is not None
            and len(json.dumps(events, ensure_ascii=False, default=str).encode()) <= 2048
        ):
            reference["events"] = events
        return reference
    if "measurement_id" in value:
        return compact_measurement(value)
    return {k: value[k] for k in ("error", "status", "candidate_id") if k in value}


def message_bytes(messages: list[BaseMessage]) -> int:
    # Conservative content envelope, not a model-specific token estimate. The tool
    # schema is fixed and is not included in this application-content budget.
    return sum(
        len(
            json.dumps(
                {"content": m.content, "tool_calls": getattr(m, "tool_calls", [])},
                ensure_ascii=False,
                default=str,
            ).encode()
        )
        for m in messages
    )


def bound_messages(
    messages: list[BaseMessage], budget: int = VERIFIER_CONTEXT_BYTES
) -> list[BaseMessage]:
    bounded = list(messages)
    if message_bytes(bounded) <= budget:
        return bounded
    # Keep the assignment intact and tool-call/result pairs intact. Old row bodies
    # are recoverable by ID; never summarize them into invented semantic claims.
    # The latest AI response can request multiple tools. None of those results
    # has reached the model yet, so protect the entire batch, not just its tail.
    latest_response = max((i for i, m in enumerate(bounded) if isinstance(m, AIMessage)), default=0)
    for i, m in enumerate(bounded[:latest_response]):
        if isinstance(m, ToolMessage):
            try:
                value = json.loads(str(m.content))
            except ValueError:
                continue
            if not isinstance(value, dict) or value.get("error"):
                continue
            if "query_id" in value:
                summary = _reference(value)
                summary["instruction"] = "Full SQL and rows remain available via read_query_result."
            elif "customer_id" in value and "events" in value:
                summary = _reference(value)
                summary["instruction"] = "Full journey remains available via customer_journey."
            elif "measurement_id" in value:
                summary = compact_measurement(value)
            elif "cohort" in value and "journeys" in value:
                summary = _reference(value)
                summary["instruction"] = (
                    "Archived evidence: recover SQL/rows with read_query_result and journeys with customer_journey."
                )
            else:
                continue
            bounded[i] = m.model_copy(update={"content": json.dumps(summary, ensure_ascii=False)})
        elif isinstance(m, AIMessage) and m.tool_calls:
            bounded[i] = m.model_copy(update={"content": ""})
        if message_bytes(bounded) <= budget:
            return bounded
    # Old SQL arguments can themselves fill the envelope. Replace complete,
    # already delivered exchanges with references, removing both halves of every
    # tool pair. Keep the original system/assignment and current batch intact.
    references = []
    for m in bounded[2:latest_response]:
        if isinstance(m, ToolMessage):
            try:
                value = json.loads(str(m.content))
            except ValueError:
                continue
            if isinstance(value, dict):
                references.append({"tool": m.name, **_reference(value)})
        elif isinstance(m, HumanMessage):
            try:
                value = json.loads(str(m.content))
            except ValueError:
                continue
            if isinstance(value, dict):
                references.extend(value.get("archived_observations", []))
    archive = HumanMessage(
        content=json.dumps(
            {
                "archived_observations": references,
                "instruction": "These completed results were previously delivered. Recover full SQL/rows by read_query_result(query_id); recover journeys by customer_journey(customer_id). Ownership is unchanged. Re-measure if more measurement detail is needed.",
            },
            ensure_ascii=False,
        )
    )
    compact = bounded[:2] + [archive] + bounded[latest_response:]
    if latest_response >= 2 and message_bytes(compact) <= budget:
        return compact
    raise VerificationContextLimit("검증 컨텍스트 한도에 도달해 이 후보를 확정하지 않았습니다.")
