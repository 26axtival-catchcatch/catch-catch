import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BriefingScreen } from "../BriefingScreen";
import { DEMO_BRIEFING } from "../briefing-mock";

afterEach(cleanup);

describe("BriefingScreen", () => {
  it("opens the full discovery composer as a briefing tab", () => {
    render(
      <BriefingScreen
        briefing={DEMO_BRIEFING}
        question=""
        onQuestionChange={vi.fn()}
        onOpenSignal={vi.fn()}
        onAsk={vi.fn()}
        notice={null}
        suggestedQuestions={[]}
      />,
    );

    expect(screen.queryByText("더 궁금한 변화가 있나요?")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "＋ 새 시그널 찾기" }));

    expect(screen.getByRole("heading", { name: "지금 궁금한 고객의 신호를 찾아볼까요?" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "＋ 새 시그널 찾기" })).toHaveAttribute("aria-selected", "true");

    fireEvent.click(screen.getByRole("tab", { name: /1 ·/ }));
    expect(screen.getByRole("button", { name: "자세히 보기" })).toBeInTheDocument();
  });
});
