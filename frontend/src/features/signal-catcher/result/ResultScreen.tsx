"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { CatchReport, EvidenceMap, RunOutcome } from "../state/types";

import { EvidencePanel } from "./EvidencePanel";
import { JourneyFlow } from "./JourneyFlow";
import { ProcessTrace } from "./ProcessTrace";
import { WatchSignalModal } from "./WatchSignalModal";
import styles from "./result.module.css";

const SENTENCE_END = /[.!?。](?:\s+|$)/;
const NUMBERED_SECTION = /\s(?=1\.\s)/;
const ACTION_PREAMBLE = /^개선 가설입니다[.!?。]?\s*/;
const SUMMARY_SECTION = /\[(조사 배경 및 개요|패턴\s*\d+\s*[:：]\s*[^\]]+|분석 한계)\]/g;
const SUMMARY_SECTION_START = /\[(조사 배경 및 개요|패턴\s*\d+\s*[:：]\s*[^\]]+|분석 한계)\]/;
const SUMMARY_LABEL = /[-–—]\s*(행동 근거|정상 대조군 비교|최종 해결 및 개선 제안)\s*[:：]/g;

type SummarySectionKind = "context" | "pattern" | "limitation" | "plain";

interface SummaryPoint {
  label: string | null;
  text: string;
}

interface SummarySection {
  key: string;
  kind: SummarySectionKind;
  eyebrow: string | null;
  title: string | null;
  points: SummaryPoint[];
}

function splitLead(text: string) {
  const value = text.trim();
  const sentenceEnd = value.search(SENTENCE_END);
  if (sentenceEnd < 0) return { lead: value, detail: "" };
  const end = sentenceEnd + 1;
  return {
    lead: value.slice(0, end).trim(),
    detail: value.slice(end).trim(),
  };
}

function splitSummary(text: string) {
  const value = text.trim();
  const structuredStart = value.search(SUMMARY_SECTION_START);

  if (structuredStart > 0) {
    return {
      lead: value.slice(0, structuredStart).trim(),
      detail: value.slice(structuredStart).trim(),
    };
  }

  // 요약이 섹션 마커로 바로 시작해도 제목은 읽을 수 있는 핵심 문장으로 보여준다.
  // 전체 원문은 detail에 남겨 섹션 맥락이 사라지지 않게 한다.
  if (structuredStart === 0) {
    const firstMarkerEnd = value.indexOf("]") + 1;
    const firstSectionCopy = splitLead(value.slice(firstMarkerEnd));
    return {
      lead: firstSectionCopy.lead || value,
      detail: value,
    };
  }

  const [overview, ...sections] = value.split(NUMBERED_SECTION);
  if (sections.length) {
    return { lead: overview.trim(), detail: `1. ${sections.join(" ").trim()}` };
  }
  return splitLead(value);
}

function parseSummaryPoints(text: string): SummaryPoint[] {
  const matches = Array.from(text.matchAll(SUMMARY_LABEL));
  if (!matches.length) {
    return text.trim() ? [{ label: null, text: text.trim() }] : [];
  }

  const points: SummaryPoint[] = [];
  const prefix = text.slice(0, matches[0].index).trim();
  if (prefix) points.push({ label: null, text: prefix });

  matches.forEach((match, index) => {
    const contentStart = (match.index ?? 0) + match[0].length;
    const contentEnd = matches[index + 1]?.index ?? text.length;
    points.push({
      label: match[1],
      text: text.slice(contentStart, contentEnd).trim(),
    });
  });

  return points;
}

function sectionMeta(rawTitle: string): Pick<SummarySection, "kind" | "eyebrow" | "title"> {
  const pattern = rawTitle.match(/^패턴\s*(\d+)\s*[:：]\s*(.+)$/);
  if (pattern) {
    return {
      kind: "pattern",
      eyebrow: `패턴 ${pattern[1]}`,
      title: pattern[2].trim(),
    };
  }
  if (rawTitle === "분석 한계") {
    return { kind: "limitation", eyebrow: "CHECK", title: rawTitle };
  }
  return { kind: "context", eyebrow: "CONTEXT", title: rawTitle };
}

function parseSummaryDetail(text: string): SummarySection[] {
  const matches = Array.from(text.matchAll(SUMMARY_SECTION));
  if (!matches.length) {
    return [{
      key: "summary-plain",
      kind: "plain",
      eyebrow: null,
      title: null,
      points: parseSummaryPoints(text),
    }];
  }

  const sections: SummarySection[] = [];
  const prefix = text.slice(0, matches[0].index).trim();
  if (prefix) {
    sections.push({
      key: "summary-prefix",
      kind: "plain",
      eyebrow: null,
      title: null,
      points: parseSummaryPoints(prefix),
    });
  }

  matches.forEach((match, index) => {
    const contentStart = (match.index ?? 0) + match[0].length;
    const contentEnd = matches[index + 1]?.index ?? text.length;
    const meta = sectionMeta(match[1]);
    sections.push({
      key: `summary-section-${index}`,
      ...meta,
      points: parseSummaryPoints(text.slice(contentStart, contentEnd)),
    });
  });

  return sections;
}

function readableParagraphs(text: string) {
  const value = text.trim();
  if (!value) return [];

  const paragraphs: string[] = [];
  const boundaries = Array.from(value.matchAll(/[.!?。](?=\s+)|\n\s*\n/g));
  let start = 0;
  for (const boundary of boundaries) {
    const end = (boundary.index ?? 0) + boundary[0].length;
    const paragraph = value.slice(start, end).trim();
    if (paragraph) paragraphs.push(paragraph);
    start = end;
  }
  const remainder = value.slice(start).trim();
  if (remainder) paragraphs.push(remainder);
  return paragraphs;
}

function SummaryDetail({ sections }: { sections: SummarySection[] }) {
  return (
    <div className={styles.summaryDetail}>
      {sections.map((section) => (
        <section
          key={section.key}
          className={styles.summarySection}
          data-kind={section.kind}
          aria-label={section.title ?? "상세 분석"}
        >
          <header className={styles.summarySectionHead}>
            {section.eyebrow ? <p>{section.eyebrow}</p> : null}
            <h3>{section.title ?? "상세 분석"}</h3>
          </header>
          <div className={styles.summarySectionBody}>
            {section.points.map((point, pointIndex) => {
              const paragraphs = readableParagraphs(point.text);
              return point.label ? (
                <div className={styles.summaryPoint} key={`${section.key}-point-${pointIndex}`}>
                  <p className={styles.summaryPointLabel}>{point.label}</p>
                  <div className={styles.summaryParagraphs}>
                    {paragraphs.map((paragraph, paragraphIndex) => (
                      <p key={`${section.key}-point-${pointIndex}-paragraph-${paragraphIndex}`}>
                        {paragraph}
                      </p>
                    ))}
                  </div>
                </div>
              ) : (
                <div className={styles.summaryParagraphs} key={`${section.key}-point-${pointIndex}`}>
                  {paragraphs.map((paragraph, paragraphIndex) => (
                    <p key={`${section.key}-paragraph-${pointIndex}-${paragraphIndex}`}>
                      {paragraph}
                    </p>
                  ))}
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}

function sourceLabelForEvidence(id: string, sourceLabels: Record<string, string>) {
  for (const [sourceId, label] of Object.entries(sourceLabels)) {
    if (id.includes(sourceId)) return label;
  }
  return "원본 데이터";
}

interface EvidenceLinksProps {
  ids: string[];
  sourceLabels: Record<string, string>;
  onOpen: (id: string) => void;
}

function EvidenceLinks({ ids, sourceLabels, onOpen }: EvidenceLinksProps) {
  if (!ids.length) return null;
  const labels = ids.map((id) => sourceLabelForEvidence(id, sourceLabels));
  const sources = [...new Set(labels)];

  return (
    <details className={styles.evidenceGroup}>
      <summary>
        <strong>근거 {ids.length.toLocaleString("ko-KR")}개</strong>
        <span>{sources.slice(0, 3).join(" · ")}{sources.length > 3 ? ` 외 ${sources.length - 3}곳` : ""}</span>
        <i aria-hidden="true">⌄</i>
      </summary>
      <div className={styles.evidenceLinks}>
        {ids.map((id, index) => (
          <button
            key={id}
            type="button"
            aria-label={`${labels[index]} 근거 ${index + 1} 열기`}
            onClick={() => onOpen(id)}
          >
            <span>{labels[index]}</span>
            <small>{String(index + 1).padStart(2, "0")}</small>
          </button>
        ))}
      </div>
    </details>
  );
}

interface ResultScreenProps {
  report: CatchReport;
  outcome: RunOutcome;
  onOpenTrace: () => void;
  onRestart: () => void;
  /** 액션 상세로 이동. 다음 행동 카드가 곧 실험 목록 역할을 한다. */
  onOpenAction: (actionId: string) => void;
  experimentOf: (actionId: string) => { status: string; elapsedDays: number; observeDays: number; hits: number; total: number } | undefined;
  /** 리포트에서 넘어온 다음 액션. 그 카드로 안내한다. */
  highlightActionId: string | null;
  onHighlightSeen: () => void;
  /** 이 분석 이후 적용된 실험. 리포트를 고치지 않고 맥락만 얹는다. */
  applied: { actionId: string; title: string; status: string }[];
  evidence: EvidenceMap;
  evidenceLoadingId: string | null;
  evidenceErrorId: string | null;
  onLoadEvidence: (evidenceId: string) => void;
  onGoHome: () => void;
}

export function ResultScreen({
  report,
  outcome,
  onOpenTrace,
  onRestart,
  onOpenAction,
  experimentOf,
  highlightActionId,
  onHighlightSeen,
  applied,
  evidence,
  evidenceLoadingId,
  evidenceErrorId,
  onLoadEvidence,
  onGoHome,
}: ResultScreenProps) {
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const [limitsOpen, setLimitsOpen] = useState(false);
  const [watchOpen, setWatchOpen] = useState(false);
  const [watching, setWatching] = useState(false);
  const highlightRef = useRef<HTMLLIElement>(null);

  /*
   * 리포트의 "이어지는 액션"에서 넘어오면 결과 화면 어딘가에 떨어져 당황하게 된다.
   * 해당 카드로 데려간 뒤 잠깐 표시해 어디를 보라는지 알린다.
   */
  useEffect(() => {
    if (!highlightActionId) return;
    const timer = setTimeout(() => {
      highlightRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 80);
    const clear = setTimeout(onHighlightSeen, 2600);
    return () => {
      clearTimeout(timer);
      clearTimeout(clear);
    };
  }, [highlightActionId, onHighlightSeen]);

  const degraded = outcome === "degraded";
  // 탈락한 주장은 과정 보기 안쪽 검증 기록에 싣는다. 여기 남는 건 통과한 것뿐이다.
  const findings = report.findings.filter((claim) => claim.verdict === "passed");
  const summary = useMemo(() => {
    const copy = splitSummary(report.summary);
    return {
      ...copy,
      sections: copy.detail ? parseSummaryDetail(copy.detail) : [],
    };
  }, [report.summary]);

  function openEvidence(id: string) {
    setEvidenceId(id);
    onLoadEvidence(id);
  }

  return (
    <div className={styles.screen}>
      <div className={styles.inner}>
        <header className={styles.head}>
          {report.limitations.length ? (
            <div className={styles.headTop}>
              <button
                type="button"
                className={styles.degraded}
                onClick={() => setLimitsOpen((prev) => !prev)}
                aria-expanded={limitsOpen}
              >
                {degraded ? "부분 캐치" : "확인하지 못한 것"}
              </button>
            </div>
          ) : null}

          <h1 className={styles.headline}>
            {report.headline}
            <br />
            <em>{report.headlineCount.toLocaleString("ko-KR")}명</em>을 찾았어요
          </h1>
          {report.headlineTrailer ? (
            <p className={styles.trailer}>{report.headlineTrailer}</p>
          ) : null}

          {limitsOpen ? (
            <ul className={styles.limits}>
              {report.limitations.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}

          {/* 언제 자른 스냅샷인지. 리포트를 사후에 갱신하지 않으므로 시점을 못 박는다. */}
          <dl className={styles.snapshot} aria-label="스냅샷 정보">
            <div>
              <dt>데이터</dt>
              <dd>{report.periodLabel}</dd>
            </div>
            <div>
              <dt>분석</dt>
              <dd>{report.analyzedAt}</dd>
            </div>
          </dl>

          {/*
            리포트는 사후에 갱신하지 않는다. 갱신하면 "이 결론이 나온 과정"을
            재현할 수 없어진다. 대신 이후에 무슨 일이 있었는지 맥락만 얹는다.
          */}
          {applied.length ? (
            <div className={styles.after} role="status">
              <p>
                이 분석 이후 <strong>{applied[0].title}</strong>를 적용
                {applied[0].status === "done" ? "했어요" : "해 관찰 중이에요"}.
                아래 수치는 <strong>적용 전 시점</strong>의 값입니다.
              </p>
              <button type="button" onClick={() => onOpenAction(applied[0].actionId)}>
                {applied[0].status === "done" ? "실험 결과 보기" : "경과 보기"}
                <span aria-hidden="true"> →</span>
              </button>
            </div>
          ) : null}

          <section className={styles.summaryCard} aria-labelledby="result-summary-title">
            <p className={styles.summaryKicker}>분석 한눈에 보기</p>
            <h2 id="result-summary-title" className={styles.summary}>{summary.lead}</h2>
            {summary.detail ? (
              <details className={styles.copyDetails}>
                <summary>전체 분석 요약 보기 <span aria-hidden="true">⌄</span></summary>
                <SummaryDetail sections={summary.sections} />
              </details>
            ) : null}
          </section>

          <dl className={styles.metrics}>
            {report.metrics.map((metric) => {
              const missing = Number.isNaN(metric.value);
              return (
                <div key={metric.metric_key} data-missing={missing}>
                  <dt>{metric.label}</dt>
                  <dd>
                    {missing ? (
                      <span className={styles.metricMissing}>근거 부족</span>
                    ) : (
                      <>
                        {metric.value.toLocaleString("ko-KR")}
                        <small>{metric.unit}</small>
                      </>
                    )}
                  </dd>
                </div>
              );
            })}
          </dl>

          <aside className={styles.watchCallout} data-watching={watching}>
            <span className={styles.watchPulse} aria-hidden="true">
              <i />
            </span>
            <div>
              <p>{watching ? "변화 캐치 중" : "발견 다음"}</p>
              <h2>{watching ? "이 발견의 변화를 계속 보고 있어요" : "이 변화, 놓치지 않게 맡겨두세요"}</h2>
              <span>
                {watching
                  ? "매일 측정할 지표와 감지 기준을 저장해두었어요."
                  : "의미 있는 수치 변화가 생기는지 캐치캐치가 매일 확인할게요."}
              </span>
            </div>
            <button type="button" onClick={() => setWatchOpen(true)}>
              {watching ? "감지 기준 다시 보기" : "변화 캐치 맡기기"}
              <span aria-hidden="true"> →</span>
            </button>
          </aside>
        </header>

        <section className={styles.block}>
          <h2 className={styles.blockTitle}>고객 여정 맵</h2>
          <p className={styles.blockNote}>
            가장 복잡했던 고객 한 명의 여정을 그대로 폈습니다.
            점을 누르면 그 행동의 원본 근거가 열려요.
          </p>
          {report.journey.length ? (
            <JourneyFlow report={report} onOpenEvidence={openEvidence} />
          ) : (
            <p className={styles.blockNote}>공개할 수 있는 대표 고객 여정이 없습니다.</p>
          )}
        </section>

        <section className={styles.insight} aria-label="검증된 발견과 다음 행동">
          <div className={styles.insightGroup}>
            <header className={styles.sectionHead}>
              <div>
                <p>VERIFIED FINDINGS</p>
                <h2>검증된 발견</h2>
              </div>
              <span>{findings.length.toLocaleString("ko-KR")}</span>
              <small>결론부터 읽고, 필요할 때 검증 내용과 원본 근거를 펼쳐보세요.</small>
            </header>
            <ul className={styles.findings}>
              {findings.map((claim, index) => {
                const copy = splitLead(claim.statement);
                return (
                  <li key={claim.claimId}>
                    <p className={styles.findingIndex}>검증 {String(index + 1).padStart(2, "0")}</p>
                    <h3 className={styles.findingText}>{copy.lead}</h3>
                    {copy.detail ? (
                      <details className={styles.copyDetails}>
                        <summary>검증 내용 자세히 <span aria-hidden="true">⌄</span></summary>
                        <p>{copy.detail}</p>
                      </details>
                    ) : null}
                    <EvidenceLinks
                      ids={claim.evidenceIds}
                      sourceLabels={report.sourceLabels}
                      onOpen={openEvidence}
                    />
                  </li>
                );
              })}
            </ul>
            {!findings.length ? <p className={styles.insightEmpty}>검증을 통과한 발견이 없습니다.</p> : null}
          </div>

          <div className={styles.insightGroup}>
            <header className={styles.sectionHead}>
              <div>
                <p>NEXT ACTIONS</p>
                <h2>다음 행동</h2>
              </div>
              <span>{report.actions.length.toLocaleString("ko-KR")}</span>
              <small>발견을 실제 개선으로 옮길 수 있도록 행동 단위로 정리했어요.</small>
            </header>
            <ul className={styles.actions}>
              {report.actions.map((item, index) => {
                const exp = experimentOf(item.actionId);
                const reason = splitLead(item.reason.replace(ACTION_PREAMBLE, ""));
                return (
                  <li
                    key={item.actionId}
                    ref={item.actionId === highlightActionId ? highlightRef : undefined}
                    data-highlight={item.actionId === highlightActionId}
                  >
                    <div className={styles.actionNumber} aria-hidden="true">
                      {String(index + 1).padStart(2, "0")}
                    </div>
                    <div className={styles.actionBody}>
                      {exp ? (
                        <p className={styles.actionState} data-status={exp.status}>
                          <span>
                            {exp.status === "done"
                              ? `실험 완료 · 예측 ${exp.total}개 중 ${exp.hits}개 적중`
                              : `관찰 중 · ${exp.elapsedDays}일째`}
                          </span>
                          {exp.status === "watching" ? (
                            <i>
                              <b
                                style={{
                                  width: `${(exp.elapsedDays / exp.observeDays) * 100}%`,
                                }}
                              />
                            </i>
                          ) : null}
                        </p>
                      ) : null}
                      <h3>{item.title}</h3>
                      <p className={styles.actionReason}>{reason.lead}</p>
                      {reason.detail ? (
                        <details className={styles.copyDetails}>
                          <summary>판단 근거 자세히 <span aria-hidden="true">⌄</span></summary>
                          <p>{reason.detail}</p>
                        </details>
                      ) : null}
                      <div className={styles.actionFoot}>
                        <EvidenceLinks
                          ids={item.evidenceIds}
                          sourceLabels={report.sourceLabels}
                          onOpen={openEvidence}
                        />
                        {item.keywords ? (
                          <button
                            type="button"
                            className={styles.primaryBtn}
                            onClick={() => onOpenAction(item.actionId)}
                          >
                            {exp ? "경과 보기" : "미리보기"}
                          </button>
                        ) : (
                          <span className={styles.actionSoon}>제안 완료</span>
                        )}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
            {!report.actions.length ? <p className={styles.insightEmpty}>제안할 다음 행동이 없습니다.</p> : null}
          </div>
        </section>

        {/* 분석가 모드 대신 이 자리. 로딩 때 흘러간 처리 과정을 그대로 다시 편다. */}
        <ProcessTrace report={report} onOpenTrace={onOpenTrace} />

        <footer className={styles.foot}>
          <button type="button" className={styles.ghostBtn} onClick={onRestart}>
            새로 캐치하기
          </button>
        </footer>
      </div>

      {evidenceId ? (
        <EvidencePanel
          evidenceId={evidenceId}
          record={evidence[evidenceId] ?? null}
          loading={evidenceLoadingId === evidenceId}
          failed={evidenceErrorId === evidenceId}
          sourceLabels={report.sourceLabels}
          onRetry={() => onLoadEvidence(evidenceId)}
          onClose={() => setEvidenceId(null)}
        />
      ) : null}

      {watchOpen ? (
        <WatchSignalModal
          runId={report.runId}
          fallbackMetrics={report.metrics}
          onClose={() => setWatchOpen(false)}
          onSaved={(count) => setWatching(count > 0)}
          onGoHome={onGoHome}
        />
      ) : null}
    </div>
  );
}
