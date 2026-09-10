"use client";

import { useEffect, useState } from "react";
import { nativeNotificationStatus, PERMISSION_CHANGED, requestNativeNotifications, type NativeNotificationStatus } from "./browser-notifications";
import styles from "./signal-alerts.module.css";

export function BrowserNotificationSettings() {
  const [permission, setPermission] = useState<NativeNotificationStatus | "checking">("checking");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const update = () => setPermission(nativeNotificationStatus());
    update();
    window.addEventListener("focus", update);
    window.addEventListener(PERMISSION_CHANGED, update);
    return () => {
      window.removeEventListener("focus", update);
      window.removeEventListener(PERMISSION_CHANGED, update);
    };
  }, []);
  async function enable() {
    setBusy(true);
    setError(null);
    try { setPermission(await requestNativeNotifications()); }
    catch { setError("알림을 켜지 못했어요. 브라우저 설정을 확인한 뒤 다시 시도해 주세요."); }
    finally { setBusy(false); }
  }
  return (
    <div className={styles.permissionSettings}>
      {permission === "default" || (permission === "granted" && error) ? (
        <button type="button" className={styles.permission} disabled={busy} onClick={enable}>
          {busy ? "알림 권한 확인 중…" : "브라우저 알림 켜기"}
        </button>
      ) : <p role="status">{permission === "granted" ? "브라우저 알림이 켜져 있어요."
        : permission === "denied" ? "브라우저 알림이 차단되어 있어요. 주소창의 사이트 설정에서 알림을 허용해 주세요."
          : permission === "unsupported" ? "이 환경에서는 브라우저 알림을 사용할 수 없어요. 알림함에서 확인할 수 있어요."
            : "알림 권한 확인 중…"}</p>}
      <small>앱이 열려 있는 동안 새 변화를 알려드려요.</small>
      {error ? <p role="alert">{error}</p> : null}
    </div>
  );
}
