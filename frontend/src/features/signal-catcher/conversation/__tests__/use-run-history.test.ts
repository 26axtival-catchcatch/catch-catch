import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { AnyRunStreamEvent } from "../../../customer-intelligence/contracts";
import { useRunHistory } from "../use-run-history";

afterEach(cleanup);
const events: AnyRunStreamEvent[] = [
  { id: 1, type: "run_started", data: { status: "running" } },
  { id: 2, type: "done", data: { status: "completed" } },
];
const empty: AnyRunStreamEvent[] = [];

it("replays saved SSE without creating a run and ignores replay duplicates", async () => {
  const streamRunEvents = vi.fn(async function* () { yield events[0]; yield events[0]; yield events[1]; });
  const client = { streamRunEvents };
  const { result } = renderHook(() => useRunHistory("saved-run", empty, client));
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.events).toEqual(events);
  expect(streamRunEvents).toHaveBeenCalledWith("saved-run", expect.objectContaining({ lastEventId: 0 }));
});

it("uses the complete in-session history without another request", () => {
  const streamRunEvents = vi.fn(async function* () {});
  const { result } = renderHook(() => useRunHistory("saved-run", events, { streamRunEvents }));
  expect(result.current.events).toEqual(events);
  expect(streamRunEvents).not.toHaveBeenCalled();
});

it("shows a retryable error and replaces failed partial history on retry", async () => {
  let attempts = 0;
  const streamRunEvents = vi.fn(async function* () {
    yield events[0];
    if (attempts++ === 0) throw new Error("disconnected");
    yield events[1];
  });
  const client = { streamRunEvents };
  const { result } = renderHook(() => useRunHistory("saved-run", empty, client));
  await waitFor(() => expect(result.current.error).toBe(true));
  act(() => result.current.retry());
  await waitFor(() => expect(result.current.error).toBe(false));
  await waitFor(() => expect(result.current.events).toEqual(events));
});

it("aborts old run replay and does not allow stale messages into the next run", async () => {
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  let signal: AbortSignal | undefined;
  const client = { async *streamRunEvents(runId: string, options?: { signal?: AbortSignal }) {
    if (runId === "old") { signal = options?.signal; await pending; yield events[0]; }
    else yield events[1];
  } };
  const { result, rerender } = renderHook(({ runId }) => useRunHistory(runId, empty, client), { initialProps: { runId: "old" } });
  rerender({ runId: "new" });
  expect(signal?.aborted).toBe(true);
  await act(async () => release());
  await waitFor(() => expect(result.current.events).toEqual([events[1]]));
});
