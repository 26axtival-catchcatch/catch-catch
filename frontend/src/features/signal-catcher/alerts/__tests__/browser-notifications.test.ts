import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AlertEvent } from "../../result/signal-client";
import { nativeNotificationStatus, requestNativeNotifications, notifySignalEvents } from "../browser-notifications";

export const alert: AlertEvent = {
  sequence: 1, eventId: "event-1", signalId: "signal-1", signalTitle: "반복 검색",
  observedValue: 28, metricValue: 28, baselineValue: null, occurredAt: "2026-09-11T00:00:00Z",
  rule: { recommendationId: "rec", ruleId: "rule", metricKey: "affected_customer_count",
    metricLabel: "대상 고객 수", metricUnit: "customers", kind: "value", operator: "gte",
    threshold: 20, comparisonUnit: "customers", windowSeconds: 86400, rationale: "관찰" },
};

describe("native signal notifications", () => {
  const showNotification = vi.fn();
  beforeEach(() => {
    localStorage.clear();
    showNotification.mockReset().mockResolvedValue(undefined);
    vi.stubGlobal("isSecureContext", true);
    vi.stubGlobal("Notification", { permission: "granted", requestPermission: vi.fn().mockResolvedValue("granted") });
    vi.stubGlobal("navigator", {
      serviceWorker: { register: vi.fn().mockResolvedValue({}), ready: Promise.resolve({ showNotification }) },
      locks: { request: vi.fn(async (_key, action) => action()) },
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("uses the real service worker contract and deduplicates replay", async () => {
    await notifySignalEvents([alert]);
    await notifySignalEvents([alert]);
    expect(showNotification).toHaveBeenCalledTimes(1);
    expect(showNotification).toHaveBeenCalledWith("캐치캐치 · 반복 검색", expect.objectContaining({
      body: "대상 고객 수 28명", data: { signalId: "signal-1" },
    }));
  });

  it("does not re-request denied permission or display old events", async () => {
    Object.defineProperty(Notification, "permission", { value: "denied", configurable: true });
    expect(nativeNotificationStatus()).toBe("denied");
    await requestNativeNotifications();
    await notifySignalEvents([alert]);
    expect(Notification.requestPermission).not.toHaveBeenCalled();
    expect(showNotification).not.toHaveBeenCalled();
  });

  it("reports native delivery errors without retrying the same alert", async () => {
    showNotification.mockRejectedValueOnce(new Error("native failure"));
    await expect(notifySignalEvents([alert])).rejects.toThrow();
    await notifySignalEvents([alert]);
    expect(showNotification).toHaveBeenCalledTimes(1);
  });

  it("requests permission directly from the user action", async () => {
    Object.defineProperty(Notification, "permission", { value: "default", configurable: true });
    const pending = requestNativeNotifications();
    expect(Notification.requestPermission).toHaveBeenCalledOnce();
    await pending;
  });

  it("reports insecure origins as unsupported", () => {
    vi.stubGlobal("isSecureContext", false);
    expect(nativeNotificationStatus()).toBe("unsupported");
  });
});
