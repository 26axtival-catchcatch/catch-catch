import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SignalClient } from "../../result/signal-client";
import { useSignalAlerts } from "../use-signal-alerts";
import { notifySignalEvents } from "../browser-notifications";

vi.mock("../browser-notifications", () => ({ notifySignalEvents: vi.fn().mockResolvedValue(undefined) }));
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
beforeEach(() => localStorage.clear());

it("commits polling progress even when the native notification API rejects", async () => {
  const event = { eventId: "one", sequence: 1, signalId: "s", signalTitle: "title" };
  const read = vi.spyOn(SignalClient.prototype, "getAlertEvents")
    .mockResolvedValueOnce({ items: [], nextCursor: 0, latestCursor: 0, hasMore: false })
    .mockResolvedValueOnce({ items: [event as never], nextCursor: 1, latestCursor: 1, hasMore: false })
    .mockResolvedValue({ items: [], nextCursor: 1, latestCursor: 1, hasMore: false });
  vi.mocked(notifySignalEvents).mockRejectedValueOnce(new Error("native failure"));
  const { result } = renderHook(() => useSignalAlerts());
  await waitFor(() => expect(result.current.ready).toBe(true));
  await act(() => result.current.refresh());
  expect(result.current.events).toHaveLength(1);
  expect(result.current.error).toBeNull();
  expect(result.current.notificationError).toBe("native failure");
  await act(() => result.current.refresh());
  expect(read).toHaveBeenLastCalledWith(1, expect.any(AbortSignal));
});

it("serializes a user refresh with bootstrap and drains pagination", async () => {
  let release!: (page: { items: never[]; nextCursor: number; latestCursor: number; hasMore: boolean }) => void;
  const read = vi.spyOn(SignalClient.prototype, "getAlertEvents")
    .mockReturnValueOnce(new Promise((resolve) => { release = resolve; }))
    .mockResolvedValue({ items: [], nextCursor: 2, latestCursor: 2, hasMore: false });
  const { result } = renderHook(() => useSignalAlerts());
  let refresh!: Promise<void>;
  await act(async () => { refresh = result.current.refresh(); });
  expect(read).toHaveBeenCalledTimes(1);
  await act(async () => {
    release({ items: [], nextCursor: 1, latestCursor: 2, hasMore: true });
    await refresh;
  });
  expect(result.current.ready).toBe(true);
  expect(read).toHaveBeenLastCalledWith(1, expect.any(AbortSignal));
});
