import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OVERLAY_ID } from "../../Overlay";
import { REPORT } from "../../state/mock";
import type { CatchReport } from "../../state/types";
import { ResultScreen } from "../ResultScreen";

const DENSE_EVIDENCE_IDS = Array.from(
  { length: 12 },
  (_, index) => `ev-hackathon_search_history-${String(index + 1).padStart(2, "0")}`,
);

const STRUCTURED_SUMMARY = `확정 432명, 미확정 후보 0명입니다. [조사 배경 및 개요]
AI 검색을 수행한 이후 목적 화면으로 진행하지 못하고 다른 메뉴를 탐색하거나 이탈한 고객 여정을 분석하였습니다. 관찰 결과 두 가지 독립적인 해맴 패턴이 확정되었습니다.

[패턴 1: 부가서비스 AI 검색 후 바로가기 링크 부재로 인한 타 메뉴 방황]
- 행동 근거: 바로가기 링크가 없는 안내를 확인한 고객이 무관한 메뉴를 반복 순회했습니다.
- 정상 대조군 비교: 바로가기 링크를 통한 고객군은 자가 처리를 완료했습니다.
- 최종 해결 및 개선 제안: 검색 결과에 '조회/해지 바로가기' CTA를 기본 탑재합니다.

[패턴 2: 로밍 AI 검색 후 세부 요금제 옵션 반복 탐색 및 이탈]
- 행동 근거: 4GB, 8GB, 12GB 상세 페이지를 순차적으로 조회하다 결정을 내리지 못했습니다.
- 정상 대조군 비교: 단일 추천 요금제를 확인한 고객은 즉시 가입을 완료했습니다.
- 최종 해결 및 개선 제안: 용량과 기간을 비교하는 표와 원클릭 가입 경로를 제공합니다.

[분석 한계]
제공된 기간 내 관찰된 로그에 기반하며 상담 세부 데이터가 부재합니다. [추가 관찰] 이 표기는 새 형식으로 원문에 그대로 남아야 합니다.`;

function denseReport(): CatchReport {
  return {
    ...REPORT,
    findings: [
      {
        ...REPORT.findings[0],
        statement:
          "로밍 요금제를 비교하다 이탈한 고객이 84명입니다. 이들은 세부 옵션을 여러 번 오간 뒤 가입을 끝내지 못했고 상담으로 이동했습니다.",
        evidenceIds: DENSE_EVIDENCE_IDS,
      },
    ],
    actions: [
      {
        ...REPORT.actions[0],
        reason:
          "개선 가설입니다. 요금제별 핵심 차이를 한눈에 보여줘야 합니다. 체류 국가와 예상 사용량을 기준으로 맞춤 요금제를 추천하면 선택 부담을 줄일 수 있습니다.",
        evidenceIds: DENSE_EVIDENCE_IDS,
      },
    ],
  };
}

function renderResult(report: CatchReport = denseReport()) {
  const onLoadEvidence = vi.fn();
  const onOpenAction = vi.fn();
  const overlay = document.createElement("div");
  overlay.id = OVERLAY_ID;
  document.body.append(overlay);

  render(
    <ResultScreen
      report={report}
      outcome="completed"
      onOpenTrace={vi.fn()}
      onRestart={vi.fn()}
      onOpenAction={onOpenAction}
      experimentOf={() => undefined}
      highlightActionId={null}
      onHighlightSeen={vi.fn()}
      applied={[]}
      evidence={{}}
      evidenceLoadingId={null}
      evidenceErrorId={null}
      onLoadEvidence={onLoadEvidence}
      onGoHome={vi.fn()}
    />,
  );

  return { onLoadEvidence, onOpenAction };
}

afterEach(() => {
  cleanup();
  document.getElementById(OVERLAY_ID)?.remove();
});

describe("ResultScreen", () => {
  it("keeps long findings and actions progressive while preserving their full copy", async () => {
    const user = userEvent.setup();
    renderResult();

    expect(
      screen.getByRole("heading", {
        name: "로밍 요금제를 비교하다 이탈한 고객이 84명입니다.",
      }),
    ).toBeInTheDocument();
    const findingDetail = screen.getByText(
      "이들은 세부 옵션을 여러 번 오간 뒤 가입을 끝내지 못했고 상담으로 이동했습니다.",
    );
    expect(findingDetail).not.toBeVisible();

    await user.click(screen.getByText("검증 내용 자세히"));
    expect(findingDetail).toBeVisible();

    expect(
      screen.getByRole("heading", { name: REPORT.actions[0].title }),
    ).toBeInTheDocument();
    expect(screen.queryByText("개선 가설입니다.")).not.toBeInTheDocument();
    expect(screen.getByText("요금제별 핵심 차이를 한눈에 보여줘야 합니다.")).toBeVisible();

    const actionDetail = screen.getByText(
      "체류 국가와 예상 사용량을 기준으로 맞춤 요금제를 추천하면 선택 부담을 줄일 수 있습니다.",
    );
    expect(actionDetail).not.toBeVisible();
    await user.click(screen.getByText("판단 근거 자세히"));
    expect(actionDetail).toBeVisible();
  });

  it("summarizes dense evidence without exposing raw ids, then opens a selected record", async () => {
    const user = userEvent.setup();
    const { onLoadEvidence } = renderResult();

    const evidenceSummaries = screen.getAllByText("근거 12개");
    expect(evidenceSummaries).toHaveLength(2);

    for (const evidenceId of DENSE_EVIDENCE_IDS) {
      expect(screen.queryByText(evidenceId, { exact: false })).not.toBeInTheDocument();
      expect(document.querySelector(`[title="${evidenceId}"]`)).toBeNull();
    }

    await user.click(evidenceSummaries[0]);
    const findingEvidence = evidenceSummaries[0].closest("details");
    expect(findingEvidence).not.toBeNull();
    const firstEvidence = within(findingEvidence!).getByRole("button", {
      name: "AI검색 이력 근거 1 열기",
    });
    expect(firstEvidence).toBeVisible();
    expect(firstEvidence).toHaveAccessibleName("AI검색 이력 근거 1 열기");

    await user.click(firstEvidence);
    expect(onLoadEvidence).toHaveBeenCalledWith(DENSE_EVIDENCE_IDS[0]);
    await waitFor(() => {
      expect(screen.getByRole("dialog", { name: "원본 근거" })).toBeInTheDocument();
    });
  });

  it("keeps the actionable CTA connected to its action", async () => {
    const user = userEvent.setup();
    const { onOpenAction } = renderResult();

    await user.click(screen.getByRole("button", { name: "미리보기" }));
    expect(onOpenAction).toHaveBeenCalledTimes(1);
    expect(onOpenAction).toHaveBeenCalledWith(REPORT.actions[0].actionId);
  });

  it("turns a structured executive summary into readable sections without dropping unknown copy", async () => {
    const user = userEvent.setup();
    renderResult({ ...denseReport(), summary: STRUCTURED_SUMMARY });

    expect(
      screen.getByRole("heading", { name: "확정 432명, 미확정 후보 0명입니다." }),
    ).toBeVisible();

    const summaryToggle = screen.getByText("전체 분석 요약 보기");
    const summaryDetails = summaryToggle.closest("details");
    expect(summaryDetails).not.toBeNull();
    expect(within(summaryDetails!).getByRole("heading", { name: "조사 배경 및 개요" })).not.toBeVisible();

    await user.click(summaryToggle);

    expect(within(summaryDetails!).getByRole("heading", { name: "조사 배경 및 개요" })).toBeVisible();
    expect(
      within(summaryDetails!).getByRole("heading", {
        name: "부가서비스 AI 검색 후 바로가기 링크 부재로 인한 타 메뉴 방황",
      }),
    ).toBeVisible();
    expect(within(summaryDetails!).getByRole("heading", { name: "분석 한계" })).toBeVisible();
    expect(within(summaryDetails!).getAllByText("행동 근거")).toHaveLength(2);
    expect(within(summaryDetails!).getAllByText("정상 대조군 비교")).toHaveLength(2);
    expect(within(summaryDetails!).getAllByText("최종 해결 및 개선 제안")).toHaveLength(2);
    expect(within(summaryDetails!).getByText(/\[추가 관찰\] 이 표기는 새 형식/)).toBeVisible();
  });

  it("keeps an unrecognized detail format as readable text", async () => {
    const user = userEvent.setup();
    const rawDetail = "아직 정의되지 않은 => 새 요약 형식입니다.";
    renderResult({
      ...denseReport(),
      summary: `핵심 결론입니다. ${rawDetail}`,
    });

    await user.click(screen.getByText("전체 분석 요약 보기"));
    expect(screen.getByText(rawDetail)).toBeVisible();
  });

  it("shows explicit empty messages when there are no verified findings or actions", () => {
    renderResult({
      ...REPORT,
      findings: REPORT.findings.filter((finding) => finding.verdict === "rejected"),
      actions: [],
    });

    const insight = screen.getByRole("region", {
      name: "검증된 발견과 다음 행동",
    });
    expect(within(insight).getByText("검증을 통과한 발견이 없습니다.")).toBeInTheDocument();
    expect(within(insight).getByText("제안할 다음 행동이 없습니다.")).toBeInTheDocument();
    expect(within(insight).queryByText(REPORT.findings[0].statement)).not.toBeInTheDocument();
  });
});
