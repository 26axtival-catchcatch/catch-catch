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
