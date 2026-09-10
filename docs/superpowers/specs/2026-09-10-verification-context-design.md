# Bounded independent verification

The approved direction is to retain verification capability while splitting its context and reducing the serial bottleneck. The baseline run f9d10f57-5e90-4ee6-ac3d-1c2e175b42b3 used one verifier for six candidates, 401 seconds, and up to 178,822 input tokens.

Each candidate receives a separate verifier task with a unique query owner, at most three tasks concurrently. A task receives one complete candidate, its referenced SQL with bounded previews, and only its own signal definition and compact measurement summary. All authorized source tables remain queryable for normal counterexamples and cross-source checks. Candidate IDs are not inferred from domain names.

The verifier can call `recheck_candidate` to execute its assigned SQL, retrieve representative journeys, and independently remeasure the signal in one request. This is mechanical evidence collection, not an automatic verdict. It must still judge SQL semantics and gather normal counterexamples or correct the cohort as needed. Partial failures retain all successful sub-results in the delivered response.

Full query results remain on the server. A paged read tool returns additional rows without granting ownership of the original query. Previews and pages contain at most 20 rows. Older delivered tool response bodies are replaced by reference metadata; complete delivered batches can also be archived to remove accumulated SQL arguments. The latest tool batch is never compacted before the model receives it. Verification finish must be submitted separately from data tools; query IDs and full original results remain available. A UTF-8 request-content budget bounds verifier input; exceeding it fails that candidate closed rather than skipping verification. The budget is a byte limit, not an exact tokenizer estimate.

Independent cohort SQL, independently owned evidence, representative journey reads, and matching independent signal measurements remain mandatory for confirmation. Failures are isolated per candidate, completed siblings survive cancellation, and only changed candidates are reverified after follow-up. Server-side union aggregation remains authoritative across candidates.

Bedrock verifier selection gets its own optional setting. Preserve Opus by default. Probe Haiku tool calling before a saved-evidence verification comparison; only select it locally if behavioral checks pass. Do not assume model availability implies equivalent verification quality.

This change does not alter HTTP schemas or repair the separately identified frontend event decoder and report narrative errors. Semantic verification instructions explicitly check feedback/cohort attribution, temporal order, normal counterexamples and resolution status.
