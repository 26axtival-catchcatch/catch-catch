"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { AnyRunStreamEvent } from "../../customer-intelligence/contracts";
import { RunClient } from "../../customer-intelligence/run-client";

export const EMPTY_HISTORY: AnyRunStreamEvent[] = [];
interface HistoryClient {
  streamRunEvents(runId: string, options?: { signal?: AbortSignal; lastEventId?: number }): AsyncIterable<AnyRunStreamEvent>;
}

/** Read-only replay. Does not create a Run or dispatch terminal events into the live controller. */
export function useRunHistory(runId: string, initialEvents = EMPTY_HISTORY, providedClient?: HistoryClient) {
  const defaultClient = useMemo(() => new RunClient(), []);
  const client = providedClient ?? defaultClient;
  const [attempt, setAttempt] = useState(0);
  const [history, setHistory] = useState<{ runId: string; events: AnyRunStreamEvent[]; loading: boolean; error: boolean }>(
    { runId, events: EMPTY_HISTORY, loading: true, error: false },
  );
  const hasCompleteHistory = initialEvents.some(event => event.type === "done");
  useEffect(() => {
    if (hasCompleteHistory) return;
    const controller = new AbortController();
    setHistory({ runId, events: EMPTY_HISTORY, loading: true, error: false });
    void (async () => {
      const events = new Map<number, AnyRunStreamEvent>();
      try {
        for await (const event of client.streamRunEvents(runId, { signal: controller.signal, lastEventId: 0 })) {
          if (controller.signal.aborted) return;
          events.set(event.id, event);
        }
        if (!controller.signal.aborted) setHistory({ runId, events: [...events.values()], loading: false, error: false });
      } catch {
        if (!controller.signal.aborted) setHistory({ runId, events: [...events.values()], loading: false, error: true });
      }
    })();
    return () => controller.abort();
  }, [runId, hasCompleteHistory, client, attempt]);
  const retry = useCallback(() => setAttempt(value => value + 1), []);
  if (hasCompleteHistory) return { events: initialEvents, loading: false, error: false, retry };
  if (history.runId !== runId) return { events: EMPTY_HISTORY, loading: true, error: false, retry };
  return { events: history.events, loading: history.loading, error: history.error, retry };
}
