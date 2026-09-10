"use client";

import { useEffect, useState } from "react";

import { DEFAULT_API_BASE_URL } from "../../customer-intelligence/run-client";
import { SignalClient, type AlertEvent } from "../result/signal-client";

const client = new SignalClient();
const CURSOR_KEY = `catchcatch.signal-alert-cursor.v1:${DEFAULT_API_BASE_URL}`;

function savedCursor(): number | null {
  const value = localStorage.getItem(CURSOR_KEY);
  if (value === null || !/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : null;
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

function showBrowserNotifications(events: AlertEvent[]) {
  if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
  for (const event of events) {
    new Notification(`캐치캐치 · ${event.signalTitle}`, {
      body: `${event.rule.metricLabel} ${event.observedValue.toLocaleString("ko-KR")}${event.rule.comparisonUnit}`,
      tag: event.eventId,
    });
  }
}

export function useSignalAlerts() {
  const [events, setEvents] = useState<AlertEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    async function poll() {
      let cursor = savedCursor();
      let failures = 0;
      while (!controller.signal.aborted) {
        let delay = document.visibilityState === "hidden" ? 15_000 : 5_000;
        try {
          const page = await client.getAlertEvents(cursor, controller.signal);
          if (controller.signal.aborted) return;
          if (page.items.length) {
            setEvents((current) => {
              const seen = new Set(current.map((item) => item.eventId));
              return [...page.items.filter((item) => !seen.has(item.eventId)), ...current].slice(0, 20);
            });
            showBrowserNotifications(page.items);
          }
          localStorage.setItem(CURSOR_KEY, String(page.nextCursor));
          cursor = page.nextCursor;
          failures = 0;
          setError(null);
          if (page.hasMore) continue;
        } catch (reason) {
          if (controller.signal.aborted) return;
          failures += 1;
          delay = Math.min(30_000, 5_000 * 2 ** Math.min(failures, 3));
          setError(reason instanceof Error ? reason.message : "알림 연결이 끊겼습니다.");
        }
        await wait(delay, controller.signal);
      }
    }

    void poll();
    return () => controller.abort();
  }, []);

  return {
    events,
    error,
    clear: () => setEvents([]),
  };
}
