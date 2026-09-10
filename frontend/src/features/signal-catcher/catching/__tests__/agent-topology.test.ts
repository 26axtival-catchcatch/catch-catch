import { describe, expect, it } from "vitest";

import type { AgentActivity } from "../../../customer-intelligence/agent-activity";
import type { AnyRunStreamEvent } from "../../../customer-intelligence/contracts";
import { createAgentTopology, getAgentGraphStats } from "../agent-topology";

let nextEventId = 1;

function activity(
  overrides: Partial<AgentActivity> = {},
  eventId = nextEventId++,
): AnyRunStreamEvent {
  return {
    id: eventId,
    type: "agent_activity",
    data: {
      schema_version: 1,
      node_id: "agent-coordinator",
      parent_node_id: null,
      depends_on: [],
      kind: "agent",
      role: "coordinator",
      task_id: "task-coordination",
      round_index: 0,
      status: "completed",
      name: "coordinator",
      display_text: "조사할 가설을 배분했어요.",
      occurred_at: "2026-09-10T08:00:00Z",
      duration_ms: 4100,
      model: null,
      details: { candidates: [], decisions: [], limitations: [] },
      ...overrides,
    },
  };
}

describe("createAgentTopology", () => {
  it("agent_activity가 없으면 가상 노드를 만들지 않는다", () => {
    expect(createAgentTopology([])).toEqual({
      nodes: [],
      edges: [],
      stats: { agents: 0, tools: 0, catches: 0, rejects: 0, allDone: false },
    });
  });

  it("kind=agent 노드와 depends_on 간선만 실제 ID로 만든다", () => {
    const activities = [
      activity(),
      activity({
        node_id: "agent-investigator-a",
        depends_on: ["agent-coordinator"],
        role: "investigator",
        task_id: "task-a",
        status: "started",
        duration_ms: null,
      }),
      activity({
        node_id: "agent-investigator-b",
        depends_on: ["agent-coordinator"],
        role: "investigator",
        task_id: "task-b",
      }),
      activity({
        node_id: "tool-query",
        parent_node_id: "agent-investigator-a",
        kind: "tool",
        role: "investigator",
        task_id: "task-a",
        name: "query_data",
      }),
      activity({
        node_id: "agent-verifier",
        depends_on: ["agent-investigator-a", "agent-investigator-b"],
        role: "verifier",
        task_id: "task-verification-0",
        status: "queued",
        duration_ms: null,
      }),
    ];
    const topology = createAgentTopology(activities);

    expect(topology.nodes.map((node) => node.id)).toEqual([
      "agent-coordinator",
      "agent-investigator-a",
      "agent-investigator-b",
      "agent-verifier",
    ]);
    expect(topology.nodes.map((node) => node.label)).toEqual([
      "총괄 에이전트",
      "분석 에이전트 1",
      "분석 에이전트 2",
      "검증 에이전트",
    ]);
    expect(topology.edges.map(({ source, target }) => `${source}->${target}`)).toEqual([
      "agent-coordinator->agent-investigator-a",
      "agent-coordinator->agent-investigator-b",
      "agent-investigator-a->agent-verifier",
      "agent-investigator-b->agent-verifier",
    ]);
    expect(topology.edges.map((edge) => edge.state)).toEqual([
      "active",
      "done",
      "active",
      "done",
    ]);
    expect(topology.nodes.some((node) => node.id === "tool-query")).toBe(false);
  });

  it("루트 이벤트보다 먼저 보이는 하위 activity도 parent와 role로 에이전트 노드를 만든다", () => {
    const topology = createAgentTopology([
      activity({
        node_id: "model-coordinator",
        parent_node_id: "agent-coordinator-live",
        kind: "model",
        role: "coordinator",
        task_id: "task-coordination",
        status: "started",
        name: "generation",
        display_text: "분석 목표에 맞는 역할을 나누고 있어요.",
        duration_ms: null,
      }),
      activity({
        node_id: "tool-coordinator",
        parent_node_id: "agent-coordinator-live",
        kind: "tool",
        role: "coordinator",
        task_id: "task-coordination",
        status: "started",
        name: "query_data",
        display_text: "데이터 질의",
        duration_ms: null,
      }),
    ]);

    expect(topology.nodes).toHaveLength(1);
    expect(topology.nodes[0]).toMatchObject({
      id: "agent-coordinator-live",
      role: "coordinator",
      label: "총괄 에이전트",
      state: "active",
      badges: ["started", "MODEL 1", "TOOL 1"],
    });
  });

  it("서버가 보내지 않은 의존 노드나 연결을 추정하지 않는다", () => {
    const topology = createAgentTopology([
      activity({
        node_id: "agent-verifier",
        depends_on: ["agent-missing"],
        role: "verifier",
        task_id: "task-verification-0",
        status: "started",
        duration_ms: null,
      }),
    ]);

    expect(topology.nodes.map((node) => node.id)).toEqual(["agent-verifier"]);
    expect(topology.edges).toEqual([]);
  });

  it("총괄 → 분석 → 검증 → 보고의 실제 depends_on 체인을 그대로 연결한다", () => {
    const topology = createAgentTopology([
      activity({ node_id: "agent-coordinator", role: "coordinator" }),
      activity({
        node_id: "agent-investigator",
        depends_on: ["agent-coordinator"],
        role: "investigator",
        task_id: "task-investigation",
      }),
      activity({
        node_id: "agent-verifier",
        depends_on: ["agent-investigator"],
        role: "verifier",
        task_id: "task-verification",
      }),
      activity({
        node_id: "agent-reporter",
        depends_on: ["agent-verifier"],
        role: "reporter",
        task_id: "task-reporting",
      }),
    ]);

    expect(topology.nodes.map((node) => node.id)).toEqual([
      "agent-coordinator",
      "agent-investigator",
      "agent-verifier",
      "agent-reporter",
    ]);
    expect(topology.edges.map(({ source, target }) => `${source}->${target}`)).toEqual([
      "agent-coordinator->agent-investigator",
      "agent-investigator->agent-verifier",
      "agent-verifier->agent-reporter",
    ]);
  });

  it("같은 node_id의 마지막 상태만 그래프와 통계에 반영한다", () => {
    const topology = createAgentTopology([
      activity({ status: "queued", duration_ms: null }),
      activity({ status: "started", duration_ms: null }),
      activity({ status: "completed", duration_ms: 8200 }),
    ]);

    expect(topology.nodes).toHaveLength(1);
    expect(topology.nodes[0]).toMatchObject({
      state: "done",
      meta: "조사할 가설을 배분했어요.",
    });
    expect(topology.stats.agents).toBe(1);
  });

  it("공개 SSE 단계와 역할별 agent_activity를 하나의 실제 실행 그래프로 연결한다", () => {
    const workflowEvents = [
      { id: 1, type: "run_started", data: { status: "running" } },
      {
        id: 2,
        type: "goal_created",
        data: { goal: { objective: "헤맨 고객 찾기", population: { description: "최근 고객" } } },
      },
      {
        id: 3,
        type: "plan_created",
        data: { plan: { revision: 0, steps: [{ step_id: "step-catalog" }], rationale: "실행 계획" } },
      },
      {
        id: 4,
        type: "step_started",
        data: { step_id: "step-catalog", primitive: "catalog_sources", selection_reason: "데이터 확인" },
      },
      {
        id: 5,
        type: "fact_created",
        data: {
          step_id: "step-catalog",
          fact: {
            primitive: "catalog_sources",
            fact_id: "fact-catalog",
            metrics: [{ label: "조사 데이터 소스", value: 2, unit: "개" }],
          },
        },
      },
      {
        id: 6,
        type: "analysis_note_created",
        data: { note: { step_id: "step-catalog", claims: [], next_action: "소스 확인 완료" } },
      },
      {
        id: 7,
        type: "step_completed",
        data: { step_id: "step-catalog", status: "completed", result_ids: ["result-catalog"], duration_ms: 12 },
      },
      activity({ status: "started" }, 8),
      activity({
        node_id: "tool-query",
        parent_node_id: "agent-coordinator",
        kind: "tool",
        status: "completed",
        name: "query_data",
        display_text: "전체 데이터 공간을 조회했어요.",
      }, 9),
      activity({
        node_id: "agent-investigator",
        depends_on: ["agent-coordinator"],
        role: "investigator",
        status: "started",
      }, 10),
      { id: 11, type: "report_validating", data: { fact_ids: ["fact-catalog"], result_ids: [] } },
    ] as unknown as AnyRunStreamEvent[];

    const topology = createAgentTopology(workflowEvents);
    const step = topology.nodes.find((node) => node.id === "step:step-catalog");
    const coordinator = topology.nodes.find((node) => node.id === "agent-coordinator");

    expect(topology.nodes.map((node) => node.category)).toEqual([
      "workflow", "step", "agent", "agent", "workflow",
    ]);
    expect(topology.nodes[0]).toMatchObject({
      id: "workflow:setup",
      badges: ["run_started", "goal_created", "plan_created"],
    });
    expect(step?.badges).toEqual([
      "step_started", "fact_created", "analysis_note_created", "step_completed",
    ]);
    expect(coordinator).toMatchObject({
      role: "coordinator",
      state: "active",
      meta: "전체 데이터 공간을 조회했어요.",
      badges: ["started", "MODEL 0", "TOOL 1"],
    });
    expect(topology.edges.map(({ source, target, relation }) => `${source}->${target}:${relation}`)).toContain(
      "step:step-catalog->agent-coordinator:stream",
    );
    expect(topology.edges.map(({ source, target, relation }) => `${source}->${target}:${relation}`)).toContain(
      "agent-coordinator->agent-investigator:dependency",
    );
    expect(topology.edges.map(({ source, target, relation }) => `${source}->${target}:${relation}`)).toContain(
      "agent-investigator->event:11:report_validating:stream",
    );
  });
});

describe("getAgentGraphStats", () => {
  it("실제 도구 노드와 서버의 최신 후보 판정만 집계한다", () => {
    const stats = getAgentGraphStats([
      activity(),
      activity({ node_id: "tool-a", kind: "tool", name: "query_data" }),
      activity({ node_id: "tool-b", kind: "tool", name: "customer_journey" }),
      activity({
        node_id: "assessment-0",
        kind: "assessment",
        role: "verifier",
        name: "verification_policy",
        details: {
          candidates: [],
          limitations: [],
          decisions: [
            { candidate_id: "candidate-a", verdict: "confirmed", reason: "근거 확인", evidence_query_ids: [] },
            { candidate_id: "candidate-b", verdict: "rejected", reason: "근거 부족", evidence_query_ids: [] },
          ],
        },
      }),
      activity({
        node_id: "assessment-1",
        kind: "assessment",
        role: "verifier",
        name: "verification_policy",
        details: {
          candidates: [],
          limitations: [],
          decisions: [
            { candidate_id: "candidate-b", verdict: "confirmed", reason: "재검증 완료", evidence_query_ids: [] },
          ],
        },
      }),
    ]);

    expect(stats).toEqual({ agents: 1, tools: 2, catches: 2, rejects: 0, allDone: true });
  });
});
