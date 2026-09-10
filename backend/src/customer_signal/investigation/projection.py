"""Project verified investigation results onto the unchanged v1 FE contracts."""

from datetime import datetime, timezone
from uuid import uuid4

from customer_signal.agent.claim_validator import render_verified_note
from customer_signal.agent.contracts import GenericRunnerOutcome
from customer_signal.domain.analysis import (
    AnalysisGoal,
    AnalysisNoteDraft,
    AnalysisPlan,
    AnalysisStep,
    ClaimDraft,
    ContinueAfterStep,
    ExpectedOutputSpec,
    FactRef,
    MeasureSpec,
    PopulationSpec,
    StepLimits,
)
from customer_signal.domain.facts import (
    AggregateEventsPayload,
    AnalysisJourneyEvent,
    AnalysisMaskedEvidence,
    AnalysisMetricFact,
    AnalysisSourceCatalogFact,
    CatalogSourcesPayload,
    CustomerJourneyPayload,
    EvidencePayload,
    FactProvenance,
    ProcessingStats,
    build_fact,
)
from customer_signal.domain.primitives import (
    AggregateEventsInput,
    CatalogSourcesInput,
    GetCustomerJourneyInput,
    GetEvidenceInput,
)
from customer_signal.domain.reports import (
    AnalysisFinding,
    AnalysisRecommendation,
    AnalysisReportProvenance,
    CustomerSignalReport,
)
from customer_signal.domain.sources import EventScope, TimeRange


def goal_and_plan(request):
    goal = AnalysisGoal(
        goal_id="goal-journey-investigation",
        objective=request.question,
        population=PopulationSpec(
            entity="customers", description="선택한 기간과 데이터 공간의 고객"
        ),
        time_range=TimeRange(start_at=request.start_at, end_at=request.end_at),
        source_ids=request.enabled_sources,
        measures=[
            MeasureSpec(
                metric_key="verified_customer_count",
                label="헤맨 여정이 확인된 고객",
                aggregation="distinct_count",
                unit="명",
            )
        ],
        output="journey",
    )
    steps = []
    for step_id, primitive, parameters, dependencies, metric, reason in (
        (
            "catalog",
            "catalog_sources",
            CatalogSourcesInput(primitive="catalog_sources"),
            [],
            "source_count",
            "현재 데이터 공간을 확인합니다.",
        ),
        (
            "investigate",
            "aggregate_events",
            AggregateEventsInput(
                primitive="aggregate_events", aggregation="count", time_grain="day"
            ),
            [],
            "candidate_customer_count",
            "가설별로 전체 공간을 조사하고 고객의 의도와 여정을 연결합니다.",
        ),
        (
            "verify",
            "aggregate_events",
            AggregateEventsInput(
                primitive="aggregate_events", aggregation="count", time_grain="day"
            ),
            [],
            "verified_customer_count",
            "정상 탐색 반례와 최종 해결을 독립적으로 확인하고 필요하면 재조사합니다.",
        ),
        (
            "journeys",
            "get_customer_journey",
            GetCustomerJourneyInput(primitive="get_customer_journey", limit=20),
            ["step-investigate"],
            "journey_event_count",
            "대표 고객의 실제 여정을 확인합니다.",
        ),
        (
            "evidence",
            "get_evidence",
            GetEvidenceInput(primitive="get_evidence", limit=20),
            ["step-journeys"],
            "evidence_record_count",
            "검증된 근거와 개선 제안을 보고서로 정리합니다.",
        ),
    ):
        steps.append(
            AnalysisStep(
                step_id="step-" + step_id,
                primitive=primitive,
                parameters=parameters,
                source_ids=request.enabled_sources,
                input_step_ids=dependencies,
                expected_output=ExpectedOutputSpec(
                    payload_kind=primitive, required_metric_keys=[metric]
                ),
                stop_condition=ContinueAfterStep(),
                limits=StepLimits(
                    max_input_events=10000,
                    max_output_rows=100,
                    max_evidence=20,
                    timeout_seconds=40.0,
                ),
                selection_reason=reason,
            )
        )
    return goal, AnalysisPlan(
        plan_id="plan-journey-investigation",
        revision=0,
        goal_id=goal.goal_id,
        steps=steps,
        rationale="총괄의 가설 배분, 병렬 조사, 독립 검증과 재조사, 근거 기반 보고를 진행합니다.",
    )


class InvestigationProjection:
    def __init__(self, data, goal, plan):
        self.data, self.goal, self.plan = data, goal, plan
        self.scope = EventScope(
            source_ids=data.request.enabled_sources,
            start_at=data.request.start_at,
            end_at=data.request.end_at,
            max_events=10000,
        )
        versions = {m.source_id: m for m in data.manifests}
        self.provenance = FactProvenance(
            scope=self.scope,
            source_ids=self.scope.source_ids,
            adapter_versions={
                s: versions[s].adapter_version if s in versions else "test"
                for s in self.scope.source_ids
            },
            manifest_versions={
                s: versions[s].manifest_version if s in versions else "test"
                for s in self.scope.source_ids
            },
            dataset_version=data.snapshot_id,
        )
        self.facts, self.notes = [], []

    def add(self, payload, step, *, claim=False):
        fact = build_fact(
            fact_id="fact-" + uuid4().hex[:24],
            result_id="result-" + uuid4().hex[:24],
            step_id="step-" + step,
            primitive=payload.kind,
            payload=payload,
            scope=self.scope,
            created_at=datetime.now(timezone.utc),
        )
        self.facts.append(fact)
        claims = []
        if claim:
            metric = payload.metrics[0]
            claims = [
                ClaimDraft(
                    claim_type="metric",
                    subject=metric.metric_key,
                    operator="eq",
                    target=metric.value,
                    fact_refs=[FactRef(fact_id=fact.fact_id, metric_key=metric.metric_key)],
                )
            ]
        self.notes.append(
            render_verified_note(
                AnalysisNoteDraft(step_id=fact.step_id, claims=claims), fact, duration_ms=0
            )
        )
        return fact, self.notes[-1]

    def base(self, metrics, rows=1):
        # This projection reads already materialized results; it performs no raw event scan.
        # The complete scan and query counts are in the run's investigation audit artifact.
        return dict(
            provenance=self.provenance,
            processing=ProcessingStats(scanned_events=0, matched_events=0, returned_rows=rows),
            metrics=metrics,
        )

    def metric(self, key, label, value, unit="명"):
        return AnalysisMetricFact(metric_key=key, label=label, value=value, unit=unit)

    def catalog(self):
        tables = self.data.catalog()["tables"]
        payload = CatalogSourcesPayload(
            kind="catalog_sources",
            sources=[
                AnalysisSourceCatalogFact(
                    source_id=t["source_id"],
                    data_interval=self.goal.time_range,
                    row_count=t["event_count"],
                    manifest_version=self.provenance.manifest_versions[t["source_id"]],
                )
                for t in sorted(tables, key=lambda t: t["source_id"])
            ],
            **self.base(
                [self.metric("source_count", "조사 데이터 소스", len(tables), "개")], len(tables)
            ),
        )
        return self.add(payload, "catalog")

    def finish(self, *, candidates, decisions, narrative, limitations, model_name, agent_mode="gemini"):
        decision_by_id = {d.candidate_id: d for d in decisions}
        confirmed, pending, verified_customers = [], [], set()
        for candidate in candidates:
            decision = decision_by_id.get(candidate.candidate_id)
            if decision is None or decision.verdict in {"candidate", "reinvestigate"}:
                pending.append(candidate)
                reason = decision.reason if decision else "독립 검증이 완료되지 않았습니다."
                limitations.append(f"미확정 후보 [{candidate.title}]: {reason}"[:500])
            elif decision.verdict == "confirmed":
                ids = self.data.cohort(decision.cohort_query_id or candidate.cohort_query_id)
                if ids:
                    verified_customers.update(ids)
                    confirmed.append((candidate, decision, ids))
        findings, recommendations, journeys, ranked = [], [], [], []
        published_customers = set()
        published_details = {}
        for index, (candidate, decision, ids) in enumerate(confirmed):
            metric = self.metric(f"pattern_{index}_customer_count", candidate.title, len(ids))
            fact, note = self.add(
                AggregateEventsPayload(
                    kind="aggregate_events",
                    requested_metric_key=metric.metric_key,
                    **self.base([metric]),
                ),
                "verify",
                claim=True,
            )
            evidence_ids, supporting_facts = [], [fact.fact_id]
            for customer_id in candidate.representative_customer_ids:
                if customer_id not in ids:
                    continue
                if customer_id in published_details:
                    prior_fact_ids, prior_evidence_ids = published_details[customer_id]
                    supporting_facts.extend(prior_fact_ids)
                    evidence_ids.extend(prior_evidence_ids)
                    continue
                original = self.data.journey(customer_id)
                raw = original["events"]
                if original["total_events"] > 20:
                    raw = raw[:10] + raw[-10:]
                    limitations.append(
                        "대표 여정은 최대 20개 이벤트로 표시합니다. 전체 여정은 조사 기록에서 확인할 수 있습니다."
                    )
                public = [
                    AnalysisJourneyEvent(**{k: r[k] for k in AnalysisJourneyEvent.model_fields})
                    for r in raw
                ]
                journey_fact = None
                if len(published_customers) < 5:
                    published_customers.add(customer_id)
                    journey_fact, _ = self.add(
                        CustomerJourneyPayload(
                            kind="get_customer_journey",
                            customer_id=customer_id,
                            events=public,
                            **self.base(
                                [
                                    self.metric(
                                        "journey_event_count", "대표 여정 이벤트", len(public), "건"
                                    )
                                ],
                                len(public),
                            ),
                        ),
                        "journeys",
                    )
                    journeys.extend(public)
                else:
                    limitations.append(
                        "보고서 대표 여정은 최대 5명이며, 다른 확정 패턴의 근거는 Evidence로 제공합니다."
                    )
                records = [
                    AnalysisMaskedEvidence(
                        evidence_id=r["evidence_id"],
                        source_id=r["source_id"],
                        occurred_at=r["occurred_at"],
                        masked_customer_id=customer_id,
                        summary=f"{r['action']}: {r['text']}"[:1000],
                    )
                    for r in raw
                ]
                evidence_fact, _ = self.add(
                    EvidencePayload(
                        kind="get_evidence",
                        records=records,
                        **self.base(
                            [
                                self.metric(
                                    "evidence_record_count", "확인한 근거", len(records), "건"
                                )
                            ],
                            len(records),
                        ),
                    ),
                    "evidence",
                )
                detail_fact_ids = ([journey_fact.fact_id] if journey_fact else []) + [
                    evidence_fact.fact_id
                ]
                detail_evidence_ids = [r.evidence_id for r in records]
                published_details[customer_id] = (detail_fact_ids, detail_evidence_ids)
                supporting_facts.extend(detail_fact_ids)
                evidence_ids.extend(detail_evidence_ids)
            evidence_ids = list(dict.fromkeys(evidence_ids))[:20]
            findings.append(
                AnalysisFinding(
                    claim=note.claims[0],
                    statement=f"{note.claims[0].rendered_text}. {decision.reason}"[:500],
                    fact_ids=supporting_facts,
                    evidence_ids=evidence_ids,
                )
            )
            recommendations.append(
                AnalysisRecommendation(
                    action_id=f"improve_pattern_{index}",
                    title=candidate.recommendation[:200] or "고객 여정의 진입점을 개선합니다.",
                    reason=f"개선 가설입니다. {candidate.behavior_evidence}"[:500],
                    claim_ids=[note.claims[0].claim_id],
                    fact_ids=supporting_facts,
                    evidence_ids=evidence_ids,
                )
            )
        aggregate = self.metric(
            "verified_customer_count",
            "헤맨 여정이 확인된 고객 (중복 제외)",
            len(verified_customers),
        )
        self.add(
            AggregateEventsPayload(
                kind="aggregate_events",
                requested_metric_key=aggregate.metric_key,
                **self.base([aggregate]),
            ),
            "verify",
        )
        candidate_ids = set()
        for candidate in pending:
            candidate_ids.update(self.data.cohort(candidate.cohort_query_id))
        candidate_metric = self.metric(
            "candidate_customer_count", "미확정 후보 고객 (확정과 중복 가능)", len(candidate_ids)
        )
        self.add(
            AggregateEventsPayload(
                kind="aggregate_events",
                requested_metric_key=candidate_metric.metric_key,
                **self.base([candidate_metric]),
            ),
            "investigate",
        )
        limits = list(dict.fromkeys(text[:500] for text in limitations if text))[:32]
        report = CustomerSignalReport(
            goal=self.goal,
            headline=narrative.headline,
            executive_summary=(
                f"확정 {len(verified_customers)}명, 미확정 후보 {len(candidate_ids)}명입니다. "
                + narrative.summary
            )[:2000],
            metrics=[
                aggregate,
                candidate_metric,
                *[
                    f.metrics[0]
                    for f in self.facts
                    if f.metrics[0].metric_key.startswith("pattern_")
                ],
            ],
            ranked_customers=ranked,
            representative_journeys=journeys,
            findings=findings,
            recommendations=recommendations[:16],
            limitations=limits,
            provenance=AnalysisReportProvenance(
                fact_ids=[f.fact_id for f in self.facts],
                result_ids=[f.result_id for f in self.facts],
                source_ids=self.scope.source_ids,
                dataset_versions=[self.data.snapshot_id],
                adapter_versions=self.provenance.adapter_versions,
                manifest_versions=self.provenance.manifest_versions,
            ),
        )
        return GenericRunnerOutcome(
            status="completed",
            goal=self.goal,
            plan=self.plan,
            facts=self.facts,
            notes=self.notes,
            report=report,
            limitations=limits,
            agent_mode=agent_mode,
            model=model_name,
        )
