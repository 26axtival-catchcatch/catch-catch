import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AnyRunStreamEvent } from "../../../customer-intelligence/contracts";
import { STAGES } from "../../state/mock";
import type { CatchSession } from "../../state/types";
import { CatchingScreen } from "../CatchingScreen";
import { OVERLAY_ID } from "../../Overlay";

vi.mock("next/dynamic", () => ({ default: () => () => <div>실행 그래프</div> }));
beforeEach(() => {
  const overlay = document.createElement("div");
  overlay.id = OVERLAY_ID;
  document.body.append(overlay);
});
afterEach(() => { cleanup(); document.getElementById(OVERLAY_ID)?.remove(); });

const session: CatchSession = {
  phase: "catching", question: "고객 행동을 분석해 주세요", stages: STAGES,
  activeStage: null, clarification: null, outcome: null, report: null,
  failureReason: null, suggestedQuestions: [],
};
const props = {
  bursting: false, flatline: false, burstMark: "lens" as const, speed: 1,
  log: [], activities: [], topologyEvents: [], onAnswerClarification: vi.fn(),
  onRetry: vi.fn(), onGiveUp: vi.fn(),
};

describe("input check in CatchingScreen", () => {
  it.each([
    { label: "before connection", events: [] as AnyRunStreamEvent[] },
    { label: "after connection", events: [{ id: 1, type: "run_started", data: { status: "running" } }] as AnyRunStreamEvent[] },
  ])(
    "shows input checking before the goal is created: $label",
    ({ events }) => {
      render(<CatchingScreen {...props} session={session} topologyEvents={events} />);
      expect(screen.getByText("입력한 질문이 분석 가능한지 확인하고 있어요")).toBeVisible();
    },
  );

  it.each(["input_out_of_scope", "input_unsafe"])(
    "offers question editing without retry for %s",
    (failureCode) => {
      const onGiveUp = vi.fn();
      render(<CatchingScreen {...props} onGiveUp={onGiveUp} session={{
        ...session, outcome: "failed", failureCode,
        failureReason: "고객 데이터로 확인할 수 있는 질문을 입력해 주세요.",
      }} />);
      expect(screen.getByRole("alert")).toHaveTextContent("이 질문으로는 분석을 시작할 수 없어요");
      expect(screen.queryByRole("button", { name: "같은 조건으로 다시 분석" })).not.toBeInTheDocument();
      expect(screen.queryByText(/같은 조건으로 처음부터 다시 분석/)).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "질문 수정하기" }));
      expect(onGiveUp).toHaveBeenCalledOnce();
    },
  );

  it("retains retry for a temporary input-check failure", () => {
    const onRetry = vi.fn();
    render(<CatchingScreen {...props} onRetry={onRetry} session={{
      ...session, outcome: "failed", failureCode: "intake_failed",
      failureReason: "질문 확인 중 일시적인 오류가 발생했어요.",
    }} />);
    fireEvent.click(screen.getByRole("button", { name: "같은 조건으로 다시 분석" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("clears the previous answer when another clarification arrives", () => {
    const onAnswerClarification = vi.fn();
    const first = { ...session, clarification: {
      clarificationId: "clarify-1", question: "어떤 고객인가요?", hint: "대상을 알려 주세요.",
    } };
    const { rerender } = render(<CatchingScreen {...props} onAnswerClarification={onAnswerClarification} session={first} />);
    fireEvent.change(screen.getByRole("textbox", { name: "추가 조건 답변" }), { target: { value: "  미가입 고객  " } });
    fireEvent.click(screen.getByRole("button", { name: "답변하고 계속" }));
    expect(onAnswerClarification).toHaveBeenCalledWith("미가입 고객");
    rerender(<CatchingScreen {...props} onAnswerClarification={onAnswerClarification} session={{
      ...first, clarification: { clarificationId: "clarify-2", question: "어떤 행동을 확인할까요?", hint: "행동을 알려 주세요." },
    }} />);
    expect(screen.getByRole("textbox", { name: "추가 조건 답변" })).toHaveValue("");
    expect(screen.getByRole("button", { name: "답변하고 계속" })).toBeDisabled();
  });
});
