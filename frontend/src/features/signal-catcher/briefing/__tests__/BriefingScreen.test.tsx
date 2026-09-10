import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BriefingScreen } from "../BriefingScreen";
import { DEMO_BRIEFING } from "../briefing-mock";

afterEach(cleanup);

describe("BriefingScreen", () => {
  it("opens the full discovery composer and returns with ordinary buttons", async () => {
    const user = userEvent.setup();
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
    await user.click(screen.getAllByRole("button", { name: "＋ 새 시그널 찾기" })[0]);

    expect(screen.getByRole("heading", { name: "지금 궁금한 고객의 신호를 찾아볼까요?" })).toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();

    const firstSignal = screen.getByRole("button", { name: /1 ·/ });
    await user.click(firstSignal);
    expect(firstSignal).toHaveAttribute("aria-current", "true");
    expect(firstSignal).not.toHaveAttribute("aria-pressed");
    expect(screen.getByRole("button", { name: "시그널 상세 보기" })).toBeInTheDocument();
  });

  it("hides request controls and previous briefing metadata when briefing is empty", () => {
    render(
      <BriefingScreen
        briefing={{
          ...DEMO_BRIEFING,
          signals: [],
          total: 0,
          requestCount: 9,
          watchingCount: 7,
          pastDates: ["9/7", "9/5"],
        }}
        question=""
        onQuestionChange={vi.fn()}
        onOpenSignal={vi.fn()}
        onAsk={vi.fn()}
        notice={null}
        suggestedQuestions={[]}
      />,
    );

    expect(screen.getByRole("article", { name: "브리핑 없음" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "지금 궁금한 고객의 신호를 찾아볼까요?" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/내 요청 \d+건 반영/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /새 시그널 찾기|지켜볼 것 요청하기/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/캐치 중 \d+건/)).not.toBeInTheDocument();
    expect(screen.queryByText("9/7")).not.toBeInTheDocument();
    expect(screen.queryByText("9/5")).not.toBeInTheDocument();
  });
});
