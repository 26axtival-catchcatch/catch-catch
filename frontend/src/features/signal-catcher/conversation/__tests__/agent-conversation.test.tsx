import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { AgentActivity } from "../../../customer-intelligence/agent-activity";
import { buildConversation } from "../agent-conversation";
import { AgentConversation } from "../AgentConversation";

afterEach(cleanup);

export function activity(overrides: Partial<AgentActivity> = {}): AgentActivity {
  return {
    schema_version: 1, node_id: "agent-a", parent_node_id: null, depends_on: [],
    kind: "agent", role: "investigator", task_id: "task-a", round_index: 0,
    status: "completed", message_kind: "summary", name: "investigator", display_text: "검색 후 행동을 조사합니다.",
    occurred_at: "2026-09-10T08:00:00Z", duration_ms: null, model: null,
    details: { candidates: [], decisions: [], limitations: [] }, ...overrides,
  };
}

const tool = activity({ node_id: "tool-a", parent_node_id: "model-a", kind: "model", message_kind: "commentary",
  name: "query_data", display_text: "관련 행동 12건을 찾았습니다.", occurred_at: "2026-09-10T08:00:02Z" });
const model = activity({ node_id: "model-a", parent_node_id: "agent-a", kind: "model", message_kind: "commentary",
  display_text: "데이터 조회를 준비합니다.", occurred_at: "2026-09-10T08:00:01Z" });
const agentB = activity({ node_id: "agent-b", task_id: "task-b", display_text: "상담 기록을 조사합니다.",
  occurred_at: "2026-09-10T08:00:01Z" });

describe("agent conversation projection", () => {
  it("attributes nested work to agent instances and keeps global chronological order", () => {
    const result = buildConversation([tool, activity(), model, agentB, activity()]);
    expect(result.agents).toHaveLength(2);
    expect(result.messages.map(m => m.activity.display_text)).toEqual([
      "검색 후 행동을 조사합니다.", "데이터 조회를 준비합니다.", "상담 기록을 조사합니다.", "관련 행동 12건을 찾았습니다.",
    ]);
    expect(result.messages.at(-1)?.agentId).toBe("agent-a");
    expect(result.agents.map(a => a.label)).toEqual(["조사 에이전트 1", "조사 에이전트 2"]);
  });

  it("keeps agent presence and lifecycle while hiding routine execution logs", () => {
    const result = buildConversation([
      activity({ message_kind: null, status: "queued", display_text: "조사 배분" }),
      activity({ message_kind: null, status: "started", display_text: "가설 조사" }),
      activity({ status: "completed", display_text: "조사를 마쳤습니다." }),
      activity({ node_id: "agent-retry", round_index: 1, status: "started", message_kind: null, display_text: "추가 조사합니다." }),
      activity({ node_id: "tool-log", kind: "tool", parent_node_id: "agent-a", message_kind: null, display_text: "데이터 목록 확인" }),
      activity({ node_id: "model-log", kind: "model", parent_node_id: "agent-a", message_kind: null, display_text: "모델 응답 생성" }),
      activity({ node_id: "assessment", kind: "assessment", parent_node_id: "agent-a", message_kind: null, display_text: "서버의 근거 검사를 반영한 후보별 판정입니다." }),
    ]);
    expect(result.messages.map(message => message.activity.display_text)).toEqual(["조사를 마쳤습니다."]);
    expect(result.agents).toHaveLength(2);
    expect(result.agents[0].status).toBe("completed");
    expect(result.agents[1].roundIndex).toBe(1);
    expect(result.agents[1].status).toBe("started");
    expect(result.agents[1].messageCount).toBe(0);
  });

  it("keeps legacy saved summaries without treating old completed labels as speech", () => {
    const result = buildConversation([
      activity({ message_kind: undefined, display_text: "완료된 공개 분석 요약입니다." }),
      activity({ node_id: "legacy-empty", message_kind: undefined, display_text: "가설 조사" }),
      activity({ node_id: "old-model", kind: "model", message_kind: undefined, display_text: "모델 응답 생성" }),
    ]);
    expect(result.messages.map(message => message.activity.display_text)).toEqual(["완료된 공개 분석 요약입니다."]);
  });

  it("does not turn an unchanged assignment into speech when an agent ends without a summary", () => {
    const result = buildConversation([
      activity({ status: "started", message_kind: null, display_text: "로밍 검색 고객을 조사합니다." }),
      activity({ status: "completed", message_kind: null, display_text: "로밍 검색 고객을 조사합니다." }),
    ]);
    expect(result.messages).toHaveLength(0);
    expect(result.agents[0].status).toBe("completed");
  });

  it("masks customer identifiers from older saved prose without mutating the event", () => {
    const original = activity({ display_text: "customer_abc123가 이 그룹에 포함됩니다." });
    const result = buildConversation([original]);
    expect(result.messages[0].text).toBe("[고객 식별자 숨김]가 이 그룹에 포함됩니다.");
    expect(result.agents[0].latestText).not.toContain("customer_abc123");
    expect(original.display_text).toContain("customer_abc123");
  });

  it("uses the chat-only text without replacing the existing execution label", () => {
    const comment = activity({ node_id: "model-comment", parent_node_id: "agent-a", kind: "model",
      message_kind: "commentary", message_text: "이제 고객 수를 집계하겠습니다.", display_text: "모델 응답 생성" });
    const result = buildConversation([activity(), comment]);
    expect(result.messages.at(-1)?.text).toBe("이제 고객 수를 집계하겠습니다.");
    expect(result.messages.at(-1)?.activity.display_text).toBe("모델 응답 생성");
    render(<AgentConversation activities={[activity(), comment]} />);
    const timeline = screen.getByRole("region", { name: "에이전트 메시지" });
    expect(within(timeline).getByText("이제 고객 수를 집계하겠습니다.")).toBeInTheDocument();
    expect(within(timeline).queryByText("모델 응답 생성")).not.toBeInTheDocument();
  });
});

describe("AgentConversation", () => {
  it("filters an individual agent including its model commentary", () => {
    render(<AgentConversation activities={[activity(), model, agentB, tool]} />);
    const timeline = screen.getByRole("region", { name: "에이전트 메시지" });
    expect(within(timeline).getByText(agentB.display_text)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /조사 에이전트 1/ }));
    expect(within(timeline).queryByText(agentB.display_text)).not.toBeInTheDocument();
    expect(within(timeline).getByText(tool.display_text)).toBeInTheDocument();
    expect(within(timeline).queryByText(/task-a|원본.*payload/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /전체 대화/ }));
    expect(within(timeline).getByText(agentB.display_text)).toBeInTheDocument();
  });

  it("shows honest historical empty and paused states", () => {
    const { rerender } = render(<AgentConversation activities={[]} completed />);
    expect(screen.getByText("저장된 에이전트 대화가 없어요")).toBeInTheDocument();
    rerender(<AgentConversation activities={[]} halted />);
    expect(screen.getByText("분석이 잠시 멈춰 있어요")).toBeInTheDocument();
  });

  it("keeps the reading position when new messages arrive and lets the reader jump to latest", () => {
    const { rerender } = render(<AgentConversation activities={[activity()]} />);
    const viewport = screen.getByRole("region", { name: "에이전트 메시지" });
    Object.defineProperties(viewport, { scrollHeight: { configurable: true, value: 1000 },
      clientHeight: { configurable: true, value: 300 } });
    viewport.scrollTop = 100;
    fireEvent.scroll(viewport);
    act(() => rerender(<AgentConversation activities={[activity(), model]} />));
    expect(viewport.scrollTop).toBe(100);
    fireEvent.click(screen.getByRole("button", { name: /최신 대화로/ }));
    expect(viewport.scrollTop).toBe(1000);
  });

  it("keeps following during rapid replay when a delayed programmatic scroll event arrives", () => {
    const { rerender } = render(<AgentConversation activities={[activity()]} />);
    const viewport = screen.getByRole("region", { name: "에이전트 메시지" });
    Object.defineProperties(viewport, { scrollHeight: { configurable: true, value: 1000 },
      clientHeight: { configurable: true, value: 300 } });
    rerender(<AgentConversation activities={[activity(), model]} />);
    expect(viewport.scrollTop).toBe(1000);
    Object.defineProperty(viewport, "scrollHeight", { configurable: true, value: 1400 });
    fireEvent.scroll(viewport);
    rerender(<AgentConversation activities={[activity(), model, tool]} />);
    expect(viewport.scrollTop).toBe(1400);
  });
});
