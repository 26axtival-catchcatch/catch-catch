import type { AgentActivity } from "../../customer-intelligence/agent-activity";
import type {
  AnyRunStreamEvent,
  GenericPrimitiveName,
} from "../../customer-intelligence/contracts";

export type AgentState = "active" | "done" | "rejected" | "waiting";
export type SignalEdgeState = "active" | "done" | "idle" | "rejected";
export type TopologyNodeCategory = "workflow" | "step" | "agent";
export type TopologyEdgeRelation = "stream" | "dependency";

export interface AgentTopologyNode {
  id: string;
  mark: string;
  eyebrow: string;
  label: string;
  meta: string;
  detail: string | null;
  badges: string[];
  state: AgentState;
  category: TopologyNodeCategory;
  role: AgentActivity["role"] | null;
  primary: boolean;
  firstEventId: number;
  lastEventId: number;
}

export interface AgentTopologyEdge {
  id: string;
  source: string;
  target: string;
  state: SignalEdgeState;
  relation: TopologyEdgeRelation;
}

export interface AgentGraphStats {
  agents: number;
  tools: number;
  catches: number;
  rejects: number;
  allDone: boolean;
}

export interface AgentTopology {
  nodes: AgentTopologyNode[];
  edges: AgentTopologyEdge[];
  stats: AgentGraphStats;
}

interface StepDraft {
  stepId: string;
  primitive: GenericPrimitiveName | null;
  firstEventId: number;
  lastEventId: number;
  badges: string[];
  meta: string;
  state: AgentState;
}

interface AgentDraft {
  id: string;
  role: AgentActivity["role"];
  roundIndex: number;
  firstEventId: number;
  lastEventId: number;
  root: AgentActivity | null;
  latest: AgentActivity;
  activities: AgentActivity[];
}

const TERMINAL_STATUSES = new Set<AgentActivity["status"]>([
  "completed",
  "failed",
  "cancelled",
]);

const PRIMITIVE_LABELS: Record<GenericPrimitiveName, string> = {
  catalog_sources: "데이터 공간 확인",
  profile_events: "이벤트 분포 확인",
  aggregate_events: "이벤트 집계",
  segment_customers: "고객군 분리",
  detect_repetition: "반복 행동 탐지",
  match_sequence: "행동 순서 확인",
  compare_segments: "고객군 비교",
  rank_customers: "고객 우선순위",
  get_customer_journey: "고객 여정 조회",
  get_evidence: "근거 조회",
};

const ROLE_LABELS: Record<AgentActivity["role"], { label: string; mark: string }> = {
  coordinator: { label: "총괄 에이전트", mark: "C" },
  investigator: { label: "분석 에이전트", mark: "I" },
  verifier: { label: "검증 에이전트", mark: "V" },
  reporter: { label: "보고 에이전트", mark: "R" },
};

function graphState(status: AgentActivity["status"]): AgentState {
  if (status === "started") return "active";
  if (status === "completed") return "done";
  if (status === "failed" || status === "cancelled") return "rejected";
  return "waiting";
}

function completedState(status: "completed" | "degraded" | "failed"): AgentState {
  return status === "failed" ? "rejected" : "done";
}

function edgeState(source: AgentTopologyNode, target: AgentTopologyNode): SignalEdgeState {
  if (target.state === "rejected") return "rejected";
  if (target.state === "active") return "active";
  if (source.state === "done" || target.state === "done") return "done";
  if (source.state === "active") return "active";
  return "idle";
}

function appendBadge(badges: string[], badge: string): void {
  if (!badges.includes(badge)) badges.push(badge);
}

function metricSummary(event: Extract<AnyRunStreamEvent, { type: "fact_created" }>): string {
  const metric = event.data.fact.metrics[0];
  if (!metric) return event.data.fact.fact_id;
  return `${metric.label} ${metric.value.toLocaleString("ko-KR")}${metric.unit}`;
}

function eventNode(event: Exclude<AnyRunStreamEvent, { type: "agent_activity" }>): AgentTopologyNode {
  const common = {
    id: `event:${event.id}:${event.type}`,
    badges: [event.type],
    state: "done" as AgentState,
    category: "workflow" as const,
    role: null,
    primary: false,
    firstEventId: event.id,
    lastEventId: event.id,
  };

  switch (event.type) {
    case "run_started":
      return { ...common, mark: "▶", eyebrow: "SSE WORKFLOW", label: "Run 시작", meta: `status · ${event.data.status}`, detail: null };
    case "goal_created":
      return { ...common, mark: "G", eyebrow: "GOAL_CREATED", label: "분석 목표 생성", meta: event.data.goal.objective, detail: event.data.goal.population.description };
    case "clarification_required":
      return { ...common, mark: "?", eyebrow: "CLARIFICATION", label: "추가 확인", meta: event.data.question, detail: null, state: "active" };
    case "plan_created":
    case "plan_revised":
      return {
        ...common,
        mark: "P",
        eyebrow: event.type.toUpperCase(),
        label: event.type === "plan_created" ? "실행 계획 생성" : "실행 계획 수정",
        meta: `${event.data.plan.steps.length}개 step · revision ${event.data.plan.revision}`,
        detail: event.data.plan.rationale,
      };
    case "report_validating":
      return {
        ...common,
        mark: "✓",
        eyebrow: "REPORT_VALIDATING",
        label: "공개 결과 검증",
        meta: `fact ${event.data.fact_ids.length}건 · result ${event.data.result_ids.length}건`,
        detail: null,
        state: "active",
      };
    case "plan":
      return { ...common, mark: "P", eyebrow: "PLAN", label: "실행 계획", meta: `${event.data.steps.length}개 단계`, detail: null };
    case "tool_started":
      return { ...common, mark: "T", eyebrow: "TOOL_STARTED", label: event.data.tool, meta: event.data.source.join(", "), detail: null, state: "active" };
    case "tool_completed":
      return { ...common, mark: "T", eyebrow: "TOOL_COMPLETED", label: event.data.tool, meta: `${event.data.count.toLocaleString("ko-KR")}건`, detail: `${event.data.duration_ms}ms` };
    case "validating":
      return { ...common, mark: "✓", eyebrow: "VALIDATING", label: "결과 검증", meta: `${event.data.result_ids.length}개 결과`, detail: null, state: "active" };
    case "result":
      return { ...common, mark: "R", eyebrow: "RESULT", label: "분석 결과 생성", meta: event.data.report.report_kind ?? "report", detail: event.data.agent_mode ?? null };
    case "error":
      return { ...common, mark: "!", eyebrow: "ERROR", label: "실행 오류", meta: event.data.message, detail: event.data.code, state: "rejected" };
    case "fallback":
      return { ...common, mark: "↻", eyebrow: "FALLBACK", label: "Provider 전환", meta: event.data.reason ?? event.data.message ?? "fallback", detail: null, state: "rejected" };
    case "done":
      return { ...common, mark: "■", eyebrow: "DONE", label: "SSE 실행 완료", meta: `status · ${event.data.status}`, detail: event.data.limitations?.join(" · ") ?? null, state: completedState(event.data.status) };
    case "step_started":
    case "fact_created":
    case "analysis_note_created":
    case "step_completed":
      throw new Error("step lifecycle events are grouped before rendering");
  }
}

function stepIdOf(event: AnyRunStreamEvent): string | null {
  if (event.type === "step_started" || event.type === "fact_created" || event.type === "step_completed") {
    return event.data.step_id;
  }
  if (event.type === "analysis_note_created") return event.data.note.step_id;
  return null;
}

function mergeWorkflowGroup(
  id: string,
  eyebrow: string,
  label: string,
  mark: string,
  members: readonly AgentTopologyNode[],
): AgentTopologyNode {
  const latest = members[members.length - 1];
  return {
    ...latest,
    id,
    mark,
    eyebrow,
    label,
    badges: members.flatMap((member) => member.badges),
    firstEventId: members[0].firstEventId,
    lastEventId: latest.lastEventId,
  };
}

function compactWorkflowNodes(nodes: readonly AgentTopologyNode[]): AgentTopologyNode[] {
  const result = [...nodes];
  const setupTypes = new Set(["run_started", "goal_created", "plan_created"]);
  const setup: AgentTopologyNode[] = [];
  while (result.length > 0 && setupTypes.has(result[0].badges[0])) {
    setup.push(result.shift()!);
  }
  if (setup.length > 0) {
    result.unshift(mergeWorkflowGroup(
      "workflow:setup",
      "SSE WORKFLOW",
      "Run · 목표 · 계획",
      "S",
      setup,
    ));
  }

  const completionTypes = new Set(["result", "done"]);
  const completion: AgentTopologyNode[] = [];
  while (result.length > 0 && completionTypes.has(result[result.length - 1].badges[0])) {
    completion.unshift(result.pop()!);
  }
  if (completion.length > 0) {
    result.push(mergeWorkflowGroup(
      "workflow:completion",
      "SSE DELIVERY",
      "결과 전달 완료",
      "■",
      completion,
    ));
  }
  return result;
}

function buildWorkflowNodes(events: readonly AnyRunStreamEvent[]): AgentTopologyNode[] {
  const standalone: AgentTopologyNode[] = [];
  const steps = new Map<string, StepDraft>();

  for (const event of events) {
    if (event.type === "agent_activity") continue;
    const stepId = stepIdOf(event);
    if (!stepId) {
      standalone.push(eventNode(event));
      continue;
    }

    const step = steps.get(stepId) ?? {
      stepId,
      primitive: null,
      firstEventId: event.id,
      lastEventId: event.id,
      badges: [],
      meta: stepId,
      state: "active" as AgentState,
    };
    step.lastEventId = event.id;
    appendBadge(step.badges, event.type);

    if (event.type === "step_started") {
      step.primitive = event.data.primitive;
      step.meta = event.data.objective ?? event.data.selection_reason ?? event.data.step_id;
      step.state = "active";
    } else if (event.type === "fact_created") {
      step.primitive = event.data.fact.primitive;
      step.meta = metricSummary(event);
    } else if (event.type === "analysis_note_created") {
      step.meta = event.data.note.claims[0]?.rendered_text ?? event.data.note.next_action;
    } else if (event.type === "step_completed") {
      step.meta = `${event.data.status} · ${event.data.duration_ms.toLocaleString("ko-KR")}ms`;
      step.state = completedState(event.data.status);
    }
    steps.set(stepId, step);
  }

  const stepNodes = [...steps.values()].map((step): AgentTopologyNode => ({
    id: `step:${step.stepId}`,
    mark: "Σ",
    eyebrow: `STEP · ${step.stepId}`,
    label: step.primitive ? PRIMITIVE_LABELS[step.primitive] : step.stepId,
    meta: step.meta,
    detail: step.primitive,
    badges: step.badges,
    state: step.state,
    category: "step",
    role: null,
    primary: false,
    firstEventId: step.firstEventId,
    lastEventId: step.lastEventId,
  }));

  const nodes = compactWorkflowNodes(
    [...standalone, ...stepNodes].sort((left, right) => left.firstEventId - right.firstEventId),
  );
  for (let index = 0; index < nodes.length - 1; index += 1) {
    if (nodes[index].category === "workflow" && nodes[index].state === "active") {
      nodes[index] = { ...nodes[index], state: "done" };
    }
  }
  return nodes;
}

function buildAgentDrafts(events: readonly AnyRunStreamEvent[]): AgentDraft[] {
  const drafts = new Map<string, AgentDraft>();

  for (const event of events) {
    if (event.type !== "agent_activity") continue;
    const activity = event.data;
    const groupId = activity.kind === "agent"
      ? activity.node_id
      : activity.parent_node_id ?? activity.node_id;
    const existing = drafts.get(groupId);
    if (existing) {
      existing.lastEventId = event.id;
      existing.latest = activity;
      existing.activities.push(activity);
      if (activity.kind === "agent") existing.root = activity;
    } else {
      drafts.set(groupId, {
        id: groupId,
        role: activity.role,
        roundIndex: activity.round_index,
        firstEventId: event.id,
        lastEventId: event.id,
        root: activity.kind === "agent" ? activity : null,
        latest: activity,
        activities: [activity],
      });
    }
  }

  return [...drafts.values()].sort((left, right) => left.firstEventId - right.firstEventId);
}

function countUnique(draft: AgentDraft, kind: AgentActivity["kind"]): number {
  return new Set(
    draft.activities.filter((activity) => activity.kind === kind).map((activity) => activity.node_id),
  ).size;
}

function buildAgentNodes(drafts: readonly AgentDraft[]): AgentTopologyNode[] {
  const investigatorCount = new Map<number, number>();

  return drafts.map((draft): AgentTopologyNode => {
    const presentation = ROLE_LABELS[draft.role];
    const modelCount = countUnique(draft, "model");
    const toolCount = countUnique(draft, "tool");
    const assessmentCount = countUnique(draft, "assessment");
    let label = presentation.label;
    let mark = presentation.mark;

    if (draft.role === "investigator") {
      const sequence = (investigatorCount.get(draft.roundIndex) ?? 0) + 1;
      investigatorCount.set(draft.roundIndex, sequence);
      label = draft.roundIndex > 0 ? `재조사 에이전트 ${sequence}` : `분석 에이전트 ${sequence}`;
      mark = `I${sequence}`;
    } else if (draft.role === "verifier" && draft.roundIndex > 0) {
      label = `재검증 에이전트 ${draft.roundIndex}`;
      mark = `V${draft.roundIndex}`;
    }

    const badges = [draft.root?.status ?? draft.latest.status, `MODEL ${modelCount}`, `TOOL ${toolCount}`];
    if (assessmentCount > 0) badges.push(`ASSESS ${assessmentCount}`);

    return {
      id: draft.id,
      mark,
      eyebrow: `AGENT_ACTIVITY · ${draft.role}`,
      label,
      meta: draft.latest.display_text,
      detail: `${draft.latest.kind} · ${draft.latest.name} · ${draft.latest.status}`,
      badges,
      state: graphState(draft.root?.status ?? draft.latest.status),
      category: "agent",
      role: draft.role,
      primary: true,
      firstEventId: draft.firstEventId,
      lastEventId: draft.lastEventId,
    };
  });
}

function activityEvents(events: readonly AnyRunStreamEvent[]): AgentActivity[] {
  return events.flatMap((event) => event.type === "agent_activity" ? [event.data] : []);
}

function latestActivities(activities: readonly AgentActivity[]): AgentActivity[] {
  const byNode = new Map<string, AgentActivity>();
  for (const activity of activities) byNode.set(activity.node_id, activity);
  return [...byNode.values()];
}

export function getAgentGraphStats(events: readonly AnyRunStreamEvent[]): AgentGraphStats {
  const latest = latestActivities(activityEvents(events));
  const agents = latest.filter((activity) => activity.kind === "agent");
  const decisions = new Map<string, AgentActivity["details"]["decisions"][number]["verdict"]>();

  for (const activity of latest) {
    for (const decision of activity.details.decisions) {
      decisions.set(decision.candidate_id, decision.verdict);
    }
  }

  return {
    agents: agents.length,
    tools: latest.filter((activity) => activity.kind === "tool").length,
    catches: [...decisions.values()].filter((verdict) => verdict === "confirmed").length,
    rejects: [...decisions.values()].filter((verdict) => verdict === "rejected").length,
    allDone: agents.length > 0 && agents.every((agent) => TERMINAL_STATUSES.has(agent.status)),
  };
}

function addEdge(
  edges: AgentTopologyEdge[],
  nodesById: ReadonlyMap<string, AgentTopologyNode>,
  sourceId: string,
  targetId: string,
  relation: TopologyEdgeRelation,
): void {
  const source = nodesById.get(sourceId);
  const target = nodesById.get(targetId);
  if (!source || !target) return;
  const id = `${relation}:${sourceId}->${targetId}`;
  if (edges.some((edge) => edge.id === id)) return;
  edges.push({ id, source: sourceId, target: targetId, relation, state: edgeState(source, target) });
}

/** 실제 공개 SSE 이벤트와 agent_activity 관계만 React Flow 토폴로지로 투영한다. */
export function createAgentTopology(events: readonly AnyRunStreamEvent[]): AgentTopology {
  const workflowNodes = buildWorkflowNodes(events);
  const agentDrafts = buildAgentDrafts(events);
  const agentNodes = buildAgentNodes(agentDrafts);
  const nodes = [...workflowNodes, ...agentNodes].sort(
    (left, right) => left.firstEventId - right.firstEventId,
  );
  const nodesById = new Map(nodes.map((node) => [node.id, node]));
  const edges: AgentTopologyEdge[] = [];

  for (let index = 1; index < workflowNodes.length; index += 1) {
    addEdge(edges, nodesById, workflowNodes[index - 1].id, workflowNodes[index].id, "stream");
  }

  for (const draft of agentDrafts) {
    const dependencies = draft.root?.depends_on ?? [];
    for (const dependencyId of dependencies) {
      addEdge(edges, nodesById, dependencyId, draft.id, "dependency");
    }
    if (dependencies.length === 0) {
      let previousWorkflow: AgentTopologyNode | null = null;
      for (const workflow of workflowNodes) {
        if (workflow.lastEventId >= draft.firstEventId) break;
        previousWorkflow = workflow;
      }
      if (previousWorkflow) addEdge(edges, nodesById, previousWorkflow.id, draft.id, "stream");
    }
  }

  let lastBridgedAgentId: string | null = null;
  for (const workflow of workflowNodes) {
    let latestAgent: AgentTopologyNode | null = null;
    for (const agent of agentNodes) {
      if (agent.lastEventId >= workflow.firstEventId) continue;
      if (!latestAgent || agent.lastEventId > latestAgent.lastEventId) latestAgent = agent;
    }
    if (latestAgent && latestAgent.id !== lastBridgedAgentId) {
      addEdge(edges, nodesById, latestAgent.id, workflow.id, "stream");
      lastBridgedAgentId = latestAgent.id;
    }
  }

  return { nodes, edges, stats: getAgentGraphStats(events) };
}
