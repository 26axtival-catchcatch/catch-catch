"use client";

import { useEffect, useRef, useState } from "react";

import { AskScreen, type AskConditions } from "../ask/AskScreen";
import type { SourceOption } from "../state/types";

import { useSwipeDeck } from "./use-swipe-deck";
import type { Briefing, BriefingSignal } from "./types";
import styles from "./briefing.module.css";

interface BriefingScreenProps {
  briefing: Briefing;
  /** 빈 브리핑 카드 안의 메인 입력값. */
  question: string;
  onQuestionChange: (value: string) => void;
  /** 카드의 "이 시그널 확인하기". 그 시그널의 리포트로 넘어간다. */
  onOpenSignal: (signal: BriefingSignal) => void;
  /** 빈 브리핑의 입력으로 지금 바로 훑어 본다. */
  onAsk: (question: string, conditions: AskConditions) => void;
  notice: string | null;
  suggestedQuestions: string[];
  sourceCount?: number | null;
  fixedPeriodLabel?: string;
  conditionsLocked?: boolean;
  periodLocked?: boolean;
  sourceOptions?: readonly SourceOption[];
  initialStartAt?: string;
  initialEndAt?: string;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  loadingMore?: boolean;
  loadMoreError?: string | null;
  onLoadMore?: () => void;
  sourceLabels?: Record<string, string>;
}

/**
 * `*로 감싼 구간*`을 마젠타로 칠한다.
 * 강조가 문자열 안에 있어야 백엔드 문장을 그대로 실어 올 수 있다.
 */
function Highlight({ text }: { text: string }) {
  return (
    <>
      {text.split(/(\*[^*]+\*)/g).map((part, i) =>
        part.length > 2 && part.startsWith("*") && part.endsWith("*") ? (
          <b key={i}>{part.slice(1, -1)}</b>
        ) : (
          part
        ),
      )}
    </>
  );
}

/** 0~1 값을 200×38 뷰박스 안의 꺾은선으로 옮긴다. */
function sparkPath(trend: number[]): string {
  if (trend.length < 2) return "";
  const gap = 200 / (trend.length - 1);
  return trend
    .map((value, i) => `${i === 0 ? "M" : "L"}${(i * gap).toFixed(1)} ${(34 - value * 29).toFixed(1)}`)
    .join(" ");
}

function splitLead(text: string) {
  const value = text.trim();
  const sentenceEnd = value.search(/[.!?。](?:\s+|$)/);
  if (sentenceEnd < 0) return { lead: value, detail: "" };
  const end = sentenceEnd + 1;
  return { lead: value.slice(0, end).trim(), detail: value.slice(end).trim() };
}

function sourceSummary(sourceIds: string[], sourceLabels: Record<string, string>): string | null {
  if (!sourceIds.length) return null;
  const labels = [...new Set(sourceIds.map((id) => sourceLabels[id]).filter(Boolean))];
  if (!labels.length) return `${sourceIds.length.toLocaleString("ko-KR")}개 데이터셋`;
  if (labels.length <= 3) return labels.join(" · ");
  return `${labels.slice(0, 3).join(" · ")} 외 ${labels.length - 3}개`;
}

export function BriefingScreen({
  briefing,
  question,
  onQuestionChange,
  onOpenSignal,
  onAsk,
  notice,
  suggestedQuestions,
  sourceCount,
  fixedPeriodLabel,
  conditionsLocked,
  periodLocked,
  sourceOptions,
  initialStartAt,
  initialEndAt,
  loading = false,
  error = null,
  onRetry,
  loadingMore = false,
  loadMoreError = null,
  onLoadMore,
  sourceLabels = {},
}: BriefingScreenProps) {
  const { signals } = briefing;
  // 훅은 빈 브리핑에서도 같은 순서로 호출하되, 실제 덱은 렌더링하지 않는다.
  const deck = useSwipeDeck(Math.max(signals.length, 1));

  const [exploreOpen, setExploreOpen] = useState(() => Boolean(question.trim()));
  const selectedSignalRef = useRef<string | null>(null);
  const signalIdsRef = useRef("");

  const current = signals[deck.index] ?? null;
  const currentCopy = current ? splitLead(current.body) : null;
  const currentSources = current ? sourceSummary(current.sourceIds, sourceLabels) : null;
  const signalIds = signals.map((signal) => signal.id).join("\u0000");

  useEffect(() => {
    if (signalIdsRef.current && signalIdsRef.current !== signalIds) {
      const selectedIndex = selectedSignalRef.current
        ? signals.findIndex((signal) => signal.id === selectedSignalRef.current)
        : -1;
      if (selectedIndex >= 0) deck.go(selectedIndex);
      else {
        selectedSignalRef.current = signals[0]?.id ?? null;
        deck.go(0);
      }
    }
    signalIdsRef.current = signalIds;
  }, [deck.go, signalIds, signals]);

  useEffect(() => {
    selectedSignalRef.current = signals[deck.index]?.id ?? null;
    // 신호 목록이 갱신된 경우는 위 효과가 기존 ID를 먼저 복원한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deck.index]);

  useEffect(() => {
    if (!exploreOpen && briefing.nextOffset !== null && deck.index >= signals.length - 1 && !loadingMore && !loadMoreError) onLoadMore?.();
  }, [briefing.nextOffset, deck.index, exploreOpen, loadMoreError, loadingMore, onLoadMore, signals.length]);

  return (
    <div className={styles.screen}>
      {/* 요청 막대 — 지켜볼 것을 거는 자리가 항상 상단에 있다 */}
      <div className={styles.reqBar}>
        <p className={styles.date}>오늘의 브리핑 · {briefing.dateLabel}</p>
        {signals.length > 0 && briefing.requestCount > 0 ? (
          <span className={styles.reqCount}>내 요청 {briefing.requestCount}건 반영</span>
        ) : null}
        {signals.length > 0 ? (
          <button
            type="button"
            className={styles.addReq}
            onClick={() => setExploreOpen(true)}
            aria-expanded={exploreOpen}
            aria-controls="briefing-request"
          >
            ＋ 새 시그널 찾기
          </button>
        ) : null}
      </div>

      {loading ? (
        <article className={styles.briefingState} role="status">
          <span className={styles.statePulse} aria-hidden="true" />
          <div>
            <b>지켜보는 변화를 모으고 있어요</b>
            <p>지켜보는 변화의 최근 수치와 흐름을 불러옵니다.</p>
          </div>
        </article>
      ) : error ? (
        <article className={styles.briefingState} role="alert" data-error="true">
          <div>
            <b>브리핑을 불러오지 못했어요</b>
            <p>{error}</p>
          </div>
          {onRetry ? <button type="button" onClick={onRetry}>다시 불러오기</button> : null}
        </article>
      ) : null}

      {/* 브리핑 조회 상태와 무관하게 첫 시그널을 요청할 수 있어야 한다. */}
      {!loading && !error && current ? (
        <>
          <h1 className={styles.lede}>
            <Highlight text={briefing.lede} />
          </h1>

          {exploreOpen ? (
            <article id="briefing-request" className={styles.requestWorkspace} aria-label="새 시그널 찾기">
              <AskScreen
                mode="briefing-request"
                question={question}
                onQuestionChange={onQuestionChange}
                onSubmit={(conditions) => onAsk(question, conditions)}
                notice={notice}
                suggestedQuestions={suggestedQuestions}
                sourceCount={sourceCount}
                fixedPeriodLabel={fixedPeriodLabel}
                conditionsLocked={conditionsLocked}
                periodLocked={periodLocked}
                sourceOptions={sourceOptions}
                initialStartAt={initialStartAt}
                initialEndAt={initialEndAt}
              />
            </article>
          ) : (
          <>
          <div
            className={styles.deck}
            tabIndex={0}
            role="group"
            aria-label="오늘의 브리핑"
            onKeyDown={(event) => {
              if (event.key === "ArrowRight") {
                event.preventDefault();
                deck.step(1);
              }
              if (event.key === "ArrowLeft") {
                event.preventDefault();
                deck.step(-1);
              }
            }}
            {...deck.handlers}
          >
          <article
            key={current.id}
            className={styles.card}
            style={deck.cardStyle}
            data-drag={deck.dragging ? "1" : undefined}
            data-from={deck.from ?? undefined}
            aria-live="polite"
          >
            <p className={styles.kicker}>
              브리핑 {deck.index + 1}
              {current.fromRequest ? (
                <span className={styles.fromReq}>◆ 내 요청으로 잡음</span>
              ) : null}
              <span className={styles.count}>
                {deck.index + 1} / {briefing.total}
              </span>
            </p>
            <h2 className={styles.headline}>
              <Highlight text={current.headline} />
            </h2>
            <p className={styles.body}>{currentCopy?.lead}</p>
            {currentCopy?.detail ? (
              <details className={styles.bodyDetails}>
                <summary>분석 내용 자세히 <span aria-hidden="true">⌄</span></summary>
                <p>{currentCopy.detail}</p>
              </details>
            ) : null}
            {current.periodLabel ? <p className={styles.period}><b>관측 기간</b>{current.periodLabel}</p> : null}
            {current.limitation ? <p className={styles.cardNote}><b>측정 참고</b>{current.limitation}</p> : null}

            <div className={styles.row}>
              <div className={styles.metricGroup}>
                <p className={styles.sectionLabel}>주요 지표</p>
                {current.metrics.length ? (
                  <ul className={styles.metrics}>
                    {current.metrics.map((metric) => (
                      <li key={metric.label}>
                        <span className={styles.metricLabel}>{metric.label}</span>
                        <span className={styles.metricValue}>{metric.value}</span>
                        <span className={styles.metricDelta} data-dir={metric.direction}>
                          {metric.direction === "up" ? "이전 측정 대비 ▲ " : metric.direction === "down" ? "이전 측정 대비 ▼ " : ""}
                          {metric.delta}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className={styles.metricEmpty}>비교할 첫 측정값을 준비하고 있어요.</p>
                )}
              </div>
              {current.trend.length >= 2 ? (
                <div className={styles.trend}>
                  <p className={styles.sectionLabel}>최근 흐름</p>
                  <svg
                    className={styles.spark}
                    viewBox="0 0 200 38"
                    preserveAspectRatio="none"
                    aria-hidden="true"
                  >
                    <path className={styles.sparkSoft} d="M0 21 L200 21" />
                    <path d={sparkPath(current.trend)} />
                  </svg>
                </div>
              ) : null}
            </div>

            <div className={styles.signalMeta}>
              <span><b>분석 기준</b>{current.evidenceNote}</span>
              {currentSources ? <span><b>확인한 데이터</b>{currentSources}</span> : null}
            </div>
            <div className={styles.acts}>
              <button type="button" className={styles.btn} onClick={() => onOpenSignal(current)}>
                시그널 상세 보기
              </button>
              <button type="button" className={styles.ghost} onClick={() => loadMoreError ? onLoadMore?.() : deck.step(1)}>
                {loadingMore ? "다음 시그널 불러오는 중…" : loadMoreError ? "다음 시그널 다시 불러오기" : "다음 시그널"}
              </button>
            </div>
          </article>
          </div>

          <p className={styles.swipeHint} data-off={deck.touched ? "1" : undefined}>
            <i aria-hidden="true">‹</i> 좌우로 드래그해 넘겨보세요 <i aria-hidden="true">›</i>
          </p>
          </>
          )}

          <div className={styles.rest} aria-label="브리핑 목록">
            {signals.map((signal, i) => (
              <button
                key={signal.id}
                type="button"
                className={styles.chip}
                data-cur={!exploreOpen && deck.index === i ? "1" : undefined}
                aria-current={!exploreOpen && deck.index === i ? "true" : undefined}
                onClick={() => {
                  setExploreOpen(false);
                  deck.go(i);
                }}
              >
                {i + 1} · {signal.chipLabel}
              </button>
            ))}
            <button
              type="button"
              className={`${styles.chip} ${styles.chipAdd}`}
              data-cur={exploreOpen ? "1" : undefined}
              aria-current={exploreOpen ? "true" : undefined}
              onClick={() => setExploreOpen(true)}
            >
              ＋ 새 시그널 찾기
            </button>
          </div>
        </>
      ) : signals.length === 0 ? (
        <article className={styles.emptyBriefing} aria-label="브리핑 없음">
          {!loading && !error ? (
            <div className={styles.emptyStatus}>
              <span className={styles.emptyPulse} aria-hidden="true" />
              <p>
                <b>오늘 먼저 알려드릴 변화는 없어요.</b>
                <span>브리핑을 기다리지 않고 직접 찾아볼 수 있어요.</span>
              </p>
            </div>
          ) : null}
          <AskScreen
            mode={loading || error ? "briefing-request" : "empty-briefing"}
            question={question}
            onQuestionChange={onQuestionChange}
            onSubmit={(conditions) => onAsk(question, conditions)}
            notice={notice}
            suggestedQuestions={suggestedQuestions}
            sourceCount={sourceCount}
            fixedPeriodLabel={fixedPeriodLabel}
            conditionsLocked={conditionsLocked}
            periodLocked={periodLocked}
            sourceOptions={sourceOptions}
            initialStartAt={initialStartAt}
            initialEndAt={initialEndAt}
          />
        </article>
      ) : null}

      {signals.length > 0 ? (
        <div className={styles.foot}>
          <span>
            캐치 중 {briefing.watchingCount}건
            {briefing.pastDates.length ? (
              <>
                {" · 최근 측정 "}
                {briefing.pastDates.map((date) => (
                  <span key={date} className={styles.mono}>{date}</span>
                ))}
              </>
            ) : null}
          </span>
        </div>
      ) : null}
    </div>
  );
}
