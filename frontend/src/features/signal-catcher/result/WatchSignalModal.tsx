"use client";

import { useEffect, useRef, useState } from "react";

import type { AnalysisMetricFact } from "../../customer-intelligence/contracts";

import { HeartMark } from "../brand/Brand";
import { Overlay } from "../Overlay";

import {
  SignalClient,
  SignalClientError,
  type AlertRecommendation,
  type AlertRecommendationSet,
  type AlertRules,
  type RegisteredSignal,
  type SignalProposal,
} from "./signal-client";
import styles from "./watch-signal.module.css";

interface ProposalMetricDraft {
  id: string;
  proposalId: string | null;
  proposalTitle: string | null;
  key: string;
  label: string;
  value: number;
  unit: string;
  selected: boolean;
}

interface RuleDraft {
  id: string;
  signalId: string;
  proposalId: string | null;
  selected: boolean;
  threshold: string;
  source: AlertRecommendationSet["source"];
  recommendation: AlertRecommendation;
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
  const normalized = unit.toLowerCase();
  if (normalized === "customers") return "명";
  if (normalized === "percent") return "%";
  if (normalized === "percentage_points") return "%p";
  if (normalized === "records") return "건";
  if (normalized === "events") return "회";
  return unit;
}

function metricValue(value: number, unit: string): string {
  return `${value.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}${displayUnit(unit)}`;
}

function proposalDraftOf(
  metric: { key: string; label: string; value: number; unit: string },
  proposal: Pick<SignalProposal, "proposalId" | "title"> | null,
  index: number,
): ProposalMetricDraft {
  return {
    id: `${proposal?.proposalId ?? "report"}:${metric.key}:${index}`,
    proposalId: proposal?.proposalId ?? null,
    proposalTitle: proposal?.title ?? null,
    key: metric.key,
    label: metric.label,
    value: metric.value,
    unit: metric.unit,
    selected: metric.key !== "denominator_customer_count",
  };
}

function usefulDrafts(proposals: SignalProposal[]): ProposalMetricDraft[] {
  const drafts: ProposalMetricDraft[] = [];
  const seen = new Set<string>();
  for (const proposal of proposals) {
    for (const metric of proposal.metrics) {
      if (metric.key === "val_count" || /확인용/.test(metric.label)) continue;
      const fingerprint = `${proposal.proposalId}:${metric.key}`;
      if (seen.has(fingerprint)) continue;
      seen.add(fingerprint);
      drafts.push(proposalDraftOf(metric, proposal, drafts.length));
    }
  }
  return drafts;
}

function fallbackDrafts(metrics: readonly AnalysisMetricFact[]): ProposalMetricDraft[] {
  return metrics.flatMap((metric, index) =>
    typeof metric.value === "number" && Number.isFinite(metric.value)
      ? [proposalDraftOf({
          key: metric.metric_key,
          label: metric.label,
          value: metric.value,
          unit: metric.unit,
        }, null, index)]
      : [],
  );
}

function operatorLabel(operator: AlertRecommendation["operator"]): string {
  return { gt: "초과할 때", gte: "이상일 때", lt: "미만일 때", lte: "이하일 때" }[operator];
}

function kindLabel(kind: AlertRecommendation["kind"]): string {
  return {
    value: "하루 측정값",
    absolute_change: "직전 하루와 차이",
    relative_change_percent: "직전 하루 대비 변화율",
  }[kind];
}

function ruleDraftsOf(
  registration: RegisteredSignal,
  recommendations: AlertRecommendationSet,
  existing: AlertRules,
  selectedKeys: Set<string>,
): RuleDraft[] {
  const existingById = new Map(existing.items.map((item) => [item.recommendationId, item]));
  const matching = recommendations.items.filter((item) => selectedKeys.has(item.metricKey));
  const items = matching.length ? matching : recommendations.items;
  return items.map((recommendation) => {
    const saved = existingById.get(recommendation.recommendationId);
    return {
      id: `${registration.signalId}:${recommendation.recommendationId}`,
      signalId: registration.signalId,
      proposalId: registration.proposalId,
      selected: existing.items.length ? Boolean(saved) : true,
      threshold: String(saved?.threshold ?? recommendation.threshold),
      source: recommendations.source,
      recommendation,
    };
  });
}

export function WatchSignalModal({
  runId,
  fallbackMetrics,
  onClose,
  onSaved,
  onGoHome,
}: WatchSignalModalProps) {
  const [step, setStep] = useState<"metrics" | "rules" | "done">("metrics");
  const [metrics, setMetrics] = useState<ProposalMetricDraft[]>([]);
  const [rules, setRules] = useState<RuleDraft[]>([]);
  const [registrations, setRegistrations] = useState<RegisteredSignal[]>([]);
  const [revisions, setRevisions] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [loadNote, setLoadNote] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedCount, setSavedCount] = useState(0);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const controller = new AbortController();
    const fallback = fallbackDrafts(fallbackMetrics);
    setLoading(true);
    client.listProposals(runId, controller.signal)
      .then((proposals) => {
        const fromApi = usefulDrafts(proposals);
        if (!fromApi.length) {
          setLoadNote("아직 등록할 수 있는 추적 후보가 없어 분석 지표만 보여드려요.");
        }
        setMetrics(fromApi.length ? fromApi : fallback);
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setMetrics(fallback);
        setLoadNote("추적 후보를 불러오지 못해 분석 지표만 보여드려요. 잠시 후 다시 열어 주세요.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [fallbackMetrics, runId]);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape" && !saving) {
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), input:not(:disabled), [tabindex="0"]',
      );
      if (!focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", onKey);
    };
  }, [saving]);

  const selectedMetrics = metrics.filter((metric) => metric.selected);
  const selectedRules = rules.filter((rule) => rule.selected);
  const visible = step === "metrics" ? metrics : rules;
  const selectedCount = step === "metrics" ? selectedMetrics.length : selectedRules.length;
  const allSelected = visible.length > 0 && selectedCount === visible.length;

  function updateMetric(id: string, patch: Partial<ProposalMetricDraft>) {
    setMetrics((current) => current.map((metric) => metric.id === id ? { ...metric, ...patch } : metric));
  }

  function updateRule(id: string, patch: Partial<RuleDraft>) {
    setRules((current) => current.map((rule) => rule.id === id ? { ...rule, ...patch } : rule));
  }

  async function readyRecommendations(registration: RegisteredSignal): Promise<AlertRecommendationSet> {
    const current = registration.alertRecommendations;
    if (current?.status === "ready") return current;
    return client.generateAlertRecommendations(registration.signalId);
  }

  async function prepareRules() {
    if (!selectedMetrics.length) {
      setSubmitError("계속 볼 지표를 하나 이상 선택해 주세요.");
      return;
    }
    const proposalIds = [...new Set(selectedMetrics.flatMap((metric) => metric.proposalId ? [metric.proposalId] : []))];
    if (!proposalIds.length) {
      setSubmitError("등록 가능한 추적 후보가 아직 없어요. 잠시 후 모달을 다시 열어 주세요.");
      return;
    }
    setSaving(true);
    setSubmitError(null);
    try {
      const registered = await Promise.all(proposalIds.map((proposalId) => client.registerProposal(proposalId)));
      const prepared = await Promise.all(registered.map(async (registration) => {
        const [recommendations, existing] = await Promise.all([
          readyRecommendations(registration),
          client.getAlertRules(registration.signalId),
        ]);
        if (recommendations.status !== "ready") {
          throw new Error(recommendations.reason ?? "AI 감지 기준을 준비하지 못했습니다.");
        }
        const keys = new Set(selectedMetrics
          .filter((metric) => metric.proposalId === registration.proposalId)
          .map((metric) => metric.key));
        return { registration, recommendations, existing, keys };
      }));
      const nextRules = prepared.flatMap(({ registration, recommendations, existing, keys }) =>
        ruleDraftsOf(registration, recommendations, existing, keys));
      if (!nextRules.length) throw new Error("선택한 지표에 맞는 AI 감지 기준이 없어요.");
      setRegistrations(registered);
      setRevisions(Object.fromEntries(prepared.map(({ registration, existing }) => [registration.signalId, existing.revision])));
      setRules(nextRules);
      setStep("rules");
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "AI 감지 기준을 불러오지 못했습니다.");
    } finally {
      setSaving(false);
    }
  }

  async function saveRules() {
    if (!selectedRules.length) {
      setSubmitError("사용할 감지 기준을 하나 이상 선택해 주세요.");
      return;
    }
    if (selectedRules.some((rule) => rule.threshold.trim() === "" || !Number.isFinite(Number(rule.threshold)))) {
      setSubmitError("감지 기준을 숫자로 입력해 주세요.");
      return;
    }
    setSaving(true);
    setSubmitError(null);
    try {
      await Promise.all(registrations.map((registration) => client.replaceAlertRules(
        registration.signalId,
        revisions[registration.signalId] ?? 0,
        selectedRules
          .filter((rule) => rule.signalId === registration.signalId)
          .map((rule) => ({
            recommendationId: rule.recommendation.recommendationId,
            threshold: Number(rule.threshold),
          })),
      )));
      setSavedCount(selectedRules.length);
      setStep("done");
      onSaved(selectedRules.length);
    } catch (error) {
      if (error instanceof SignalClientError && error.status === 409) {
        try {
          const latest = await Promise.all(registrations.map((registration) => client.getAlertRules(registration.signalId)));
          const latestBySignal = new Map(latest.map((item) => [item.signalId, item]));
          setRevisions(Object.fromEntries(latest.map((item) => [item.signalId, item.revision])));
          setRules((current) => current.map((rule) => {
            const currentRules = latestBySignal.get(rule.signalId)?.items ?? [];
            const saved = currentRules.find((item) => item.recommendationId === rule.recommendation.recommendationId);
            return {
              ...rule,
              selected: Boolean(saved),
              threshold: String(saved?.threshold ?? rule.recommendation.threshold),
            };
          }));
          setSubmitError("다른 화면에서 기준이 바뀌어 최신 내용을 불러왔어요. 확인한 뒤 다시 저장해 주세요.");
        } catch {
          setSubmitError("기준이 다른 화면에서 바뀌었지만 최신 내용을 불러오지 못했어요. 모달을 닫고 다시 열어 주세요.");
        }
      } else {
        setSubmitError(error instanceof Error ? error.message : "감지 기준을 저장하지 못했습니다.");
      }
    } finally {
      setSaving(false);
    }
  }

  function toggleAll(checked: boolean) {
    if (step === "metrics") {
      setMetrics((current) => current.map((metric) => ({ ...metric, selected: checked })));
    } else {
      setRules((current) => current.map((rule) => ({ ...rule, selected: checked })));
    }
  }

  return (
    <Overlay>
      <div className={styles.scrim} onMouseDown={(event) => {
        if (event.target === event.currentTarget && !saving) onClose();
      }}>
        <div
          ref={dialogRef}
          className={styles.modal}
          role="dialog"
          aria-modal="true"
          aria-labelledby="watch-title"
          aria-describedby="watch-description"
        >
          {step !== "done" ? (
            <>
              <header className={styles.head}>
                <div>
                  <p className={styles.eyebrow}><span /> CHANGE WATCH</p>
                  <h2 id="watch-title">
                    {step === "metrics" ? "이 발견의 변화를 계속 캐치할까요?" : "AI가 제안한 첫 감지 기준이에요"}
                  </h2>
                  <p id="watch-description">
                    {step === "metrics"
                      ? "계속 볼 지표를 고르면 AI가 하루 단위의 첫 감지 기준을 제안해요."
                      : "방향은 지표의 의미에 맞춰 정했어요. 숫자는 직접 바꿀 수 있어요."}
                  </p>
                </div>
                <button ref={closeRef} type="button" className={styles.close} onClick={onClose} aria-label="닫기">✕</button>
              </header>

              <div className={styles.controlBar}>
                <label className={styles.allChoice}>
                  <input type="checkbox" checked={allSelected} onChange={(event) => toggleAll(event.target.checked)} />
                  <span className={styles.controlHeart} aria-hidden="true"><HeartMark size={10} /></span>
                  <span>모두 선택</span>
                </label>
                <span><b>{selectedCount}</b>개 선택 · 매일 확인</span>
              </div>

              <div className={styles.body}>
                {loading ? (
                  <div className={styles.loading} role="status"><i />분석에서 추적할 수치를 고르고 있어요</div>
                ) : step === "metrics" && metrics.length ? (
                  <ul className={styles.metricList}>
                    {metrics.map((metric) => (
                      <li key={metric.id} data-selected={metric.selected} data-step="metric">
                        <label className={styles.metricChoice}>
                          <input type="checkbox" checked={metric.selected} onChange={(event) => updateMetric(metric.id, { selected: event.target.checked })} />
                          <span className={styles.checkmark} aria-hidden="true"><HeartMark size={12} /></span>
                          <span className={styles.metricName}>
                            {metric.label}
                            {metric.proposalTitle ? <small>{metric.proposalTitle}</small> : null}
                          </span>
                        </label>
                        <div className={styles.current}>
                          <span>현재</span>
                          <strong>{metricValue(metric.value, metric.unit)}</strong>
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : step === "rules" && rules.length ? (
                  <ul className={styles.metricList}>
                    {rules.map((rule) => (
                      <li key={rule.id} data-selected={rule.selected}>
                        <label className={styles.metricChoice}>
                          <input type="checkbox" checked={rule.selected} onChange={(event) => updateRule(rule.id, { selected: event.target.checked })} />
                          <span className={styles.checkmark} aria-hidden="true"><HeartMark size={12} /></span>
                          <span className={styles.metricName}>
                            {rule.recommendation.metricLabel}
                            <small>{kindLabel(rule.recommendation.kind)}</small>
                          </span>
                        </label>
                        <div className={styles.ruleOperator}>{operatorLabel(rule.recommendation.operator)}</div>
                        <div className={styles.threshold} aria-label={`${rule.recommendation.metricLabel} 감지 기준`}>
                          <label>
                            <span className="sr-only">{rule.recommendation.metricLabel} 기준값</span>
                            <input
                              type="number"
                              value={rule.threshold}
                              step="any"
                              disabled={!rule.selected}
                              onChange={(event) => updateRule(rule.id, { threshold: event.target.value })}
                            />
                            <em>{displayUnit(rule.recommendation.comparisonUnit)}</em>
                          </label>
                        </div>
                        <p className={styles.aiNote}>
                          <b>{rule.source === "model" ? "AI 제안" : "데모 제안"}</b>
                          {rule.recommendation.rationale}
                        </p>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className={styles.empty}>계속 추적할 수 있는 수치가 아직 없어요.</p>
                )}
                {loadNote && step === "metrics" ? <p className={styles.loadNote}>{loadNote}</p> : null}
              </div>

              <footer className={styles.foot}>
                <div>
                  <strong>{selectedCount ? `${selectedCount}개 ${step === "metrics" ? "지표를 선택했어요" : "기준으로 변화를 캐치해요"}` : "계속 볼 항목을 골라 주세요"}</strong>
                  <span>{step === "metrics" ? "다음 단계에서 선택한 후보가 등록되고 AI 기준이 생성돼요." : "저장한 조건은 서버에서 매일 새 데이터와 비교합니다."}</span>
                </div>
                <div className={styles.actions}>
                  {step === "rules" ? (
                    <button type="button" className={styles.back} disabled={saving} onClick={() => { setSubmitError(null); setStep("metrics"); }}>이전</button>
                  ) : null}
                  <button
                    type="button"
                    className={styles.submit}
                    disabled={saving || loading || !visible.length}
                    onClick={step === "metrics" ? prepareRules : saveRules}
                  >
                    {saving
                      ? step === "metrics" ? "AI 기준 준비 중…" : "저장하는 중…"
                      : step === "metrics" ? "AI 감지 기준 받기" : "변화 캐치 시작하기"}
                  </button>
                </div>
                {submitError ? <p className={styles.error} role="alert">{submitError}</p> : null}
                <p className={styles.persistenceNote}>
                  {step === "metrics" ? "등록과 기준 생성에는 최대 1분 정도 걸릴 수 있어요." : "비교 방식은 AI 제안대로 유지되고 기준 숫자만 조정할 수 있어요."}
                </p>
              </footer>
            </>
          ) : (
            <div className={styles.done} role="status">
              <button ref={closeRef} type="button" className={styles.close} onClick={onClose} aria-label="닫기">✕</button>
              <span className={styles.doneMark} aria-hidden="true"><HeartMark size={34} /></span>
              <p className={styles.eyebrow}><span /> CATCHING</p>
              <h2 id="watch-title">이제 변화는 캐치캐치가 볼게요</h2>
              <p id="watch-description">
                선택한 {savedCount}개 기준은 매일 다시 확인돼요. 메인 브리핑에서 최신 측정값을 볼 수 있어요.
              </p>
              <button type="button" className={styles.submit} onClick={onGoHome}>메인화면으로 돌아가기</button>
            </div>
          )}
        </div>
      </div>
    </Overlay>
  );
}
