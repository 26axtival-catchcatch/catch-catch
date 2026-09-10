import type { AgentActivity } from "../../customer-intelligence/agent-activity";

export const AGENT_ROLES = {
  coordinator: { label: "조율 에이전트", nickname: "길잡이", description: "질문을 읽고, 함께 찾을 방향을 잡아요" },
  investigator: { label: "조사 에이전트", nickname: "탐정", description: "고객이 남긴 단서를 하나씩 따라가요" },
  verifier: { label: "검증 에이전트", nickname: "체커", description: "찾은 단서가 맞는지 근거로 다시 확인해요" },
  reporter: { label: "정리 에이전트", nickname: "기록가", description: "찾은 것과 아직 모르는 것을 정리해요" },
} satisfies Record<AgentActivity["role"], { label: string; nickname: string; description: string }>;

export const ACTIVITY_STATUS = {
  queued: "대기", started: "진행 중", completed: "완료", failed: "실패", cancelled: "중단",
} satisfies Record<AgentActivity["status"], string>;

export interface ConversationAgent {
  id: string;
  role: AgentActivity["role"];
  label: string;
  nickname: string;
  roundIndex: number;
  status: AgentActivity["status"];
  messageCount: number;
  latestText: string;
}

export interface ConversationMessage {
  id: string;
  agentId: string;
  activity: AgentActivity;
  kind: "commentary" | "summary";
  text: string;
}

const LEGACY_STATUS_LABELS = new Set(["조사 배분", "가설 조사", "독립 검증", "보고서 작성"]);

function conversationKind(activity: AgentActivity, initialText?: string): ConversationMessage["kind"] | null {
  if (activity.status !== "completed") return null;
  if (activity.kind === "model") return activity.message_kind === "commentary" ? "commentary" : null;
  if (activity.kind !== "agent") return null;
  if (activity.message_kind === "summary") return "summary";
  // Older journals stored completed role summaries before message_kind existed.
  if (initialText === activity.display_text) return null;
  return !LEGACY_STATUS_LABELS.has(activity.display_text.trim()) ? "summary" : null;
}

/** Project only public progress; timestamps order parallel work, input order breaks ties. */
export function buildConversation(activities: readonly AgentActivity[]) {
  const nodes = new Map(activities.map(activity => [activity.node_id, activity]));
  const initialTexts = new Map(activities.filter(activity => activity.kind === "agent"
    && (activity.status === "queued" || activity.status === "started"))
    .map(activity => [activity.node_id, activity.display_text]));
  const owner = (activity: AgentActivity): string => {
    let node = activity;
    const visited = new Set<string>();
    while (node.kind !== "agent" && node.parent_node_id && !visited.has(node.node_id)) {
      visited.add(node.node_id);
      const parent = nodes.get(node.parent_node_id);
      if (!parent) return node.parent_node_id;
      node = parent;
    }
    return node.kind === "agent" ? node.node_id : `${node.role}:${node.task_id}:${node.round_index}`;
  };
  const seen = new Set<string>();
  const ordered = [...activities]
    .sort((a, b) => Date.parse(a.occurred_at) - Date.parse(b.occurred_at))
    .flatMap(activity => {
      const id = JSON.stringify([activity.node_id, activity.status, activity.occurred_at,
        activity.display_text, activity.message_kind, activity.message_text]);
      if (seen.has(id)) return [];
      seen.add(id);
      return [{ id, agentId: owner(activity), activity }];
    });
  const byId = new Map<string, ConversationAgent>();
  const messages: ConversationMessage[] = [];
  for (const { id, agentId, activity } of ordered) {
    const current = byId.get(agentId);
    if (current) {
      // An agent's lifecycle is authoritative; children may finish out of order.
      if (activity.kind === "agent" || !nodes.has(agentId)) current.status = activity.status;
    } else {
      byId.set(agentId, {
        id: agentId, role: activity.role, label: AGENT_ROLES[activity.role].label,
        nickname: AGENT_ROLES[activity.role].nickname,
        roundIndex: activity.round_index, status: activity.status, messageCount: 0,
        latestText: "",
      });
    }
    const kind = conversationKind(activity, initialTexts.get(activity.node_id));
    if (kind) {
      const sourceText = activity.message_text ?? activity.display_text;
      if (LEGACY_STATUS_LABELS.has(sourceText.trim()) || sourceText.trim() === "모델 응답 생성") continue;
      // Older saved summaries/commentary may predate server-side identifier masking.
      const text = sourceText.replace(/customer[_-][a-z0-9_-]+/gi, "[고객 식별자 숨김]");
      messages.push({ id, agentId, activity, kind, text });
      const agent = byId.get(agentId)!;
      agent.messageCount += 1;
      agent.latestText = text;
    }
  }
  const agents = [...byId.values()];
  const roleIndexes = new Map<string, number>();
  for (const agent of agents) {
    const index = (roleIndexes.get(agent.role) ?? 0) + 1;
    roleIndexes.set(agent.role, index);
    if (agents.filter(item => item.role === agent.role).length > 1) {
      agent.label += ` ${index}`;
      agent.nickname += ` ${index}`;
    }
  }
  return { agents, messages };
}
