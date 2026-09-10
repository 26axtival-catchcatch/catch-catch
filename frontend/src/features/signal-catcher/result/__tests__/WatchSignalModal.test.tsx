import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

import { OVERLAY_ID } from "../../Overlay";
import { WatchSignalModal } from "../WatchSignalModal";
import { SignalClient, type AlertRecommendation, type SignalProposal } from "../signal-client";

const metrics = [
  { key: "affected_customer_count", label: "대상 고객 수", value: 70, unit: "customers" },
  { key: "average_steps", label: "평균 탐색 횟수", value: 2.5, unit: "events" },
];
const proposal: SignalProposal = {
  proposalId: "proposal-1", title: "로밍 검색 후 이탈", description: "반복 탐색",
  populationDescription: "로밍 검색 고객", limitations: [], sourceIds: ["app"], metrics,
};
const criteria: AlertRecommendation[] = metrics.map((m) => ({
  recommendationId: m.key, metricKey: m.key, metricLabel: m.label, metricUnit: m.unit,
  threshold: m.value, comparisonUnit: m.unit, kind: "value", operator: "gte",
  windowSeconds: 86400, rationale: "분석 지표를 그대로 확인합니다.",
}));

function mount({ revision = 0, items = [], proposals = [proposal] }: {
  revision?: number; items?: Array<AlertRecommendation & { ruleId: string }>;
  proposals?: SignalProposal[];
} = {}) {
  const overlay = document.createElement("div");
  overlay.id = OVERLAY_ID;
  document.body.append(overlay);
  vi.spyOn(SignalClient.prototype, "listProposals").mockResolvedValue(proposals);
  vi.spyOn(SignalClient.prototype, "registerProposal").mockResolvedValue({
    signalId: "signal-1", proposalId: proposal.proposalId,
    alertRecommendations: { status: "ready", source: "measurement", items: criteria, reason: null },
  });
  vi.spyOn(SignalClient.prototype, "getAlertRules").mockResolvedValue({ signalId: "signal-1", revision, items });
  const generate = vi.spyOn(SignalClient.prototype, "generateAlertRecommendations");
  const save = vi.spyOn(SignalClient.prototype, "replaceAlertRules").mockResolvedValue({
    signalId: "signal-1", revision: revision + 1, items: [],
  });
  const onSaved = vi.fn();
  render(<WatchSignalModal runId="run-1" fallbackMetrics={[]} onClose={vi.fn()} onSaved={onSaved} onGoHome={vi.fn()} />);
  return { save, generate, onSaved };
}

afterEach(() => {
  cleanup();
  document.getElementById(OVERLAY_ID)?.remove();
  vi.restoreAllMocks();
});

it("shows the original signal metrics once and saves only the edited thresholds", async () => {
  const user = userEvent.setup();
  const { save, generate, onSaved } = mount();
  const count = await screen.findByRole("spinbutton", { name: "대상 고객 수 기준값" });
  expect(screen.getByRole("heading", { name: "어떤 변화가 생기면 알려드릴까요?" })).toBeVisible();
  expect(screen.getAllByRole("spinbutton")).toHaveLength(2);
  expect(screen.getByText("70명")).toBeVisible();
  expect(screen.getByText("2.5회")).toBeVisible();
  expect(screen.getByText(proposal.title)).toBeVisible();
  expect(generate).not.toHaveBeenCalled();
  expect(screen.queryByText(/AI.*제안/)).not.toBeInTheDocument();
  await user.clear(count);
  await user.type(count, "25");
  expect(within(count.closest("li")!).getByText(/이상이면 알려드려요/)).toBeVisible();
  await user.click(screen.getByRole("button", { name: "변화 캐치 시작하기" }));
  await waitFor(() => expect(save).toHaveBeenCalledWith("signal-1", 0, [
    { recommendationId: "affected_customer_count", threshold: 25 },
    { recommendationId: "average_steps", threshold: 2.5 },
  ]));
  expect(onSaved).toHaveBeenCalledWith(2);
});

it("keeps a saved opt-out unchecked when reopened", async () => {
  mount({ revision: 2 });
  await screen.findByRole("spinbutton", { name: "대상 고객 수 기준값" });
  expect(screen.getAllByRole("checkbox").every((input) => !(input as HTMLInputElement).checked)).toBe(true);
});

it("preserves a saved value threshold and does not substitute unrelated conditions", async () => {
  mount({ revision: 1, items: [{ ...criteria[0], threshold: 42, ruleId: "saved-1" }] });
  expect(await screen.findByRole("spinbutton", { name: "대상 고객 수 기준값" })).toHaveValue(42);
  expect(screen.getByRole("spinbutton", { name: "평균 탐색 횟수 기준값" })).toBeDisabled();
});

it("shows one set of metrics when multiple proposals refer to the same registered signal", async () => {
  const user = userEvent.setup();
  const { save } = mount({ proposals: [proposal, { ...proposal, proposalId: "same-definition" }] });
  await waitFor(() => expect(screen.getAllByRole("spinbutton")).toHaveLength(2));
  await user.click(screen.getByRole("button", { name: "변화 캐치 시작하기" }));
  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
});
