"use client";

import { useEffect, useRef, useState } from "react";
import { DEFAULT_API_BASE_URL } from "../../customer-intelligence/run-client";
import { SignalClient, type FastForwardResult } from "../result/signal-client";
import styles from "./signal-alerts.module.css";

const client = new SignalClient();
const REQUEST_KEY = `catchcatch.fast-forward-request.v1:${DEFAULT_API_BASE_URL}`;

function summary(result: FastForwardResult): string {
  const days = result.items.flatMap((item) => item.dailyResults);
  if (!days.length) return "분석할 활성 시그널이 없어요.";
  const success = days.filter((day) => day.status === "success").length;
  const failed = days.length - success;
  const dates = [...new Set(days.map((day) => new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul", month: "long", day: "numeric",
  }).format(new Date(day.startAt))))];
  const count = result.items.reduce((sum, item) => sum + item.alertCount, 0);
  return `${dates.join(", ")} 분석: ${success}건 완료${failed ? `, ${failed}건 측정 불가. 해당 날짜의 데이터를 확인해 주세요` : ""}. ${count ? `새 알림 ${count}건을 알림함에서 확인할 수 있어요.` : "새로 충족한 알림 기준은 없어요."}`;
}

export function SignalFastForward({ beforeRun, onCompleted, disabled = false }: {
  beforeRun: () => Promise<void>;
  onCompleted: () => void;
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pendingId = useRef<string | null>(null);
  const running = useRef(false);
  useEffect(() => {
    try {
      pendingId.current = sessionStorage.getItem(REQUEST_KEY);
      setRetry(Boolean(pendingId.current));
    } catch { /* in-memory retries still use the same ID */ }
  }, []);

  async function advance() {
    if (running.current) return;
    running.current = true;
    setBusy(true); setNotice(null); setError(null);
    try {
      await beforeRun(); // bootstrap must finish before producing a new event
      pendingId.current ??= crypto.randomUUID();
      try { sessionStorage.setItem(REQUEST_KEY, pendingId.current); } catch { /* memory fallback */ }
      const result = await client.fastForward(pendingId.current);
      pendingId.current = null;
      try { sessionStorage.removeItem(REQUEST_KEY); } catch { /* memory fallback */ }
      setRetry(false);
      setNotice(summary(result));
      onCompleted();
    } catch (reason) {
      setRetry(Boolean(pendingId.current));
      setError(reason instanceof Error ? reason.message : "빨리감기를 완료하지 못했어요.");
    } finally {
      running.current = false; setBusy(false);
    }
  }
  return (
    <div className={styles.wrap}>
      <button type="button" className={styles.trigger} onClick={advance} disabled={busy || disabled}
        title="등록한 활성 시그널을 다음 날짜의 데이터로 분석합니다">
        <span aria-hidden="true">»</span>{busy ? "다음 하루 분석 중…" : retry ? "같은 요청 재시도" : "하루 빨리감기"}
      </button>
      {notice || error ? <div className={styles.resultPanel}>
        <button type="button" className={styles.dismiss} aria-label="빨리감기 결과 닫기" onClick={() => { setNotice(null); setError(null); }}>×</button>
        {error ? <p role="alert">{error} {retry ? "같은 요청으로 다시 시도하면 날짜가 중복으로 넘어가지 않아요." : "알림 연결 후 다시 시도해 주세요."}</p>
          : <p role="status">{notice}</p>}
      </div> : null}
    </div>
  );
}
