import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  AnalysisFact,
  AnalysisGoal,
  AnalysisPlan,
  AnyRunStreamEvent,
  CustomerSignalReport,
  PublicSourceList,
  RunSnapshot,
} from "../../../customer-intelligence/contracts";
import {
  genericFact,
  genericGoal,
  genericPlan,
  genericReport,
} from "../../../customer-intelligence/__tests__/generic-fixtures";

import { LIVE_END_AT, LIVE_START_AT } from "../live-adapter";
import {
  type SignalCatcherClient,
  useLiveCatchSession,
} from "../use-live-catch-session";

function source(sourceId: string, label: string): PublicSourceList["items"][number] {
  return {
    source_id: sourceId,
    label,
    description: `${label} 설명`,
    data_interval: { start_at: LIVE_START_AT, end_at: LIVE_END_AT },
    refresh_cadence: "static_demo",
    supported_event_types: [],
    supported_topics: [],
    supported_outcomes: [],
    dimensions: {},
    measures: {},
    capabilities: [],
    adapter_version: "1",
    manifest_version: "1",
  };
}

const sources: PublicSourceList = {
  items: [
    source("hackathon_search_history", "검색 이력"),
    source("hackathon_voc", "상담 이력"),
  ],
};

const apiSources: PublicSourceList = {
  items: [source("search_history", "기존 검색 이력"), ...sources.items],
};

const report = {
  ...genericReport,
  metrics: [
    {
      metric_key: "verified_customer_count",
      label: "확정 고객",
      value: 1,
      unit: "명",
      dimensions: {},
    },
  ],
  provenance: {
    ...genericReport.provenance,
    source_ids: sources.items.map((source) => source.source_id),
  },
} as unknown as CustomerSignalReport;
const goal = genericGoal as unknown as AnalysisGoal;
const plan = genericPlan as unknown as AnalysisPlan;

const journeyFact = {
  ...genericFact,
  step_id: "step-journeys",
  primitive: "get_customer_journey",
  payload: {
    ...genericFact.payload,
    kind: "get_customer_journey",
    customer_id: "C-01**",
  },
} as unknown as AnalysisFact;

function streamEvents(): AnyRunStreamEvent[] {
  const activity = {
    schema_version: 1 as const,
    node_id: "agent-coordinator-1",
    parent_node_id: null,
    depends_on: [],
    kind: "agent" as const,
    role: "coordinator" as const,
    task_id: "task-coordinate",
    round_index: 0,
    name: "coordinator",
    occurred_at: "2026-09-11T00:00:01Z",
    duration_ms: null,
    model: null,
    details: { candidates: [], decisions: [], limitations: [] },
  };
  return [
    { id: 1, type: "run_started", data: { status: "running" } },
    {
      id: 2,
      type: "agent_activity",
      data: { ...activity, status: "started", display_text: "질문을 역할별로 나누고 있어요." },
    },
    {
      id: 3,
      type: "agent_activity",
      data: {
        ...activity,
        status: "completed",
        display_text: "조사할 가설 두 개를 배분했어요.",
        duration_ms: 830,
      },
    },
    { id: 4, type: "goal_created", data: { goal } },
    { id: 5, type: "plan_created", data: { plan } },
    {
      id: 6,
      type: "fact_created",
      data: { step_id: journeyFact.step_id, fact: journeyFact },
    },
    { id: 7, type: "report_validating", data: { fact_ids: [], result_ids: [] } },
    { id: 8, type: "result", data: { agent_mode: "bedrock", report } },
    { id: 9, type: "done", data: { status: "completed" } },
  ];
}

describe("useLiveCatchSession", () => {
  it("refreshes sources, creates the fixed Bedrock run, consumes SSE, and loads details", async () => {
    const calls: string[] = [];
    let statusCalls = 0;
    const createdRequests: Array<{
      question: string;
      start_at: string;
      end_at: string;
      enabled_sources: string[];
    }> = [];
    const snapshot: RunSnapshot = {
      run_id: "run-live-1",
      status: "completed",
      request: {
        question: "헤맨 고객 찾아줘",
        start_at: LIVE_START_AT,
        end_at: LIVE_END_AT,
        enabled_sources: sources.items.map((source) => source.source_id),
      },
      created_at: "2026-09-11T00:00:00Z",
      updated_at: "2026-09-11T00:03:00Z",
      agent_mode: "bedrock",
      report,
      error: null,
      plan_history: [plan],
      facts: [journeyFact],
    };
    const client: SignalCatcherClient = {
      listSources: vi.fn(async () => {
        calls.push("sources");
        return apiSources;
      }),
      createRun: vi.fn(async (request) => {
        calls.push("create");
        createdRequests.push(request);
        return {
          run_id: "run-live-1",
          status_url: "/api/runs/run-live-1",
          events_url: "/api/runs/run-live-1/events",
        };
      }),
      getRun: vi.fn(async () => {
        calls.push("status");
        statusCalls += 1;
        const current: RunSnapshot = statusCalls < 3
          ? { ...snapshot, status: "running" }
          : snapshot;
        return current;
      }),
      async *streamRunEvents() {
        calls.push("stream");
        for (const event of streamEvents()) yield event;
      },
      submitClarification: vi.fn(),
      getJourney: vi.fn(async () => {
        calls.push("journey");
        return {
          result_id: "journey-1",
          customer_id: "C-01**",
          events: [],
          evidence_ids: [],
          stats: { scanned_rows: 0, returned_rows: 0 },
        };
      }),
      getEvidence: vi.fn(async (_runId, evidenceId) => ({
        result_id: "evidence-result-1",
        records: [
          {
            evidence_id: evidenceId,
            source_id: "hackathon_voc",
            occurred_at: "2026-09-05T10:00:00+09:00",
            masked_customer_id: "C-01**",
            summary: "상담 근거",
            raw_fields: {},
          },
        ],
        evidence_ids: [evidenceId],
        stats: { scanned_rows: 1, returned_rows: 1 },
      })),
    };
    const { result } = renderHook(() => useLiveCatchSession(client));

    act(() => result.current.start("헤맨 고객 찾아줘", {
      enabledSources: ["hackathon_search_history"],
      startAt: "2026-09-04",
      endAt: "2026-09-11",
    }));

    await waitFor(() => expect(result.current.session.phase).toBe("result"), {
      timeout: 2_500,
    });

    expect(createdRequests).toEqual([
      {
        question: "헤맨 고객 찾아줘",
        start_at: LIVE_START_AT,
        end_at: LIVE_END_AT,
        enabled_sources: ["hackathon_search_history"],
      },
    ]);
    expect(calls.indexOf("sources")).toBeLessThan(calls.indexOf("create"));
    expect(calls.indexOf("create")).toBeLessThan(calls.indexOf("status"));
    expect(calls).toContain("stream");
    expect(calls).toContain("journey");
    expect(statusCalls).toBeGreaterThanOrEqual(3);
    expect(result.current.session.report?.runId).toBe("run-live-1");
    expect(result.current.session.report?.headlineCount).toBe(1);
    expect(result.current.activities).toHaveLength(2);
    expect(result.current.activities[0]).toMatchObject({
      node_id: "agent-coordinator-1",
      status: "started",
      display_text: "질문을 역할별로 나누고 있어요.",
      duration_ms: null,
    });
    expect(result.current.activities[1]).toMatchObject({
      node_id: "agent-coordinator-1",
      status: "completed",
      display_text: "조사할 가설 두 개를 배분했어요.",
      duration_ms: 830,
    });
    expect(result.current.topologyEvents.map((event) => event.type)).toEqual([
      "run_started",
      "agent_activity",
      "agent_activity",
      "goal_created",
      "plan_created",
      "fact_created",
      "report_validating",
      "result",
      "done",
    ]);
    expect(result.current.sourceCount).toBe(2);
    expect(result.current.sourceOptions?.map((source) => source.id)).toEqual([
      "hackathon_search_history",
      "hackathon_voc",
    ]);

    act(() => result.current.loadEvidence("evidence-1"));
    await waitFor(() => expect(result.current.evidence["evidence-1"]).toBeDefined());
    expect(client.getEvidence).toHaveBeenCalledWith(
      "run-live-1",
      "evidence-1",
      expect.any(AbortSignal),
    );
  });

  it("restores a completed run and its detailed journey from the run id", async () => {
    const snapshot: RunSnapshot = {
      run_id: "run-saved-1",
      status: "completed",
      request: {
        question: "저장된 고객 여정을 보여줘",
        start_at: LIVE_START_AT,
        end_at: LIVE_END_AT,
        enabled_sources: sources.items.map((item) => item.source_id),
      },
      created_at: "2026-09-11T00:00:00Z",
      updated_at: "2026-09-11T00:03:00Z",
      agent_mode: "bedrock",
      report,
      error: null,
      plan_history: [plan],
      facts: [journeyFact],
      last_event_id: 9,
    };
    const client: SignalCatcherClient = {
      listSources: vi.fn(async () => apiSources),
      createRun: vi.fn(),
      getRun: vi.fn(async () => snapshot),
      async *streamRunEvents() {},
      submitClarification: vi.fn(),
      getJourney: vi.fn(async () => ({
        result_id: "journey-saved-1",
        customer_id: "C-01**",
        events: [],
        evidence_ids: [],
        stats: { scanned_rows: 0, returned_rows: 0 },
      })),
      getEvidence: vi.fn(),
    };
    const { result } = renderHook(() => useLiveCatchSession(client));

    act(() => result.current.restoreRun("run-saved-1"));

    await waitFor(() => expect(result.current.session.phase).toBe("result"));

    expect(client.createRun).not.toHaveBeenCalled();
    expect(client.getRun).toHaveBeenCalledWith("run-saved-1", expect.any(AbortSignal));
    expect(client.getJourney).toHaveBeenCalledWith(
      "run-saved-1",
      "C-01**",
      expect.any(AbortSignal),
    );
    expect(result.current.session.question).toBe("저장된 고객 여정을 보여줘");
    expect(result.current.session.report?.runId).toBe("run-saved-1");
  });
});
