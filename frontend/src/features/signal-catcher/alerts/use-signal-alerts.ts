"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { DEFAULT_API_BASE_URL } from "../../customer-intelligence/run-client";
import { SignalClient, type AlertEvent } from "../result/signal-client";
import { notifySignalEvents } from "./browser-notifications";

const client = new SignalClient();
const CURSOR_KEY = `catchcatch.signal-alert-cursor.v1:${DEFAULT_API_BASE_URL}`;

function savedCursor(): number | null {
  try {
    const value = localStorage.getItem(CURSOR_KEY);
    if (value === null || !/^\d+$/.test(value)) return null;
    const parsed = Number(value);
    return Number.isSafeInteger(parsed) ? parsed : null;
  } catch { return null; }
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const done = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", done);
      resolve();
    };
    const timer = window.setTimeout(done, ms);
    signal.addEventListener("abort", done, { once: true });
    if (signal.aborted) done();
  });
}

export function useSignalAlerts() {
  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notificationError, setNotificationError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const pollRef = useRef<() => Promise<void>>(async () => { throw new Error("알림 연결 준비 중이에요."); });
  const refresh = useCallback(() => pollRef.current(), []);

  useEffect(() => {
    const controller = new AbortController();
    let cursor = savedCursor();
    let pending: Promise<void> | null = null;

    const pollOnce = (): Promise<void> => {
      if (pending) return pending;
      pending = (async () => {
        do {
          const page = await client.getAlertEvents(cursor, controller.signal);
          if (controller.signal.aborted) return;
          if (page.items.length) {
            setEvents((current) => {
              const seen = new Set(current.map((item) => item.eventId));
              return [...page.items.filter((item) => !seen.has(item.eventId)), ...current].slice(0, 20);
            });
          }
          cursor = page.nextCursor;
          try { localStorage.setItem(CURSOR_KEY, String(Math.max(savedCursor() ?? 0, cursor))); } catch { /* retain this tab's cursor */ }
          setError(null);
          setReady(true);
          if (page.items.length) {
            try { await notifySignalEvents(page.items); setNotificationError(null); }
            catch (reason) {
              if (!controller.signal.aborted) setNotificationError(reason instanceof Error ? reason.message : "브라우저 알림을 표시하지 못했어요.");
            }
          }
          if (!page.hasMore) break;
        } while (!controller.signal.aborted);
      })().catch((reason) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "알림 연결이 끊겼습니다.");
        throw reason;
      }).finally(() => { pending = null; });
      return pending;
    };
    pollRef.current = pollOnce;

    async function poll() {
      let failures = 0;
      while (!controller.signal.aborted) {
        let delay = document.visibilityState === "hidden" ? 15_000 : 5_000;
        try {
          await pollOnce();
          failures = 0;
        } catch (reason) {
          if (controller.signal.aborted) return;
          failures += 1;
          delay = Math.min(30_000, 5_000 * 2 ** Math.min(failures, 3));
          setError(reason instanceof Error ? reason.message : "알림 연결이 끊겼습니다.");
        }
        await wait(delay, controller.signal);
      }
    }

    const visible = () => {
      if (document.visibilityState === "visible") void pollOnce().catch(() => undefined);
    };
    document.addEventListener("visibilitychange", visible);
    void poll();
    return () => {
      controller.abort();
      document.removeEventListener("visibilitychange", visible);
    };
  }, []);

  return {
    events,
    error,
    notificationError,
    ready,
    refresh,
    clear: () => setEvents([]),
  };
}
