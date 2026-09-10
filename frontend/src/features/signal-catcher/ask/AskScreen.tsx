"use client";

import { useEffect, useRef, useState } from "react";

import type { SourceId } from "../../customer-intelligence/contracts";
import { PLACEHOLDER_QUESTIONS, SOURCE_OPTIONS, SUGGESTIONS } from "../state/mock";
import type { SourceOption } from "../state/types";

import { ComposerMenu, PERIOD_CHOICES, isRequiredSource, type PeriodChoice } from "./ComposerMenu";
import { TypewriterPlaceholder } from "./TypewriterPlaceholder";
import styles from "./ask.module.css";

/** 시그널이 입력창으로 빨려 들어가는 시간. 전환은 그 뒤에 시작한다. */
const SEND_MS = 420;

/** 입력이 멎으면 파형도 가라앉는다. */
const IDLE_MS = 1400;

/*
 * 입력창 바깥 좌우로 흐르는 시그널.
 * 두 칸이 같은 파형을 쓰고 마스크 방향만 반대라, 하나의 신호가
 * 입력창을 지나가는 것처럼 보인다.
 */
const FLOW_PATH =
  "M0 30 H34 l5 -6 l4 6 H60 l5 -22 l8 42 l6 -27 l5 7 H110 l6 -6 l5 6 H200 " +
  "H234 l5 -6 l4 6 H260 l5 -22 l8 42 l6 -27 l5 7 H310 l6 -6 l5 6 H400";

function SignalFlow({ side }: { side: "left" | "right" }) {
  return (
    <span className={styles.wave} data-side={side} aria-hidden="true">
      <svg viewBox="0 0 400 60" preserveAspectRatio="none">
        <path d={FLOW_PATH} />
      </svg>
    </span>
  );
}

export interface AskConditions {
  enabledSources: SourceId[];
  startAt: string;
  endAt: string;
}

interface AskScreenProps {
  question: string;
  onQuestionChange: (value: string) => void;
  onSubmit: (conditions: AskConditions) => void;
  /** unsupported_analysis 또는 실패로 되돌아왔을 때의 안내 문구. */
  notice: string | null;
  /** 되돌아왔을 때 백엔드가 준 대안 질문. 있으면 제안 카드를 대체한다. */
  suggestedQuestions: string[];
  /** 브리핑이 비었을 때 스티치 카드 안에 같은 입력 경험을 넣는다. */
  mode?: "standalone" | "empty-briefing";
  /** 라이브 Run은 핸드오프의 고정 주간과 서버 등록 Source 전체를 사용한다. */
  sourceCount?: number | null;
  fixedPeriodLabel?: string;
  conditionsLocked?: boolean;
  periodLocked?: boolean;
  sourceOptions?: readonly SourceOption[];
  initialStartAt?: string;
  initialEndAt?: string;
}

export function AskScreen({
  question,
  onQuestionChange,
  onSubmit,
  notice,
  suggestedQuestions,
  mode = "standalone",
  sourceCount,
  fixedPeriodLabel,
  conditionsLocked = false,
  periodLocked = false,
  sourceOptions,
  initialStartAt,
  initialEndAt,
}: AskScreenProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [typing, setTyping] = useState(false);
  const [sending, setSending] = useState(false);
  const displayedSources = sourceOptions ?? SOURCE_OPTIONS;
  const [sources, setSources] = useState<SourceId[]>(() =>
    displayedSources.map((item) => item.id),
  );
  const [period, setPeriod] = useState<PeriodChoice>(() =>
    initialStartAt && initialEndAt
      ? {
          key: "api-default",
          label: fixedPeriodLabel ?? `${initialStartAt} – ${initialEndAt}`,
          startAt: initialStartAt,
          endAt: initialEndAt,
        }
      : PERIOD_CHOICES[1],
  );
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!sourceOptions) return;
    const available = new Set(sourceOptions.map((item) => item.id));
    setSources((current) => {
      const retained = current.filter((id) => available.has(id));
      return retained.length ? retained : sourceOptions.map((item) => item.id);
    });
  }, [sourceOptions]);

  useEffect(() => {
    if (!initialStartAt || !initialEndAt) return;
    setPeriod((current) =>
      current.startAt === initialStartAt && current.endAt === initialEndAt
        ? current
        : {
            key: "api-default",
            label: fixedPeriodLabel ?? `${initialStartAt} – ${initialEndAt}`,
            startAt: initialStartAt,
            endAt: initialEndAt,
          },
    );
  }, [fixedPeriodLabel, initialEndAt, initialStartAt]);

  useEffect(() => {
    const node = inputRef.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${node.scrollHeight}px`;
  }, [question]);

  // 입력이 이어지는 동안만 파형의 진폭을 키운다.
  useEffect(() => {
    if (!question) {
      setTyping(false);
      return;
    }
    setTyping(true);
    const id = window.setTimeout(() => setTyping(false), IDLE_MS);
    return () => window.clearTimeout(id);
  }, [question]);

  function toggleSource(id: SourceId) {
    if (isRequiredSource(id)) return;
    setSources((prev) => (prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]));
  }

  function submit() {
    if (!question.trim()) {
      inputRef.current?.focus();
      return;
    }
    if (sending) return;

    // 파형이 입력창으로 빨려 들어간 뒤에 화면을 넘긴다.
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      onSubmit({
        enabledSources: sources,
        startAt: period.startAt,
        endAt: period.endAt,
      });
      return;
    }
    setTyping(false);
    setSending(true);
    window.setTimeout(() => onSubmit({
      enabledSources: sources,
      startAt: period.startAt,
      endAt: period.endAt,
    }), SEND_MS);
  }

  const cards = suggestedQuestions.length
    ? suggestedQuestions.map((text) => ({ persona: "추천", label: text, question: text }))
    : SUGGESTIONS.map((item) => ({ ...item }));

  return (
    <div className={styles.screen} data-mode={mode}>
      <div className={styles.center}>
        <p className={styles.kicker}>
          {mode === "empty-briefing"
            ? "아직 도착한 브리핑이 없어요"
            : "고객은 말보다 먼저 신호를 보냅니다"}
        </p>
        <h1 className={styles.title}>
          {mode === "empty-briefing"
            ? "지금 궁금한 고객의 신호를 찾아볼까요?"
            : "고객의 시그널을 찾아보세요"}
        </h1>

        {notice ? (
          <div className={styles.notice} role="status">
            <p>{notice}</p>
          </div>
        ) : null}

        <div className={styles.composerWrap}>
          <div className={styles.tokens}>
            <span className={styles.token}>
              데이터셋 {sourceCount === null && !sources.length ? "확인 중" : sources.length}
            </span>
            <span className={styles.token}>{fixedPeriodLabel ?? period.label}</span>
          </div>

          <div
            className={styles.signalRow}
            data-typing={typing}
            data-sending={sending}
          >
            <SignalFlow side="left" />

            <form
              className={styles.composer}
              onSubmit={(event) => {
                event.preventDefault();
                submit();
              }}
            >
              <button
                type="button"
                className={styles.plus}
                aria-label={conditionsLocked ? "분석 조건은 시연 기준으로 고정됨" : "분석 조건 추가"}
                aria-expanded={menuOpen}
                disabled={conditionsLocked}
                onClick={() => setMenuOpen((prev) => !prev)}
              >
                +
              </button>

              <div className={styles.field}>
                <label className={styles.srOnly} htmlFor="catch-question">
                  분석 질문
                </label>
                <textarea
                  id="catch-question"
                  ref={inputRef}
                  rows={1}
                  value={question}
                  onChange={(event) => onQuestionChange(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      submit();
                    }
                  }}
                />
                <TypewriterPlaceholder phrases={PLACEHOLDER_QUESTIONS} paused={question.length > 0} />
              </div>

              <button type="submit" className={styles.go} aria-label="시그널 캐치하기">
                <svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true">
                  <circle cx="8.6" cy="8.6" r="6" fill="none" stroke="currentColor" strokeWidth="2" />
                  <path
                    d="M13.2 13.2 17.4 17.4"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.4"
                    strokeLinecap="round"
                  />
                </svg>
              </button>

              {menuOpen && !conditionsLocked ? (
                <ComposerMenu
                  sources={displayedSources}
                  selected={sources}
                  period={period}
                  onToggleSource={toggleSource}
                  onSelectPeriod={setPeriod}
                  periodLocked={periodLocked}
                  onClose={() => setMenuOpen(false)}
                />
              ) : null}
            </form>

            <SignalFlow side="right" />
          </div>
        </div>

        <ul className={styles.cards} aria-label="이런 질문은 어때요">
          {cards.map((card) => (
            <li key={card.question}>
              <button
                type="button"
                className={styles.card}
                onClick={() => {
                  onQuestionChange(card.question);
                  inputRef.current?.focus();
                }}
              >
                <span className={styles.cardTag}>{card.persona}</span>
                <span className={styles.cardLabel}>{card.label}</span>
                {card.question === card.label ? null : (
                  <span className={styles.cardQuestion}>{card.question}</span>
                )}
                <span className={styles.cardArrow} aria-hidden="true">
                  ↗
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
