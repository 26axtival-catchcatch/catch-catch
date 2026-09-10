# Verification Context Implementation Plan

> Execute inline with test-driven development; the user has authorized the implementation direction.

**Goal:** Split verification into bounded independent tasks without weakening confirmation gates.
**Architecture:** One candidate per verifier, concurrency six, filtered handoff, recoverable result previews, compact history and a request-content budget. Keep server ownership checks and independent measurements.
**Tech Stack:** Python, asyncio, Pydantic, DuckDB, LangChain, Bedrock, pytest.

- [x] Add regression cases in backend/tests/test_verification_context.py and test_investigation_runner.py: candidate isolation, concurrent execution, failure isolation, sibling query rejection, follow-up targeting, bounded/recoverable query previews, context limit and model role selection. Run targeted pytest and observe failure before implementation.
- [x] Implement context helpers in backend/src/customer_signal/investigation/verification.py; integrate candidate workers in runner.py, query paging in data.py/model.py, and filtered signal handoffs in workbench.py. Re-run targeted tests and preserve existing confirmation tests.
- [x] Add optional BEDROCK_VERIFIER_MODEL through config.py, api.py, model.py and scripts/compose.py; test default routing and override independently.
- [x] Run investigation, signal and Bedrock regression suites plus ruff and git diff --check. Replay saved synthetic candidates through the new verifier, compare latency/context and decisions against baseline. Rebuild/restart the local backend after passing checks.
- [x] Record measured results and remaining limitations; retain raw provider content and credentials outside all outputs.

Observed during live evaluation: five-row previews increased model round trips, and retained old SQL arguments exhausted one task. Added twenty-row previews, reference archives for complete delivered batches, and a verifier-only bundled recheck tool. Confirmation gates remain authoritative; failed sub-steps return their successful evidence without granting measurement confirmation.

Final measurement: maximum input 178,822 → 38,386 tokens; verification 400.632 → 436.304 seconds. Context reduction is verified; latency and cost improvement are not achieved. See docs/verification/verification-context.md for evidence and limitations.
