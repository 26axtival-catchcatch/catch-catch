import type { CatchSession, StageKey, StageTick } from "../state/types";

export type AgentState = "active" | "done" | "rejected" | "waiting";
export type SignalEdgeState = "active" | "done" | "idle" | "rejected";

export interface AgentTopologyNode {
  id: string;
  mark: string;
  label: string;
  meta: string;
  state: AgentState;
  primary: boolean;
}

export interface AgentTopologyEdge {
  id: string;
  source: string;
  target: string;
  state: SignalEdgeState;
}

export interface AgentGraphStats {
  tools: number;
  catches: number;
  rejects: number;
  stageIndex: number;
  allDone: boolean;
}

export interface AgentTopology {
  nodes: AgentTopologyNode[];
  edges: AgentTopologyEdge[];
  stats: AgentGraphStats;
}

type CandidateState = AgentState | "pending";

interface CandidateNode extends Omit<AgentTopologyNode, "state"> {
  state: CandidateState;
}

const RESEARCH_BRANCHES = ["search", "behavior", "counsel"] as const;
const VERIFY_BRANCHES = ["source", "cross", "rebuttal"] as const;

function stageIndexOf(session: CatchSession): number {
  const activeIndex = session.stages.findIndex((stage) => stage.status === "active");
  if (activeIndex >= 0) return activeIndex;

  const doneCount = session.stages.filter((stage) => stage.status === "done").length;
  return Math.max(0, doneCount - 1);
}

function signalState(
  visible: boolean,
  active: boolean,
  done: boolean,
  rejected = false,
): CandidateState {
  if (!visible) return "pending";
  if (rejected) return "rejected";
  if (done) return "done";
  if (active) return "active";
  return "waiting";
}

export function getAgentGraphStats(
  session: CatchSession,
  log: (StageTick & { stage: StageKey })[],
): AgentGraphStats {
  let tools = 0;
  let catches = 0;
  let rejects = 0;

  for (const entry of log) {
    if (entry.kind === "tool") tools += 1;
    else if (entry.kind === "fact") catches += 1;
    else if (entry.kind === "reject") rejects += 1;
  }

  return {
    tools,
    catches,
    rejects,
    stageIndex: stageIndexOf(session),
    allDone: session.stages.every((stage) => stage.status === "done"),
  };
}

/**
 * 실행 로그에 맞춰 실제로 존재하는 노드와 연결만 만든다.
 * 가지가 생기면 Dagre가 이 토폴로지를 다시 배치하므로 좌표나 SVG 경로를 손댈 필요가 없다.
 */
export function createAgentTopology(
  session: CatchSession,
  log: (StageTick & { stage: StageKey })[],
): AgentTopology {
  const stats = getAgentGraphStats(session, log);
  const { tools, catches, rejects, stageIndex, allDone } = stats;
  const activeStage = session.activeStage;

  const candidates: CandidateNode[] = [
    {
      id: "lead",
      mark: "◎",
      label: "분석 조율",
      meta: stageIndex < 2 ? "질문과 범위 정리" : "분석 순서 확정",
      state: signalState(true, stageIndex < 2 && !allDone, stageIndex >= 2 || allDone),
      primary: true,
    },
    {
      id: "research",
      mark: "∑",
      label: "데이터 분석",
      meta: stageIndex >= 3 || allDone ? "관련 데이터 확인 완료" : "관련 데이터 확인 중",
      state: signalState(stageIndex >= 1, activeStage === "analyze", stageIndex >= 3 || allDone),
      primary: true,
    },
    {
      id: "search",
      mark: "01",
      label: "데이터 조회",
      meta: tools >= 1 ? `${tools}회 조회` : "조회 준비",
      state: signalState(tools >= 1, tools >= 1 && tools < 4, tools >= 4 || allDone),
      primary: false,
    },
    {
      id: "behavior",
      mark: "02",
      label: "사실 정리",
      meta: catches >= 1 ? `${catches}건 발견` : "결과 정리 중",
      state: signalState(tools >= 3, tools >= 3 && tools < 6, tools >= 6 || allDone),
      primary: false,
    },
    {
      id: "counsel",
      mark: "03",
      label: "맥락 해석",
      meta: stageIndex >= 3 ? "발견 내용 간 관계 정리" : "해석 준비",
      state: signalState(tools >= 5, tools >= 5 && stageIndex < 3, stageIndex >= 3 || allDone),
      primary: false,
    },
    {
      id: "verify",
      mark: "✓",
      label: "근거 검증",
      meta: allDone ? "원본 데이터 대조 완료" : "원본 데이터와 대조 중",
      state: signalState(stageIndex >= 1, stageIndex >= 2 && !allDone, allDone),
      primary: true,
    },
    {
      id: "source",
      mark: "A",
      label: "출처 확인",
      meta: catches >= 2 || allDone ? "출처 확인 완료" : "원본과 대조 중",
      state: signalState(catches >= 1, catches === 1, catches >= 2 || allDone),
      primary: false,
    },
    {
      id: "cross",
      mark: "B",
      label: "교차 검증",
      meta: rejects > 0 || allDone ? `${catches}건 확인 완료` : `${catches}건 비교 중`,
      state: signalState(catches >= 2, rejects === 0 && !allDone, rejects > 0 || allDone),
      primary: false,
    },
    {
      id: "rebuttal",
      mark: rejects > 0 ? "×" : "C",
      label: "반대 근거 확인",
      meta: rejects > 0 ? `근거 부족 ${rejects}건 제외` : "누락된 근거 확인 중",
      state: signalState(stageIndex >= 3, activeStage === "verify" && !allDone, allDone, rejects > 0),
      primary: false,
    },
    {
      id: "report",
      mark: "¶",
      label: "결과 정리",
      meta: allDone ? "검증 결과 정리 완료" : "검증 결과 대기",
      state: signalState(stageIndex >= 3, false, allDone),
      primary: true,
    },
  ];

  const nodes = candidates.filter(
    (node): node is AgentTopologyNode => node.state !== "pending",
  );
  const nodeState = new Map(nodes.map((node) => [node.id, node.state]));
  const visible = new Set(nodeState.keys());

  const connections: Array<{ source: string; target: string }> = [];
  const connect = (source: string, target: string) => {
    if (visible.has(source) && visible.has(target)) connections.push({ source, target });
  };

  connect("lead", "research");

  const researchBranches = RESEARCH_BRANCHES.filter((id) => visible.has(id));
  if (researchBranches.length > 0) {
    for (const id of researchBranches) {
      connect("research", id);
      connect(id, "verify");
    }
  } else {
    connect("research", "verify");
  }

  const verifyBranches = VERIFY_BRANCHES.filter((id) => visible.has(id));
  if (verifyBranches.length > 0) {
    for (const id of verifyBranches) {
      connect("verify", id);
      connect(id, "report");
    }
  } else {
    connect("verify", "report");
  }

  const edgeState = (source: string, target: string): SignalEdgeState => {
    const sourceState = nodeState.get(source);
    const targetState = nodeState.get(target);
    if (targetState === "rejected") return "rejected";
    if (targetState === "active" || sourceState === "active") return "active";
    if (targetState === "done") return "done";
    return "idle";
  };

  const edges = connections.map(({ source, target }) => ({
    id: `${source}-${target}`,
    source,
    target,
    state: edgeState(source, target),
  }));

  return { nodes, edges, stats };
}
