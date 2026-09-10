"use client";

import { useEffect, useRef, useState } from "react";
import type { AnalysisMetricFact } from "../../customer-intelligence/contracts";
import { HeartMark } from "../brand/Brand";
import { Overlay } from "../Overlay";
import { BrowserNotificationSettings } from "../alerts/BrowserNotificationSettings";
import {
  SignalClient,
  SignalClientError,
  type AlertRecommendation,
  type AlertRules,
  type RegisteredSignal,
  type SignalMetricValue,
  type SignalProposal,
} from "./signal-client";
import styles from "./watch-signal.module.css";

interface RuleDraft {
  id: string;
  signalId: string;
  proposalId: string;
  proposalTitle: string;
  metric: SignalMetricValue;
  selected: boolean;
  threshold: string;
  criterion: AlertRecommendation;
}

interface WatchSignalModalProps {
  runId: string;
  fallbackMetrics: readonly AnalysisMetricFact[];
  onClose: () => void;
  onSaved: (count: number) => void;
  onGoHome: () => void;
}

const client = new SignalClient();

function displayUnit(unit: string): string {
  const units: Record<string, string> = {
    customers: "명", percent: "%", percentage_points: "%p", records: "건", events: "회",
  };
  return units[unit.toLowerCase()] ?? unit;
}

function metricValue(value: number, unit: string): string {
  return `${value.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}${displayUnit(unit)}`;
}

function savedRule(criterion: AlertRecommendation, existing: AlertRules) {
  return existing.items.find((item) => item.recommendationId === criterion.recommendationId)
    ?? existing.items.find((item) => item.metricKey === criterion.metricKey
      && item.metricUnit === criterion.metricUnit && item.kind === "value" && item.operator === "gte");
}

async function prepareRules(proposal: SignalProposal, signal: AbortSignal) {
  const registration = await client.registerProposal(proposal.proposalId, signal);
  const current = registration.alertRecommendations;
  const [criteria, existing] = await Promise.all([
    current?.status === "ready" && current.source === "measurement"
      ? Promise.resolve(current)
      : client.generateAlertRecommendations(registration.signalId, signal),
    client.getAlertRules(registration.signalId, signal),
  ]);
  if (criteria.status !== "ready" || criteria.source !== "measurement") {
    throw new Error(criteria.reason ?? "분석 지표를 불러오지 못했어요. 다시 시도해 주세요.");
  }
  const byKey = new Map(criteria.items
    .filter((item) => item.kind === "value" && item.operator === "gte")
    .map((item) => [item.metricKey, item]));
  const seen = new Set<string>();
  const rules: RuleDraft[] = [];
  for (const metric of proposal.metrics) {
    if (metric.key === "val_count" || /확인용/.test(metric.label) || seen.has(metric.key)) continue;
    seen.add(metric.key);
    const criterion = byKey.get(metric.key);
    // An unrelated condition must never replace a metric missing from this signal.
    if (!criterion || criterion.metricUnit !== metric.unit) {
      throw new Error("일부 지표의 알림 기준을 불러오지 못했어요. 다시 시도해 주세요.");
    }
    const saved = savedRule(criterion, existing);
    rules.push({
      id: `${registration.signalId}:${metric.key}`,
      signalId: registration.signalId,
      proposalId: proposal.proposalId,
      proposalTitle: proposal.title,
      metric,
      criterion,
      selected: existing.revision > 0 ? Boolean(saved) : metric.key !== "denominator_customer_count",
      threshold: String(saved?.threshold ?? criterion.threshold),
    });
  }
  return { registration, existing, rules };
}

export function WatchSignalModal({ runId, fallbackMetrics, onClose, onSaved, onGoHome }: WatchSignalModalProps) {
  const [rules, setRules] = useState<RuleDraft[]>([]);
  const [registrations, setRegistrations] = useState<RegisteredSignal[]>([]);
  const [revisions, setRevisions] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedCount, setSavedCount] = useState<number | null>(null);
  const [attempt, setAttempt] = useState(0);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoadError(null);
    setSubmitError(null);
    setRules([]);
    setRegistrations([]);
    setSavedCount(null);
    async function load() {
      const proposals = await client.listProposals(runId, controller.signal);
      if (!proposals.length) throw new Error("아직 알림을 설정할 수 있는 분석 지표가 없어요.");
      const loaded = await Promise.all(proposals.map((proposal) => prepareRules(proposal, controller.signal)));
      const prepared = [...new Map(loaded.map((item) => [item.registration.signalId, item])).values()];
      if (controller.signal.aborted) return;
      setRules(prepared.flatMap((item) => item.rules));
      setRegistrations(prepared.map((item) => item.registration));
      setRevisions(Object.fromEntries(prepared.map((item) => [item.registration.signalId, item.existing.revision])));
    }
    void load().catch((error: unknown) => {
      if (!controller.signal.aborted) setLoadError(error instanceof Error ? error.message : "분석 지표를 불러오지 못했어요.");
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [runId, attempt]);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape" && !saving) onCloseRef.current();
      if (event.key !== "Tab") return;
      const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), input:not(:disabled), [tabindex="0"]',
      );
      if (!focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKey);
    };
  }, [saving]);

  const selected = rules.filter((rule) => rule.selected);
  const allSelected = rules.length > 0 && selected.length === rules.length;
  const proposalIds = [...new Set(rules.map((rule) => rule.proposalId))];

  function updateRule(id: string, patch: Partial<RuleDraft>) {
    setRules((current) => current.map((rule) => rule.id === id ? { ...rule, ...patch } : rule));
  }

  async function saveRules() {
    for (const rule of selected) {
      const value = Number(rule.threshold);
      if (!rule.threshold.trim() || !Number.isFinite(value)) {
        setSubmitError("알림 기준을 숫자로 입력해 주세요."); return;
      }
      if (["percent", "%"].includes(rule.metric.unit) && (value < 0 || value > 100)) {
        setSubmitError(`${rule.metric.label} 기준은 0부터 100 사이로 입력해 주세요.`); return;
      }
      if (["affected_customer_count", "denominator_customer_count"].includes(rule.metric.key) && value < 0) {
        setSubmitError("고객 수 기준은 0 이상으로 입력해 주세요."); return;
      }
    }
    setSaving(true);
    setSubmitError(null);
    try {
      // Retain each successful revision if a later signal fails, so retry is safe.
      for (const registration of registrations) {
        const saved = await client.replaceAlertRules(registration.signalId, revisions[registration.signalId] ?? 0,
          selected.filter((rule) => rule.signalId === registration.signalId).map((rule) => ({
            recommendationId: rule.criterion.recommendationId, threshold: Number(rule.threshold),
          })));
        setRevisions((current) => ({ ...current, [registration.signalId]: saved.revision }));
      }
      setSavedCount(selected.length);
      onSaved(selected.length);
    } catch (error) {
      if (error instanceof SignalClientError && error.status === 409) {
        try {
          const latest = await Promise.all(registrations.map((item) => client.getAlertRules(item.signalId)));
          const bySignal = new Map(latest.map((item) => [item.signalId, item]));
          setRevisions(Object.fromEntries(latest.map((item) => [item.signalId, item.revision])));
          setRules((current) => current.map((rule) => {
            const existing = bySignal.get(rule.signalId)!;
            const saved = savedRule(rule.criterion, existing);
            return { ...rule, selected: Boolean(saved), threshold: String(saved?.threshold ?? rule.criterion.threshold) };
          }));
          setSubmitError("다른 화면에서 기준이 바뀌어 최신 내용을 불러왔어요. 확인한 뒤 다시 저장해 주세요.");
        } catch {
          setLoadError("최신 알림 기준을 불러오지 못했어요. 다시 불러온 뒤 저장해 주세요.");
        }
      } else {
        setSubmitError(error instanceof Error ? error.message : "알림 기준을 저장하지 못했어요.");
      }
    } finally { setSaving(false); }
  }

  return (
    <Overlay>
      <div className={styles.scrim} onMouseDown={(event) => {
        if (event.target === event.currentTarget && !saving) onClose();
      }}>
        <div ref={dialogRef} className={styles.modal} role="dialog" aria-modal="true" aria-labelledby="watch-title" aria-describedby="watch-description">
          {savedCount === null ? <>
            <header className={styles.head}>
              <div>
                <p className={styles.eyebrow}><span /> CHANGE WATCH</p>
                <h2 id="watch-title">어떤 변화가 생기면 알려드릴까요?</h2>
                <p id="watch-description">상세에서 확인한 지표예요. 알림을 받을 항목을 고르고 기준값만 바꿔 주세요.</p>
              </div>
              <button ref={closeRef} type="button" className={styles.close} disabled={saving} onClick={onClose} aria-label="닫기">✕</button>
            </header>
            <div className={styles.controlBar}>
              <label className={styles.allChoice}>
                <input type="checkbox" checked={allSelected} disabled={loading || saving || !!loadError} onChange={(event) => {
                  const checked = event.target.checked;
                  setRules((current) => current.map((rule) => ({ ...rule, selected: checked })));
                }} />
                <span className={styles.controlHeart} aria-hidden="true"><HeartMark size={10} /></span>
                <span>모두 선택</span>
              </label>
              <span><b>{selected.length}</b>개 선택 · 매일 확인</span>
            </div>
            <div className={styles.body}>
              {loading ? <div className={styles.loading} role="status"><i />분석에서 확인한 지표를 불러오고 있어요</div>
                : loadError ? <>
                  <p className={styles.loadNote} role="alert">{loadError}</p>
                  <button type="button" className={styles.back} onClick={() => setAttempt((value) => value + 1)}>다시 불러오기</button>
                  {fallbackMetrics.filter((metric) => Number.isFinite(metric.value)).map((metric) => (
                    <p key={metric.metric_key} className={styles.loadNote}>{metric.label} {metricValue(metric.value, metric.unit)} (분석 당시)</p>
                  ))}
                </> : proposalIds.map((proposalId) => {
                  const group = rules.filter((rule) => rule.proposalId === proposalId);
                  return <section key={proposalId} className={styles.signalGroup} aria-label={group[0].proposalTitle}>
                    <h3>{group[0].proposalTitle}</h3>
                    <ul className={styles.metricList}>
                      {group.map((rule) => <li key={rule.id} data-selected={rule.selected}>
                        <label className={styles.metricChoice}>
                          <input type="checkbox" checked={rule.selected} disabled={saving} onChange={(event) => updateRule(rule.id, { selected: event.target.checked })} />
                          <span className={styles.checkmark} aria-hidden="true"><HeartMark size={12} /></span>
                          <span className={styles.metricName}>{rule.metric.label}</span>
                        </label>
                        <div className={styles.current}><span>분석 당시</span><strong>{metricValue(rule.metric.value, rule.metric.unit)}</strong></div>
                        <div className={styles.threshold}>
                          <label>
                            <input type="number" aria-label={`${rule.metric.label} 기준값`} value={rule.threshold} step="any"
                              min={["percent", "%", "customers"].includes(rule.metric.unit) ? 0 : undefined}
                              max={["percent", "%"].includes(rule.metric.unit) ? 100 : undefined}
                              disabled={!rule.selected || saving} onChange={(event) => updateRule(rule.id, { threshold: event.target.value })} />
                            <em>{displayUnit(rule.metric.unit)}</em>
                          </label>
                          <span className={styles.ruleOperator}>이상이면 알려드려요</span>
                        </div>
                      </li>)}
                    </ul>
                  </section>;
                })}
            </div>
            <footer className={styles.foot}>
              <div><strong>{selected.length ? `${selected.length}개 지표의 변화를 확인해요` : "선택한 알림이 없어요"}</strong><span>매일 측정한 값이 기준에 도달하면 알려드려요.</span></div>
              <button type="button" className={styles.submit} disabled={saving || loading || !!loadError || !rules.length} onClick={saveRules}>
                {saving ? "저장하는 중…" : selected.length ? "변화 캐치 시작하기" : "알림 설정 저장"}
              </button>
              {submitError ? <p className={styles.error} role="alert">{submitError}</p> : null}
              <p className={styles.persistenceNote}>처음 표시한 기준값은 분석 당시 수치예요. 하루에 확인할 기준으로 조정해 주세요.</p>
            </footer>
          </> : <div className={styles.done} role="status">
            <button ref={closeRef} type="button" className={styles.close} onClick={onClose} aria-label="닫기">✕</button>
            <span className={styles.doneMark} aria-hidden="true"><HeartMark size={34} /></span>
            <p className={styles.eyebrow}><span /> CATCHING</p>
            <h2 id="watch-title">{savedCount ? "이제 변화는 캐치캐치가 볼게요" : "알림 설정을 저장했어요"}</h2>
            <p id="watch-description">{savedCount ? `선택한 ${savedCount}개 지표를 매일 확인해요. 설정한 값 이상이면 알려드릴게요.` : "선택한 지표의 알림을 모두 껐어요."}</p>
            {savedCount > 0 ? <BrowserNotificationSettings /> : null}
            {savedCount > 0 ? <p style={{ display: "none" }}>상단의 하루 빨리감기로 다음 날짜의 변화를 확인할 수 있어요.</p> : null}
            <button type="button" className={styles.submit} onClick={onGoHome}>메인화면으로 돌아가기</button>
          </div>}
        </div>
      </div>
    </Overlay>
  );
}
