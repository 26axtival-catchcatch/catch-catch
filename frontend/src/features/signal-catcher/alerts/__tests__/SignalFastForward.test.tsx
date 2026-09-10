import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SignalClient } from "../../result/signal-client";
import { SignalFastForward } from "../SignalFastForward";

beforeEach(() => sessionStorage.clear());
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("waits for polling bootstrap and preserves the request ID across failure and remount", async () => {
  const order: string[] = [];
  const beforeRun = vi.fn(async () => { order.push("bootstrap"); });
  const run = vi.spyOn(SignalClient.prototype, "fastForward").mockImplementationOnce(async () => {
    order.push("run"); throw new Error("연결 실패");
  }).mockResolvedValue({ requestId: "saved", items: [] });
  const props = { beforeRun, onCompleted: vi.fn(), disabled: false };
  const view = render(<SignalFastForward {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "하루 빨리감기" }));
  await screen.findByRole("alert");
  expect(order).toEqual(["bootstrap", "run"]);
  const id = run.mock.calls[0][0];
  view.unmount();
  render(<SignalFastForward {...props} />);
  fireEvent.click(await screen.findByRole("button", { name: "같은 요청 재시도" }));
  await waitFor(() => expect(run).toHaveBeenCalledTimes(2));
  expect(run.mock.calls[1][0]).toBe(id);
  await screen.findByText("분석할 활성 시그널이 없어요.");
});

it("explains a data boundary and can restart from a selected day", async () => {
  vi.spyOn(SignalClient.prototype, "fastForward").mockResolvedValue({ requestId: "stopped", items: [{
    signalId: "s-1", status: "blocked", reason: "해당 날짜의 관측 데이터가 없어 멈췄습니다.",
    dailyResults: [], alertCount: 0,
  }] });
  const reset = vi.spyOn(SignalClient.prototype, "resetFastForward").mockResolvedValue({
    requestId: "reset", startAt: "2026-09-10T15:00:00Z", signalCount: 1,
  });
  const onCompleted = vi.fn();
  render(<SignalFastForward beforeRun={vi.fn(async () => {})} onCompleted={onCompleted} />);
  fireEvent.click(screen.getByRole("button", { name: "하루 빨리감기" }));
  await screen.findByText(/관측 데이터가 없어 멈췄습니다/);
  expect(screen.queryByText("분석할 활성 시그널이 없어요.")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "시작일 설정" }));
  fireEvent.change(screen.getByLabelText("다음 분석일"), { target: { value: "2026-09-11" } });
  fireEvent.click(screen.getByRole("button", { name: "이 날짜부터 다시 시작" }));
  await waitFor(() => expect(reset).toHaveBeenCalledWith(expect.any(String), "2026-09-11T00:00:00+09:00"));
  await screen.findByText(/1개 시그널.*9월 11일/);
  expect(onCompleted).toHaveBeenCalledTimes(2);
});

it("retries a lost reset response with the same operation and date after remount", async () => {
  const reset = vi.spyOn(SignalClient.prototype, "resetFastForward")
    .mockRejectedValueOnce(new Error("응답 유실"))
    .mockResolvedValue({ requestId: "reset", startAt: "2026-09-11T15:00:00Z", signalCount: 1 });
  const run = vi.spyOn(SignalClient.prototype, "fastForward");
  const props = { beforeRun: vi.fn(async () => {}), onCompleted: vi.fn() };
  const view = render(<SignalFastForward {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "시작일 설정" }));
  fireEvent.change(screen.getByLabelText("다음 분석일"), { target: { value: "2026-09-12" } });
  fireEvent.click(screen.getByRole("button", { name: "이 날짜부터 다시 시작" }));
  await screen.findByRole("alert");
  const args = reset.mock.calls[0];
  view.unmount();
  render(<SignalFastForward {...props} />);
  fireEvent.click(await screen.findByRole("button", { name: "같은 요청 재시도" }));
  await waitFor(() => expect(reset).toHaveBeenCalledTimes(2));
  expect(reset.mock.calls[1]).toEqual(args);
  expect(run).not.toHaveBeenCalled();
});
