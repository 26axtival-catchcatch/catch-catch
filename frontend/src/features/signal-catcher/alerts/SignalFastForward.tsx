"use client";

import { useEffect, useRef, useState } from "react";
import { DEFAULT_API_BASE_URL } from "../../customer-intelligence/run-client";
import { SignalClient, SignalClientError, type FastForwardResult } from "../result/signal-client";
import { LIVE_END_AT } from "../state/live-adapter";
import styles from "./signal-alerts.module.css";

const client = new SignalClient();
const REQUEST_KEY = `catchcatch.fast-forward-request.v1:${DEFAULT_API_BASE_URL}`;
type Pending = { id: string; kind: "advance" } | { id: string; kind: "reset"; startAt: string };
const dateLabel = (value: string) => new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul", month: "long", day: "numeric",
}).format(new Date(value));

function summary(result: FastForwardResult): string {
  const days = result.items.flatMap((item) => item.dailyResults);
  const reasons = [...new Set(result.items.map((item) => item.reason).filter(Boolean))];
  if (!days.length) return reasons.join(" ") || "분석할 활성 시그널이 없어요.";
  const success = days.filter((day) => day.status === "success").length;
  const failed = days.length - success;
  const dates = [...new Set(days.map((day) => dateLabel(day.startAt)))];
  const count = result.items.reduce((sum, item) => sum + item.alertCount, 0);
  return `${dates.join(", ")} 분석: ${success}건 완료${failed ? `, ${failed}건 측정 불가` : ""}. ${reasons.join(" ")} ${count ? `새 알림 ${count}건을 알림함에서 확인할 수 있어요.` : "새로 충족한 알림 기준은 없어요."}`;
}

function savedRequest(): Pending | null {
  const raw = sessionStorage.getItem(REQUEST_KEY);
  if (!raw) return null;
  // Retain retries created before reset support was introduced.
  if (/^[\da-f-]{36}$/i.test(raw)) return { id: raw, kind: "advance" };
  const value = JSON.parse(raw);
  if (typeof value.id === "string" && (value.kind === "advance"
    || (value.kind === "reset" && typeof value.startAt === "string"))) return value;
  return null;
}

export function SignalFastForward({ beforeRun, onCompleted, disabled = false }: {
  beforeRun: () => Promise<void>;
  onCompleted: () => void;
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [retry, setRetry] = useState(false);
  const [settings, setSettings] = useState(false);
  const [startDate, setStartDate] = useState(LIVE_END_AT.slice(0, 10));
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef<Pending | null>(null);
  const running = useRef(false);
  useEffect(() => {
    try {
      pending.current = savedRequest();
      setRetry(Boolean(pending.current));
    } catch { /* in-memory retries still use the same request */ }
    setReady(true);
  }, []);

  function clearPending() {
    pending.current = null;
    try { sessionStorage.removeItem(REQUEST_KEY); } catch { /* memory fallback */ }
    setRetry(false);
  }

  async function run(kind: "advance" | "reset" = "advance") {
    if (running.current) return;
    running.current = true;
    setBusy(true); setNotice(null); setError(null);
    try {
      await beforeRun();
      pending.current ??= kind === "reset"
        ? { id: crypto.randomUUID(), kind, startAt: `${startDate}T00:00:00+09:00` }
        : { id: crypto.randomUUID(), kind };
      const operation = pending.current;
      try { sessionStorage.setItem(REQUEST_KEY, JSON.stringify(operation)); } catch { /* memory fallback */ }
      if (operation.kind === "reset") {
        const result = await client.resetFastForward(operation.id, operation.startAt);
        setNotice(result.signalCount
          ? `${result.signalCount}개 시그널을 ${dateLabel(result.startAt)}부터 분석할 준비가 됐어요. 하루 빨리감기를 눌러 주세요.`
          : "분석할 활성 시그널이 없어요.");
        setSettings(false);
      } else {
        setNotice(summary(await client.fastForward(operation.id)));
      }
      clearPending();
      onCompleted();
    } catch (reason) {
      // A rejected date/selection did not run. Let the user correct it; ambiguous
      // network failures and busy locks must retry the original operation instead.
      if (reason instanceof SignalClientError && [400, 404, 422].includes(reason.status ?? 0)) clearPending();
      setRetry(Boolean(pending.current));
      setError(reason instanceof Error ? reason.message : "요청을 완료하지 못했어요.");
    } finally {
      running.current = false; setBusy(false);
    }
  }
  const locked = busy || disabled || !ready;
  return (
    <div className={styles.wrap}>
      <div className={styles.forwardActions}>
        <button type="button" className={styles.trigger} onClick={() => void run()} disabled={locked}
          title="등록한 활성 시그널을 다음 날짜의 데이터로 분석합니다">
          <span aria-hidden="true">»</span>{busy ? "처리 중…" : retry ? "같은 요청 재시도" : "하루 빨리감기"}
        </button>
        <button type="button" className={styles.trigger} disabled={locked || retry}
          aria-expanded={settings} onClick={() => setSettings((value) => !value)}>시작일 설정</button>
      </div>
      {settings || notice || error ? <div className={styles.resultPanel}>
        <button type="button" className={styles.dismiss} aria-label="빨리감기 결과 닫기"
          onClick={() => { setNotice(null); setError(null); setSettings(false); }}>×</button>
        {settings ? <form className={styles.resetForm} onSubmit={(event) => { event.preventDefault(); void run("reset"); }}>
          <label htmlFor="fast-forward-date">다음 분석일</label>
          <input id="fast-forward-date" type="date" required value={startDate} disabled={locked || retry}
            onChange={(event) => setStartDate(event.target.value)} />
          <p>기존 측정 이력은 별도 보관하고, 선택한 날짜의 전날을 비교 기준으로 준비해요. 시그널과 알림 조건은 유지돼요.</p>
          <button type="submit" className={styles.trigger} disabled={locked || retry || !startDate}>이 날짜부터 다시 시작</button>
        </form> : null}
        {error ? <p role="alert">{error} {retry ? "같은 요청으로 재시도하면 작업이 중복 실행되지 않아요." : ""}</p>
          : notice ? <p role="status">{notice}</p> : null}
      </div> : null}
    </div>
  );
}
