"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { HeartMark } from "../brand/Brand";
import { Overlay } from "../Overlay";
import {
  SignalClient,
  SignalClientError,
  type DailyResults,
  type DailySchedule,
  type MeasurementComparison,
  type MeasurementHistory,
  type RegistrySignal,
  type SignalMeasurement,
} from "../result/signal-client";

import styles from "./signal-detail.module.css";

const client = new SignalClient();

function kstDate(value: string | Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(typeof value === "string" ? new Date(value) : value);
}

function shiftedDate(value: string, days: number): string {
  const next = new Date(`${value}T00:00:00Z`);
  next.setUTCDate(next.getUTCDate() + days);
  return next.toISOString().slice(0, 10);
}

function initialWindow() {
  const end = kstDate(new Date());
  return { start: shiftedDate(end, -1), end };
}

function instant(date: string): string {
  return `${date}T00:00:00+09:00`;
}

function displayUnit(unit: string): string {
  if (unit === "customers") return "명";
  if (unit === "percentage_points") return "%p";
  if (unit === "percent") return "%";
  if (unit === "records") return "건";
  if (unit === "events") return "회";
  return unit;
}

function valueLabel(value: number | null, unit: string): string {
  return value === null ? "측정 불가" : `${value.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}${displayUnit(unit)}`;
}

function periodLabel(startAt: string, endAt: string): string {
  return `${kstDate(startAt)} – ${kstDate(new Date(new Date(endAt).getTime() - 1))}`;
}

function measurementNote(measurement: SignalMeasurement): string {
  if (measurement.status === "unavailable") return measurement.reason ?? "이 기간은 측정할 수 없었어요.";
  const values = measurement.values.filter((item) => item.value !== null && item.key !== "val_count");
  return values.map((item) => `${item.label} ${valueLabel(item.value, item.unit)}`).join(" · ");
}

interface SignalDetailModalProps {
  signalId: string;
  sourceLabels: Record<string, string>;
  onClose: () => void;
  onChanged: () => void;
}

export function SignalDetailModal({ signalId, sourceLabels, onClose, onChanged }: SignalDetailModalProps) {
  const initial = useMemo(initialWindow, []);
  const [detail, setDetail] = useState<RegistrySignal | null>(null);
  const [schedule, setSchedule] = useState<DailySchedule | null>(null);
  const [daily, setDaily] = useState<DailyResults | null>(null);
  const [comparison, setComparison] = useState<MeasurementComparison | null>(null);
  const [history, setHistory] = useState<MeasurementHistory | null>(null);
  const [baselineId, setBaselineId] = useState("");
  const [targetId, setTargetId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [startDate, setStartDate] = useState(initial.start);
  const [endDate, setEndDate] = useState(initial.end);
  const [backfillDate, setBackfillDate] = useState(initial.start);
  const closeRef = useRef<HTMLButtonElement>(null);
  const busyRef = useRef<string | null>(null);
  const customComparisonRef = useRef(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    const [nextDetail, nextSchedule, nextDaily, nextComparison, nextHistory] = await Promise.all([
      client.getSignal(signalId, signal),
      client.getSchedule(signalId, signal),
      client.getDailyResults(signalId, undefined, signal),
      client.getComparison(signalId, signal),
      client.getMeasurementHistory(signalId, signal),
    ]);
    setDetail(nextDetail);
    setSchedule(nextSchedule);
    setDaily((current) => current && current.items.length > nextDaily.items.length
      ? {
          ...nextDaily,
          items: [...nextDaily.items, ...current.items.filter((old) => !nextDaily.items.some((item) => item.executionId === old.executionId))],
        }
      : nextDaily);
    if (!customComparisonRef.current) setComparison(nextComparison);
    setHistory(nextHistory);
    if (nextHistory.latestByWindow.length >= 2) {
      const latest = nextHistory.latestByWindow;
      setBaselineId((current) => current || latest[latest.length - 2].measurementId);
      setTargetId((current) => current || latest[latest.length - 1].measurementId);
    }
  }, [signalId]);

  useEffect(() => {
    const controller = new AbortController();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    setLoading(true);
    load(controller.signal)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : "변화 상세를 불러오지 못했습니다.");
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible" && !busyRef.current) void load(controller.signal).catch(() => undefined);
    }, 5_000);
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape" && !busy) onClose(); };
    document.addEventListener("keydown", onKey);
    return () => {
      controller.abort();
      window.clearInterval(timer);
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKey);
    };
  }, [load, onClose]);

  useEffect(() => {
    busyRef.current = busy;
  }, [busy]);

  async function runAction(key: string, action: () => Promise<void>, refresh = true) {
    setBusy(key);
    setError(null);
    setNotice(null);
    try {
      await action();
      if (refresh) {
        await load();
        onChanged();
      }
    } catch (reason) {
      if (reason instanceof SignalClientError && reason.status === 409) {
        await load().catch(() => undefined);
      }
      setError(reason instanceof Error ? reason.message : "요청을 완료하지 못했습니다.");
    } finally {
      setBusy(null);
    }
  }

  async function loadMore() {
    if (!daily?.nextBefore) return;
    await runAction("more", async () => {
      const next = await client.getDailyResults(signalId, daily.nextBefore ?? undefined);
      setDaily({
        ...next,
        items: [...daily.items, ...next.items.filter((item) => !daily.items.some((old) => old.executionId === item.executionId))],
      });
    });
  }

  const sources = detail?.sourceIds.map((id) => sourceLabels[id] ?? id).join(" · ") ?? "";

  return (
    <Overlay>
      <div className={styles.scrim}>
        <section className={styles.modal} role="dialog" aria-modal="true" aria-labelledby="signal-detail-title">
          <header className={styles.head}>
            <div>
              <p><HeartMark size={13} /> CATCH DETAIL</p>
              <h2 id="signal-detail-title">{detail?.title ?? "변화 상세"}</h2>
              {detail ? <span>{detail.populationDescription} · {sources}</span> : null}
            </div>
            <button ref={closeRef} type="button" onClick={onClose} disabled={Boolean(busy)} aria-label="닫기">✕</button>
          </header>

          {loading ? <div className={styles.state}>측정 상태를 불러오고 있어요.</div> : null}
          {!loading && error && !detail ? <div className={styles.state} data-error="true">{error}<button type="button" onClick={() => void load()}>다시 불러오기</button></div> : null}

          {detail && schedule ? (
            <div className={styles.body}>
              <section className={styles.summary}>
                <div><span>추적 상태</span><strong>{detail.status === "active" ? "캐치 중" : detail.status === "paused" ? "일시 중지" : "보관됨"}</strong></div>
                <div><span>매일 자동 분석</span><strong>{schedule.enabled ? "켜짐" : "꺼짐"}</strong></div>
                <div><span>다음 실행</span><strong>{new Date(schedule.nextRunAt).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}</strong></div>
                <div className={styles.summaryActions}>
                  <button type="button" disabled={Boolean(busy)} onClick={() => void runAction("status", async () => {
                    await client.updateSignalStatus(signalId, detail.status === "active" ? "paused" : "active");
                  })}>{detail.status === "active" ? "추적 잠시 멈추기" : "추적 다시 시작"}</button>
                  <button type="button" disabled={Boolean(busy)} onClick={() => void runAction("schedule", async () => {
                    await client.updateSchedule(signalId, !schedule.enabled);
                  })}>자동 분석 {schedule.enabled ? "끄기" : "켜기"}</button>
                </div>
              </section>

              <section className={styles.block}>
                <div className={styles.blockHead}><div><span>MANUAL CHECK</span><h3>지금 분석</h3></div><small>선택한 기간을 저장된 정의로 다시 측정해요.</small></div>
                <div className={styles.formRow}>
                  <label>시작일<input type="date" value={startDate} max={endDate} onChange={(event) => setStartDate(event.target.value)} /></label>
                  <label>종료일<input type="date" value={endDate} min={startDate} onChange={(event) => setEndDate(event.target.value)} /></label>
                  <button type="button" disabled={Boolean(busy) || !startDate || !endDate || startDate >= endDate} onClick={() => void runAction("measure", async () => {
                    const result = await client.measure(signalId, instant(startDate), instant(endDate));
                    setNotice(result.status === "success" ? `측정 완료 · ${measurementNote(result)}` : result.reason ?? "측정할 수 없었어요.");
                  })}>{busy === "measure" ? "측정 중…" : "이 기간 분석"}</button>
                </div>
              </section>

              <section className={styles.block}>
                <div className={styles.blockHead}><div><span>DAILY SCHEDULE</span><h3>과거 일별 결과 보충</h3></div><small>선택 날짜부터 닫힌 하루를 순서대로 채워요.</small></div>
                <div className={styles.formRow}>
                  <label>첫 측정일<input type="date" value={backfillDate} max={initial.start} onChange={(event) => setBackfillDate(event.target.value)} /></label>
                  <button type="button" disabled={Boolean(busy) || !backfillDate} onClick={() => void runAction("backfill", async () => {
                    await client.updateSchedule(signalId, true, instant(shiftedDate(backfillDate, 1)));
                    setNotice(`${backfillDate}부터 일별 결과를 보충하도록 등록했어요.`);
                  })}>{busy === "backfill" ? "등록 중…" : "보충 시작"}</button>
                  <span className={styles.pending}>남은 기간 {daily?.pendingDays ?? 0}일</span>
                </div>
              </section>

              <section className={styles.block}>
                <div className={styles.blockHead}><div><span>COMPARISON</span><h3>최근 일별 변화</h3></div></div>
                {history && history.latestByWindow.length >= 2 ? (
                  <div className={styles.comparePicker}>
                    <label>기준 기간<select value={baselineId} onChange={(event) => setBaselineId(event.target.value)}>{history.latestByWindow.map((item) => <option key={item.measurementId} value={item.measurementId}>{periodLabel(item.startAt, item.endAt)}</option>)}</select></label>
                    <label>비교 기간<select value={targetId} onChange={(event) => setTargetId(event.target.value)}>{history.latestByWindow.map((item) => <option key={item.measurementId} value={item.measurementId}>{periodLabel(item.startAt, item.endAt)}</option>)}</select></label>
                    <button type="button" disabled={Boolean(busy) || !baselineId || !targetId || baselineId === targetId} onClick={() => void runAction("compare", async () => {
                      customComparisonRef.current = true;
                      setComparison(await client.getComparison(signalId, undefined, { baselineId, targetId }));
                    }, false)}>선택 기간 비교</button>
                  </div>
                ) : null}
                {comparison?.comparable ? (
                  <ul className={styles.changes}>
                    {comparison.metrics.filter((item) => item.key !== "val_count").map((item) => (
                      <li key={item.key}><span>{item.label}</span><strong>{valueLabel(item.targetValue, item.unit)}</strong><em data-down={item.absoluteChange < 0 || undefined}>{item.absoluteChange > 0 ? "▲" : item.absoluteChange < 0 ? "▼" : ""} {valueLabel(Math.abs(item.absoluteChange), item.changeUnit)}</em></li>
                    ))}
                  </ul>
                ) : <p className={styles.limitation}>{comparison?.limitations.join(" ") || "비교할 일별 측정이 아직 없어요."}</p>}
              </section>

              <section className={styles.block}>
                <div className={styles.blockHead}><div><span>ALL MEASUREMENTS</span><h3>전체 측정 이력</h3></div><small>최초·수동·자동 측정을 모두 포함해요.</small></div>
                {history?.items.length ? (
                  <ul className={styles.history}>
                    {[...history.items].reverse().map((item) => (
                      <li key={item.measurementId}>
                        <time>{periodLabel(item.startAt, item.endAt)}</time>
                        <b>{item.status === "success" ? "측정 완료" : "측정 불가"}</b>
                        <span>{measurementNote(item)}</span>
                      </li>
                    ))}
                  </ul>
                ) : <p className={styles.limitation}>저장된 측정 이력이 없어요.</p>}
              </section>

              <section className={styles.block}>
                <div className={styles.blockHead}><div><span>DAILY HISTORY</span><h3>일별 실행 이력</h3></div></div>
                {daily?.items.length ? (
                  <ul className={styles.history}>
                    {daily.items.map((item) => (
                      <li key={item.executionId}>
                        <time>{periodLabel(item.startAt, item.endAt)}</time>
                        <b data-status={item.status}>{item.status === "running" ? "측정 중" : item.status === "unavailable" && item.measurement?.status === "success" ? "재측정 완료" : item.measurement?.status === "success" ? "완료" : "측정 불가"}</b>
                        <span>{item.measurement ? measurementNote(item.measurement) : "결과를 기다리고 있어요."}</span>
                      </li>
                    ))}
                  </ul>
                ) : <p className={styles.limitation}>자동 실행된 일별 결과가 아직 없어요.</p>}
                {daily?.nextBefore ? <button type="button" className={styles.more} disabled={Boolean(busy)} onClick={() => void loadMore()}>이전 결과 더 보기</button> : null}
              </section>

              {notice ? <p className={styles.notice} role="status">{notice}</p> : null}
              {error ? <p className={styles.error} role="alert">{error}</p> : null}
            </div>
          ) : null}
        </section>
      </div>
    </Overlay>
  );
}
