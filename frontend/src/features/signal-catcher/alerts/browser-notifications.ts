import { DEFAULT_API_BASE_URL } from "../../customer-intelligence/run-client";
import type { AlertEvent } from "../result/signal-client";

export type NativeNotificationStatus = NotificationPermission | "unsupported";
export const PERMISSION_CHANGED = "catchcatch:notification-permission";
const DELIVERY_KEY = `catchcatch.native-alert-sequence.v1:${DEFAULT_API_BASE_URL}`;
let memorySequence = 0;

export function nativeNotificationStatus(): NativeNotificationStatus {
  if (typeof window === "undefined" || !window.isSecureContext || typeof Notification === "undefined"
    || !("serviceWorker" in navigator)) return "unsupported";
  return Notification.permission;
}

export async function notificationWorker(): Promise<ServiceWorkerRegistration> {
  let timer: ReturnType<typeof setTimeout>;
  try {
    return await Promise.race([
      (async () => {
        await navigator.serviceWorker.register("/signal-notifications-sw.js");
        return navigator.serviceWorker.ready;
      })(),
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error("브라우저 알림 준비가 지연되고 있어요.")), 8_000);
      }),
    ]);
  } finally {
    clearTimeout(timer!);
  }
}

export async function requestNativeNotifications(): Promise<NativeNotificationStatus> {
  const current = nativeNotificationStatus();
  // Call requestPermission before any asynchronous work to retain the user gesture.
  const permission = current === "default" ? await Notification.requestPermission() : current;
  window.dispatchEvent(new Event(PERMISSION_CHANGED));
  if (permission === "granted") await notificationWorker();
  return permission;
}

function unitLabel(unit: string): string {
  return ({ customers: "명", percentage_points: "%p", percent: "%", records: "건", events: "회" })[unit] ?? unit;
}

function lastSequence(): number {
  try {
    const raw = localStorage.getItem(DELIVERY_KEY);
    const value = raw === null ? 0 : Number(raw);
    return Number.isSafeInteger(value) && value >= 0 ? value : 0;
  } catch {
    return memorySequence;
  }
}

export async function notifySignalEvents(events: AlertEvent[]): Promise<void> {
  if (!events.length || nativeNotificationStatus() !== "granted") return;
  const deliver = async () => {
    const pending = events.filter((event) => event.sequence > lastSequence()).sort((a, b) => a.sequence - b.sequence);
    if (!pending.length) return;
    const registration = await notificationWorker();
    let failed = false;
    for (const event of pending) {
      // Consume before calling the browser: a native API failure must never cause
      // a replay loop, and all tabs share this sequence under the same Web Lock.
      memorySequence = Math.max(memorySequence, event.sequence);
      try { localStorage.setItem(DELIVERY_KEY, String(event.sequence)); } catch { /* in-memory fallback */ }
      try {
        await registration.showNotification(`캐치캐치 · ${event.signalTitle}`, {
          body: `${event.rule.metricLabel} ${event.observedValue.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}${unitLabel(event.rule.comparisonUnit)}`,
          tag: `catchcatch:${DEFAULT_API_BASE_URL}:${event.eventId}`,
          data: { signalId: event.signalId },
        });
      } catch {
        failed = true;
      }
    }
    if (failed) throw new Error("브라우저 알림을 표시하지 못했어요. 알림함과 브라우저 설정을 확인해 주세요.");
  };
  if (navigator.locks) await navigator.locks.request(DELIVERY_KEY, deliver);
  else await deliver();
}
