import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { RunSnapshot } from "../../../customer-intelligence/contracts";
import { SignalCatcherApp } from "../../SignalCatcherApp";
import { DEMO_BRIEFING } from "../../briefing/briefing-mock";
import { LIVE_END_AT, LIVE_START_AT } from "../../state/live-adapter";
import { type SignalCatcherClient, useLiveCatchSession } from "../../state/use-live-catch-session";

vi.mock("next/dynamic", () => ({ default: () => () => <div>실행 그래프</div> }));
vi.mock("../../state/use-catch-session", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../state/use-catch-session")>(),
  useCatchSession: () => useLiveCatchSession(client),
  useDemoOptions: () => ({
    flags: new Set(), pause: null, speed: 1, burst: "lens", view: null,
    main: "briefing", briefingEmpty: true,
  }),
}));
vi.mock("../../briefing/use-signal-briefing", () => ({
  useSignalBriefing: () => ({ briefing: DEMO_BRIEFING, loading: false, error: null, refresh: vi.fn() }),
}));
vi.mock("../../alerts/use-signal-alerts", () => ({
  useSignalAlerts: () => ({ events: [], error: null, clear: vi.fn(), refresh: vi.fn() }),
}));

const question = "내일 날씨를 알려 줘";
const client: SignalCatcherClient = {
  listSources: vi.fn(async () => ({ items: [] })), createRun: vi.fn(),
  getRun: vi.fn(async (): Promise<RunSnapshot> => ({
    run_id: "run-input-blocked", status: "failed",
    request: { question, start_at: LIVE_START_AT, end_at: LIVE_END_AT, enabled_sources: [] },
    created_at: "2026-09-11T00:00:00Z", updated_at: "2026-09-11T00:00:00Z",
    agent_mode: "bedrock", report: null,
    error: {
      code: "input_out_of_scope", message: "고객 데이터에 관한 질문을 입력해 주세요.",
      suggested_questions: ["로밍 요금제 탐색 중 이탈한 고객을 찾아 주세요."],
    },
    plan_history: [], facts: [],
  })),
  async *streamRunEvents() {},
  submitClarification: vi.fn(), getJourney: vi.fn(), getEvidence: vi.fn(),
};

beforeEach(() => {
  vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("opens the populated briefing composer with the blocked question ready to edit", async () => {
  render(<SignalCatcherApp initialRunId="run-input-blocked" />);
  fireEvent.click(await screen.findByRole("button", { name: "질문 수정하기" }));
  expect(screen.getByRole("textbox", { name: "분석 질문" })).toHaveValue(question);
  expect(screen.getByRole("heading", { name: "지금 궁금한 고객의 신호를 찾아볼까요?" })).toBeVisible();
  expect(client.createRun).not.toHaveBeenCalled();
});
