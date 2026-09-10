"use client";

import { useState } from "react";

import { HeartMark } from "../brand/Brand";
import type { AlertEvent } from "../result/signal-client";
import { BrowserNotificationSettings } from "./BrowserNotificationSettings";

import styles from "./signal-alerts.module.css";

interface SignalAlertInboxProps {
  events: AlertEvent[];
  error: string | null;
  notificationError?: string | null;
  onOpenSignal: (signalId: string) => void;
  onClear: () => void;
}

function unitOf(unit: string): string {
  if (unit === "customers") return "명";
  if (unit === "percentage_points") return "%p";
  if (unit === "percent") return "%";
  return unit;
}

export function SignalAlertInbox({ events, error, notificationError, onOpenSignal, onClear }: SignalAlertInboxProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className={styles.wrap}>
      <button
        type="button"
        className={styles.trigger}
        data-active={events.length > 0 || undefined}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <HeartMark size={14} />
        알림
        {events.length ? <b>{events.length}</b> : null}
      </button>
      {open ? (
        <section className={styles.panel} aria-label="변화 알림">
          <header>
            <div><strong>캐치한 변화</strong><span>새 측정에서 알림 기준을 넘었어요</span></div>
            {events.length ? <button type="button" onClick={onClear}>모두 확인</button> : null}
          </header>
          {events.length ? (
            <ul>
              {events.map((event) => (
                <li key={event.eventId}>
                  <button type="button" onClick={() => { setOpen(false); onOpenSignal(event.signalId); }}>
                    <HeartMark size={13} />
                    <span>
                      <strong>{event.signalTitle}</strong>
                      <small>{event.rule.metricLabel} · {event.observedValue.toLocaleString("ko-KR")}{unitOf(event.rule.comparisonUnit)}</small>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p>{error ? "알림 연결을 다시 시도하고 있어요." : "새로 캐치한 변화가 없어요."}</p>
          )}
          {notificationError ? <p role="alert">{notificationError}</p> : null}
          <BrowserNotificationSettings />
        </section>
      ) : null}
    </div>
  );
}
