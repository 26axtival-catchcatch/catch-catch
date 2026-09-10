import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BriefingScreen } from "../BriefingScreen";
import { DEMO_BRIEFING } from "../briefing-mock";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("BriefingScreen", () => {
  it.each([
    { state: "loading", loading: true, error: null },
    { state: "failed", loading: false, error: "브리핑 조회 실패" },
    { state: "empty", loading: false, error: null },
  ])("allows a new signal request when briefing is $state", async ({ loading, error }) => {
    vi.stubGlobal("matchMedia", () => ({ matches: true }));
    const user = userEvent.setup();
    const onAsk = vi.fn();
    const onRetry = vi.fn();
    const question = "상담 뒤 같은 문의를 반복한 고객";
    render(
      <BriefingScreen
        briefing={{ ...DEMO_BRIEFING, signals: [], total: 0, nextOffset: null }}
        loading={loading}
        error={error}
        question={question}
        onQuestionChange={vi.fn()}
        onOpenSignal={vi.fn()}
        onAsk={onAsk}
        onRetry={onRetry}
        notice={null}
        suggestedQuestions={[]}
        sourceOptions={[{
          id: "hackathon_voc",
          label: "상담 이력",
          note: "상담 데이터",
          topics: [],
          interval: "2026-09-04 – 2026-09-11",
        }]}
        initialStartAt="2026-09-04T00:00:00+09:00"
        initialEndAt="2026-09-11T00:00:00+09:00"
      />,
    );

    expect(screen.getByRole("textbox", { name: "분석 질문" })).toHaveValue(question);
    await user.click(screen.getByRole("button", { name: "고객 변화 찾기" }));
    expect(onAsk).toHaveBeenCalledWith(question, {
      enabledSources: ["hackathon_voc"],
      startAt: "2026-09-04T00:00:00+09:00",
      endAt: "2026-09-11T00:00:00+09:00",
    });
    if (error) {
      await user.click(screen.getByRole("button", { name: "다시 불러오기" }));
      expect(onRetry).toHaveBeenCalledOnce();
    }
  });

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
