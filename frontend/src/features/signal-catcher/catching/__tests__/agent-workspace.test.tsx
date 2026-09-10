import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { AnyRunStreamEvent } from "../../../customer-intelligence/contracts";
import type { AgentActivity } from "../../../customer-intelligence/agent-activity";
import { AgentWorkspace } from "../AgentWorkspace";
import { CatchingScreen } from "../CatchingScreen";
import { STAGES } from "../../state/mock";
import type { CatchSession } from "../../state/types";

vi.mock("next/dynamic", () => ({ default: () => () => <div>실행 그래프</div> }));
afterEach(cleanup);
const activity: AgentActivity = { schema_version: 1, node_id: "agent-v", parent_node_id: null,
  depends_on: [], kind: "agent", role: "verifier", task_id: "verify", round_index: 0,
  status: "completed", name: "verifier", display_text: "동일 고객의 근거를 확인했습니다.",
  occurred_at: "2026-09-10T08:00:00Z", duration_ms: 500, model: null,
  details: { candidates: [], decisions: [], limitations: [] } };
const events: AnyRunStreamEvent[] = [{ id: 1, type: "agent_activity", data: activity }];

it("switches between conversation and topology while retaining the selected agent", () => {
  render(<AgentWorkspace events={events} completed />);
  fireEvent.click(screen.getByRole("button", { name: /체커.*검증 에이전트.*완료/ }));
  expect(screen.getByRole("heading", { name: "체커의 단서 노트" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "토폴로지" }));
  expect(screen.getByText("실행 그래프")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "에이전트 대화" }));
  expect(screen.getByRole("heading", { name: "체커의 단서 노트" })).toBeVisible();
});

it("keeps the messages available when an analysis fails", () => {
  const session = { question: "로밍 탐색", phase: "catching", outcome: "failed", stages: STAGES,
    failureReason: "분석 연결이 끊어졌어요", clarification: null } as CatchSession;
  render(<CatchingScreen session={session} bursting={false} flatline={false} burstMark="lens"
    speed={1} log={[]} activities={[activity]} topologyEvents={events}
    onAnswerClarification={vi.fn()} onRetry={vi.fn()} onGiveUp={vi.fn()} />);
  expect(screen.getByText(activity.display_text)).toBeVisible();
  expect(screen.getByRole("button", { name: "같은 조건으로 다시 분석" })).toBeVisible();
});
