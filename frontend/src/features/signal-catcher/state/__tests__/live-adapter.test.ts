import { describe, expect, it } from "vitest";

import type {
  CustomerSignalReport,
  JourneyEvent,
  PublicSourceList,
} from "../../../customer-intelligence/contracts";

import {
  LIVE_END_AT,
  LIVE_START_AT,
  activeSourceListOf,
  journeyNodesOf,
  sourceLabelsOf,
  stageForStep,
  toCatchReport,
} from "../live-adapter";

const journey: JourneyEvent[] = [
  {
    event_id: "event-2",
    evidence_id: "evidence-2",
    source_id: "hackathon_voc",
    occurred_at: "2026-09-06T10:00:00+09:00",
    event_type: "voc",
    action: "상담 완료",
    topic: "로밍",
    outcome: "해결",
    text: "상담으로 문제를 해결했습니다.",
  },
  {
    event_id: "event-1",
    evidence_id: "evidence-1",
    source_id: "hackathon_search_history",
    occurred_at: "2026-09-05T10:00:00+09:00",
    event_type: "search",
    action: "반복 검색",
    topic: "로밍",
    outcome: "실패",
    text: "같은 내용을 다시 검색했습니다.",
  },
];

const report = {
  report_kind: "customer_signal",
  goal: {
    kind: "goal",
    goal_id: "goal-1",
    objective: "헤맨 고객 찾기",
    population: { entity: "customers", description: "분석 기간의 고객" },
    time_range: {
      start_at: LIVE_START_AT,
      end_at: LIVE_END_AT,
    },
    source_ids: ["hackathon_search_history", "hackathon_voc"],
    measures: [],
    group_by: [],
    predicates: [],
    sequence: null,
    output: "journey",
  },
  headline: "원하는 경로를 바로 찾지 못한 고객",
  executive_summary: "두 개 패턴을 확인했습니다.",
  metrics: [
    {
      metric_key: "verified_customer_count",
      label: "확정 고객",
      value: 215,
      unit: "명",
      dimensions: {},
    },
    {
      metric_key: "candidate_customer_count",
      label: "미확정 후보",
      value: 51,
      unit: "명",
      dimensions: {},
    },
  ],
  signals: [],
  ranked_customers: [],
  representative_journeys: journey,
  findings: [],
  recommendations: [],
  limitations: ["미확정 후보는 독립 검증이 부족합니다."],
  provenance: {
    fact_ids: [],
    result_ids: [],
    source_ids: ["hackathon_search_history", "hackathon_voc"],
    dataset_versions: ["snapshot-1"],
    adapter_versions: {
      hackathon_search_history: "1",
      hackathon_voc: "1",
    },
    manifest_versions: {
      hackathon_search_history: "1",
      hackathon_voc: "1",
    },
  },
} as CustomerSignalReport;

describe("Signal Catcher live adapter", () => {
  it("replaces built-in sources with seeded sources when both are returned", () => {
    const sources = {
      items: [
        { source_id: "search_history", label: "기존 검색 이력" },
        { source_id: "voc", label: "기존 상담 이력" },
        { source_id: "hackathon_search_history", label: "신규 검색 이력" },
        { source_id: "hackathon_voc", label: "신규 상담 이력" },
      ],
    } as PublicSourceList;

    expect(activeSourceListOf(sources).items.map((source) => source.source_id)).toEqual([
      "hackathon_search_history",
      "hackathon_voc",
    ]);
  });

  it("keeps built-in sources as a fallback when seeded sources are absent", () => {
    const sources = {
      items: [{ source_id: "search_history", label: "검색 이력" }],
    } as PublicSourceList;

    expect(activeSourceListOf(sources)).toBe(sources);
  });

  it("maps the fixed-period customer_signal report without inventing rankings", () => {
    const mapped = toCatchReport({
      runId: "run-1",
      report,
      plans: [],
      facts: [],
      stepDurations: {},
      traceLog: [],
      sourceLabels: {
        hackathon_search_history: "검색 이력",
        hackathon_voc: "상담 이력",
      },
      startedAt: Date.parse("2026-09-11T01:00:00Z"),
      completedAt: "2026-09-11T01:03:00Z",
    });

    expect(mapped.headlineCount).toBe(215);
    expect(mapped.metrics.map((metric) => metric.metric_key)).toContain(
      "candidate_customer_count",
    );
    expect(mapped.periodLabel).toBe("2026.09.04 – 2026.09.17");
    expect(mapped.score.durationMs).toBe(180_000);
    expect(mapped.journey.map((event) => event.event_id)).toEqual([
      "event-1",
      "event-2",
    ]);
  });

  it("derives only presentation tone and never a customer risk score", () => {
    const nodes = journeyNodesOf(journey);

    expect(nodes[0].tone).toBe("repeat");
    expect(nodes[1].tone).toBe("resolved");
    expect(nodes.every((node) => !("risk_score" in node))).toBe(true);
  });

  it("keeps dynamic source labels and maps public steps onto the five UI stages", () => {
    const sources = {
      items: [
        {
          source_id: "hackathon_app_behavior",
          label: "앱 행동",
        },
      ],
    } as PublicSourceList;

    expect(sourceLabelsOf(sources)).toEqual({ hackathon_app_behavior: "앱 행동" });
    expect(stageForStep("step-journeys")).toBe("insight");
    expect(stageForStep("step-evidence")).toBe("verify");
  });
});
