"""Read only Signal spans through the configured local Langfuse MCP server."""

import argparse
import asyncio
import json
import os
import tempfile
import tomllib
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path.home() / ".codex/config.toml")
    parser.add_argument("--server", default="langfuse_local")
    parser.add_argument("--trace-id")
    parser.add_argument("--backend-credentials", action="store_true",
                        help="Use LANGFUSE_* from the process environment for the Backend project")
    parser.add_argument("--age", type=int, default=180)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cfg = tomllib.loads(args.config.read_text())["mcp_servers"][args.server]
    environment = {**os.environ, **cfg.get("env", {})}
    if args.backend_credentials:
        for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"):
            if not os.environ.get(key):
                raise RuntimeError("Backend Langfuse environment is incomplete")
            environment[key] = os.environ[key]
    parameters = StdioServerParameters(
        command=cfg["command"], args=cfg.get("args", []),
        env=environment,
    )
    query = {"type": "SPAN", "age": args.age, "name": "customer_signal.signal",
             "limit": 100, "output_mode": "full_json_string"}
    if args.trace_id:
        query["trace_id"] = args.trace_id
    # The MCP process may log its configuration. Do not forward stderr or credentials.
    with tempfile.TemporaryFile(mode="w+") as errors:
        async with stdio_client(parameters, errlog=errors) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("fetch_observations", query)
                if result.isError:
                    raise RuntimeError("Langfuse MCP observation lookup failed")
                raw = (result.structuredContent or {}).get("result")
                if raw is None:
                    raw = next(item.text for item in result.content if item.type == "text")
                while isinstance(raw, str):
                    raw = json.loads(raw)
                observations = raw.get("data", []) if isinstance(raw, dict) else raw
    safe = []
    for observation in observations:
        metadata = observation.get("metadata") or {}
        safe.append({
            **{key: observation.get(key, observation.get(alias)) for key, alias in {
                "id": "id", "name": "name", "type": "type", "traceId": "trace_id",
                "parentObservationId": "parent_observation_id", "startTime": "start_time",
                "endTime": "end_time",
            }.items()},
            "metadata": {key: metadata.get(key) for key in (
                "entity_type", "operation", "signal_id", "proposal_id", "candidate_id",
                "task_id", "source_run_id", "run_id", "measurement_id"
            ) if key in metadata},
        })
    summary = {"server": args.server, "count": len(safe), "observations": safe}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
