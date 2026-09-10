import type {
  AnalysisFact,
  AnalysisPlan,
  CustomerSignalReport,
  JourneyEvent,
  PublicSourceList,
  SourceId,
} from "../../customer-intelligence/contracts";

import { STAGES } from "./mock";
import type {
  CatchReport,
  JourneyLane,
  JourneyNode,
  StageKey,
  StageTick,
  SourceOption,
} from "./types";

export const LIVE_START_AT = "2026-09-04T00:00:00+09:00";
// Reserve the following week of synthetic data for daily fast-forward analysis.
export const LIVE_END_AT = "2026-09-11T00:00:00+09:00";

/**
 * 시딩 Source가 함께 반환되면 기존 내장 Source 대신 시딩 Source만 활성화한다.
 * 백엔드는 전체 카탈로그를 유지하므로 Signal Catcher 화면에서 교체 정책을 적용한다.
 */
export function activeSourceListOf(sources: PublicSourceList): PublicSourceList {
  const seededSources = sources.items.filter((source) =>
    source.source_id.startsWith("hackathon_"),
  );
  return seededSources.length ? { items: seededSources } : sources;
}

export function sourceLabelsOf(sources: PublicSourceList): Record<SourceId, string> {
  return Object.fromEntries(
    sources.items.map((source) => [source.source_id, source.label]),
  );
}

export function sourceOptionsOf(sources: PublicSourceList): SourceOption[] {
  return sources.items.map((source) => ({
    id: source.source_id,
    label: source.label,
    note: source.description,
    topics: source.supported_topics,
    interval: `${source.data_interval.start_at.slice(0, 10)} – ${source.data_interval.end_at.slice(0, 10)}`,
  }));
}

function metricValue(report: CustomerSignalReport, key: string): number {
  return report.metrics.find((metric) => metric.metric_key === key)?.value ?? 0;
}

function dateLabel(timestamp: string): string {
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  })
    .format(new Date(timestamp))
    .replace(/\. /g, ".")
    .replace(/\.$/, "");
}

function periodLabel(startAt: string, endAt: string): string {
  const inclusiveEnd = new Date(new Date(endAt).getTime() - 1);
  return `${dateLabel(startAt)} – ${dateLabel(inclusiveEnd.toISOString())}`;
}

function toneOf(event: JourneyEvent): JourneyNode["tone"] {
  const text = `${event.action} ${event.outcome} ${event.text}`;
  if (/완료|성공|해결|가입/.test(text) && !/미가입|미완료/.test(text)) return "resolved";
  if (/반복|재검색|재조회|다시/.test(text)) return "repeat";
  if (/실패|불만|이탈|오류|미완료|미가입|종료/.test(text)) return "negative";
  return "signal";
}

export function journeyNodesOf(events: readonly JourneyEvent[]): JourneyNode[] {
  const ordered = [...events].sort((left, right) =>
    left.occurred_at.localeCompare(right.occurred_at),
  );
  const denominator = Math.max(ordered.length - 1, 1);
  return ordered.map((event, index) => {
    const tone = toneOf(event);
    const baseIntensity = 0.18 + (index / denominator) * 0.62;
    return {
      ...event,
      lane: event.source_id,
      column: index,
      intensity: Math.min(1, baseIntensity + (tone === "negative" ? 0.18 : 0)),
      tone,
      insight: event.text,
    };
  });
}

function lanesOf(
  journey: readonly JourneyNode[],
  labels: Record<SourceId, string>,
): JourneyLane[] {
  const ids = [...new Set(journey.map((event) => event.source_id))];
  return ids.map((id) => ({ id, label: labels[id] ?? id }));
}

function claimTarget(target: unknown): string {
  if (typeof target === "string") return target;
  if (typeof target === "number" || typeof target === "boolean") return String(target);
  return JSON.stringify(target);
}

function stepStage(stepId: string): StageKey {
  if (stepId.includes("catalog")) return "analyze";
  if (stepId.includes("journey")) return "insight";
  if (stepId.includes("verify") || stepId.includes("evidence")) return "verify";
  return "analyze";
}

export function stageForStep(stepId: string): StageKey {
  return stepStage(stepId);
}

export function makeTick(
  stage: StageKey,
  kind: StageTick["kind"],
  text: string,
  options: { primitive?: string; meta?: string; short?: string } = {},
): StageTick & { stage: StageKey } {
  return {
    stage,
    kind,
    primitive: options.primitive ?? null,
    text,
    meta: options.meta ?? "",
    short: options.short ?? null,
    ms: 0,
  };
}

interface CatchReportInput {
  runId: string;
  report: CustomerSignalReport;
  plans: readonly AnalysisPlan[];
  facts: readonly AnalysisFact[];
  stepDurations: Readonly<Record<string, number>>;
  traceLog: readonly (StageTick & { stage: StageKey })[];
  sourceLabels: Record<SourceId, string>;
  journey?: readonly JourneyEvent[];
  startedAt: number;
  completedAt: string;
}

export function toCatchReport({
  runId,
  report,
  plans,
  facts,
  stepDurations,
  traceLog,
  sourceLabels,
  journey: detailedJourney,
  startedAt,
  completedAt,
}: CatchReportInput): CatchReport {
  const latestPlan = plans.at(-1);
  const previousPlan = plans.length > 1 ? plans.at(-2) : undefined;
  const factById = new Map(facts.map((fact) => [fact.fact_id, fact]));
  const journey = journeyNodesOf(detailedJourney ?? report.representative_journeys);
  const findings = report.findings.map((finding) => {
    const sourceIds = new Set<SourceId>();
    for (const factId of finding.fact_ids) {
      for (const sourceId of factById.get(factId)?.source_ids ?? []) sourceIds.add(sourceId);
    }
    const claim = finding.claim;
    return {
      claimId: claim.claim_id,
      statement: finding.statement,
      verdict: "passed" as const,
      rejectedReason: null,
      chain: {
        claim: `${claim.claim_type} · ${claim.subject} · ${claim.operator} ${claimTarget(claim.target)}`,
        fact: finding.fact_ids.length ? finding.fact_ids.join(", ") : "공개 Fact 참조 없음",
        source: [...sourceIds].map((id) => sourceLabels[id] ?? id).join(", ") || "Source 참조 없음",
        evidence: finding.evidence_ids.length
          ? finding.evidence_ids.join(", ")
          : "공개 Evidence 참조 없음",
      },
      evidenceIds: finding.evidence_ids,
    };
  });
  const supportedFindings = findings.filter((finding) => finding.evidenceIds.length > 0).length;
  const evidenceCoverage = findings.length
    ? Math.round((supportedFindings / findings.length) * 100)
    : 0;
  const lastRevision = latestPlan?.revision ?? 0;

  return {
    headline: report.headline,
    headlineCount: metricValue(report, "verified_customer_count"),
    headlineTrailer: null,
    summary: report.executive_summary,
    segmentLabel: report.goal.population.description,
    metrics: report.metrics,
    journey,
    lanes: lanesOf(journey, sourceLabels),
    findings,
    actions: report.recommendations.map((recommendation) => ({
      actionId: recommendation.action_id,
      title: recommendation.title,
      reason: recommendation.reason,
      evidenceIds: recommendation.evidence_ids,
      keywords: null,
    })),
    limitations: report.limitations,
    planSteps: (latestPlan?.steps ?? []).map((step) => {
      const previous = previousPlan?.steps.find((item) => item.step_id === step.step_id);
      const revised = previous && (
        previous.primitive !== step.primitive ||
        previous.selection_reason !== step.selection_reason
      );
      return {
        stepId: step.step_id,
        primitive: step.primitive,
        objective: step.selection_reason,
        durationMs: stepDurations[step.step_id] ?? 0,
        revisedFrom: revised ? previous.selection_reason : null,
      };
    }),
    score: {
      claimsPassed: findings.length,
      // 미확정 후보는 구조화된 Claim이 아니라 limitations에 오므로 총 Claim에 섞지 않는다.
      claimsTotal: findings.length,
      evidenceCoverage,
      steps: latestPlan?.steps.length ?? 0,
      sources: report.provenance.source_ids.length,
      planRevisions: lastRevision,
      durationMs: Math.max(0, Date.parse(completedAt) - startedAt),
    },
    runId,
    periodLabel: periodLabel(report.goal.time_range.start_at, report.goal.time_range.end_at),
    analyzedAt: dateLabel(completedAt),
    datasetVersion: report.provenance.dataset_versions.join(", ") || "unknown",
    adapterVersions: report.provenance.adapter_versions,
    traceLog: [...traceLog],
    sourceLabels,
  };
}

export function completedStages() {
  return STAGES.map((stage) => ({ ...stage, detail: stage.detail, status: "done" as const }));
}
