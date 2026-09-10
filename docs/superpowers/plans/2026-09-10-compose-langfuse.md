# App and Langfuse Compose implementation plan

**Goal:** Run the application and its own Langfuse stack locally and verify a fresh application trace through the Langfuse API.

**Architecture:** One Compose project contains a same-origin reverse proxy, Next.js, a single FastAPI worker, and Langfuse web/worker with PostgreSQL, ClickHouse, Redis, and MinIO. Named volumes preserve application and telemetry data. Existing local services remain separate.

**Tech stack:** Docker Compose, Python 3.12/uv, Next.js standalone, nginx, Langfuse.

- [x] Package backend and frontend using lockfiles and explicit build contexts that exclude secrets and local data.
- [x] Add Compose, health checks, local resource settings, persistent volumes, proxy streaming, and idempotent private environment initialization.
- [x] Build and start the project; verify health, UI, synthetic analysis, SSE replay, downloads, fresh trace identity/metadata, and persistence after restart. Use fixture when provider credentials are absent; identify that limitation explicitly.
- [x] Record reproducible commands and verification evidence, review the changes, and leave the working services accessible locally.

Results: `docs/verification/local-compose.md`. The root UI is an existing static prototype; the actual API-connected browser smoke used `/legacy`. Initial verification used fixture. After the user supplied the root environment file, 44 Bedrock generation spans were ingested with stage/provider/run_id metadata and workflow ancestry. Two calls (verifier/reporter) returned InternalServerException, so analysis used a partial result despite terminal status completed. Verification now distinguishes successful ingestion from partial model execution and exits nonzero on generation errors. The backend remains in Bedrock mode.

## Verification contract

`python3 scripts/compose.py init`, `up`, `verify`, `ps`, and `down` provide the local workflow. Initialization never overwrites the source environment file or prints credentials. Re-running it preserves Langfuse initialization keys and passwords. Verification exits nonzero on a failed run, missing SSE result, or missing trace/span metadata and writes only public metadata under the ignored local directory. Runtime environment inspection checks that frontend receives no provider or tracing secrets. The API's endpoint contracts remain unchanged.
