"use client";

import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { SignalMark } from "../brand/Brand";

import { useSwipeDeck } from "./use-swipe-deck";
import type { Briefing, BriefingSignal } from "./types";
import styles from "./briefing.module.css";

interface BriefingScreenProps {
  briefing: Briefing;
  /** 카드의 "이 시그널 확인하기". 그 시그널의 리포트로 넘어간다. */
  onOpenSignal: (signal: BriefingSignal) => void;
  /** "비슷한 걸 더 찾기"와 마지막 장의 입력. 지금 바로 훑어 본다. */
  onAsk: (question: string) => void;
  /** 상단 "＋ 지켜볼 것 요청하기". 다음 브리핑부터 반영되는 요청을 건다. */
  onRequestWatch: (request: string) => void;
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

interface AskRowProps {
  placeholder: string;
  submitLabel: string;
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  autoFocus?: boolean;
  /** Esc 로 닫는다. 열어 둔 자리를 키보드만으로 되돌릴 수 있어야 한다. */
  onCancel: () => void;
}

/** 요청/추가 질문이 쓰는 한 줄 입력. 두 자리가 같은 모양을 쓴다. */
function AskRow({
  placeholder,
  submitLabel,
  value,
  onChange,
  onSubmit,
  autoFocus,
  onCancel,
}: AskRowProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
  }, [autoFocus]);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!value.trim()) return;
    onSubmit();
  }

  return (
    <form
      className={styles.askRow}
      onSubmit={submit}
      onKeyDown={(event) => {
        if (event.key === "Escape") onCancel();
      }}
    >
      <span className={styles.askIcon} aria-hidden="true">⌕</span>
      <input
        ref={inputRef}
        className={styles.askInput}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
      />
      <button type="submit" className={styles.askSubmit} disabled={!value.trim()}>
        {submitLabel}
      </button>
    </form>
  );
}

export function BriefingScreen({
  briefing,
  onOpenSignal,
  onAsk,
  onRequestWatch,
}: BriefingScreenProps) {
  const { signals } = briefing;
  // 시그널 뒤에 "더 찾기" 한 장을 붙여 브리핑의 끝을 빈 화면으로 두지 않는다
  const total = signals.length + 1;
  const deck = useSwipeDeck(total);

  const [talkOpen, setTalkOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [askText, setAskText] = useState("");
  const [requestText, setRequestText] = useState("");
  /** 방금 건 요청. 접수됐다는 것을 화면에서 바로 돌려준다. */
  const [justRequested, setJustRequested] = useState<string | null>(null);
  const talkRef = useRef<HTMLDivElement>(null);
  const sheetRef = useRef<HTMLDivElement>(null);

  const current = deck.index < signals.length ? signals[deck.index] : null;

  function openTalk() {
    setTalkOpen(true);
    // 화면을 넘기지 않고 아래에 대화가 이어붙는다
    requestAnimationFrame(() =>
      talkRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }),
    );
  }

  function toggleSheet() {
    setSheetOpen((open) => {
      if (open) return false;
      requestAnimationFrame(() =>
        sheetRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" }),
      );
      return true;
    });
  }

  function submitAsk() {
    onAsk(askText.trim());
    setAskText("");
  }

  function submitRequest() {
    const request = requestText.trim();
    onRequestWatch(request);
    setJustRequested(request);
    setRequestText("");
    setSheetOpen(false);
  }

  return (
    <div className={styles.screen}>
      {/* 요청 막대 — 지켜볼 것을 거는 자리가 항상 상단에 있다 */}
      <div className={styles.reqBar}>
        <p className={styles.date}>오늘의 브리핑 · {briefing.dateLabel}</p>
        {briefing.requestCount > 0 ? (
          <span className={styles.reqCount}>내 요청 {briefing.requestCount}건 반영</span>
        ) : null}
        <button
          type="button"
          className={styles.addReq}
          onClick={toggleSheet}
          aria-expanded={sheetOpen}
        >
          ＋ 지켜볼 것 요청하기
        </button>
      </div>

      <p className={styles.lede}>
        <Highlight text={briefing.lede} />
      </p>

      <div
        className={styles.deck}
        tabIndex={0}
        role="group"
        aria-label="오늘의 시그널"
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
        {current ? (
          <article
            key={current.id}
            className={styles.card}
            style={deck.cardStyle}
            data-drag={deck.dragging ? "1" : undefined}
            data-from={deck.from ?? undefined}
          >
            <p className={styles.kicker}>
              시그널 {deck.index + 1} · {current.name}
              {current.fromRequest ? (
                <span className={styles.fromReq}>◆ 내 요청으로 잡음</span>
              ) : null}
              <span className={styles.count}>
                {deck.index + 1} / {total}
              </span>
            </p>
            <h2 className={styles.headline}>
              <Highlight text={current.headline} />
            </h2>
            <p className={styles.body}>{current.body}</p>

            <div className={styles.row}>
              <ul className={styles.metrics}>
                {current.metrics.map((metric) => (
                  <li key={metric.label}>
                    <span className={styles.metricLabel}>{metric.label}</span>
                    <span className={styles.metricValue}>{metric.value}</span>
                    <span className={styles.metricDelta} data-dir={metric.direction}>
                      {metric.direction === "up" ? "▲" : "▼"} {metric.delta}
                    </span>
                  </li>
                ))}
              </ul>
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

            <div className={styles.acts}>
              <button type="button" className={styles.btn} onClick={() => onOpenSignal(current)}>
                이 시그널 확인하기
              </button>
              <button type="button" className={styles.more} onClick={openTalk}>
                비슷한 걸 더 찾기
              </button>
              <button type="button" className={styles.ghost} onClick={() => deck.step(1)}>
                넘기기
              </button>
              <span className={styles.hint}>{current.evidenceNote}</span>
            </div>
          </article>
        ) : (
          <article
            key="last"
            className={`${styles.card} ${styles.last}`}
            style={deck.cardStyle}
            data-drag={deck.dragging ? "1" : undefined}
            data-from={deck.from ?? undefined}
          >
            <p className={styles.kicker}>
              오늘 브리핑 끝
              <span className={styles.count}>
                {total} / {total}
              </span>
            </p>
            <h2 className={styles.headline}>
              오늘 잡은 건 여기까지예요. <b>더 찾아볼까요?</b>
            </h2>
            <p className={styles.body}>
              말씀해 주시면 그 구간을 훑어서 시그널이 될 만한 것을 찾고, 바로 와쳐를 걸 수 있게
              정리해 드립니다.
            </p>
            <button type="button" className={styles.openAsk} onClick={openTalk}>
              <span className={styles.askIcon} aria-hidden="true">⌕</span>
              <span className={styles.openAskText}>{briefing.askPlaceholder}</span>
            </button>
            <p className={styles.backlog}>
              지난 브리핑에서 넘긴 것 {briefing.backlogCount}건 · 관찰 중인 실험{" "}
              {briefing.watchingCount}건
            </p>
          </article>
        )}
      </div>

      <p className={styles.swipeHint} data-off={deck.touched ? "1" : undefined}>
        <i aria-hidden="true">‹</i> 좌우로 드래그해 넘겨보세요 <i aria-hidden="true">›</i>
      </p>

      <div className={styles.rest}>
        {signals.map((signal, i) => (
          <button
            key={signal.id}
            type="button"
            className={styles.chip}
            data-cur={deck.index === i ? "1" : undefined}
            aria-current={deck.index === i}
            onClick={() => deck.go(i)}
          >
            {i + 1} · {signal.chipLabel}
          </button>
        ))}
        <button
          type="button"
          className={`${styles.chip} ${styles.chipAdd}`}
          data-cur={deck.index === signals.length ? "1" : undefined}
          aria-current={deck.index === signals.length}
          onClick={() => deck.go(signals.length)}
        >
          ⊕ 더 찾기
        </button>
      </div>

      {/* 지켜볼 것 요청 — 다음 브리핑에 반영된다 */}
      {sheetOpen ? (
        <div className={styles.sheet} ref={sheetRef}>
          <p className={styles.sheetTitle}>무엇을 지켜볼까요 — 다음 브리핑부터 반영됩니다</p>
          <AskRow
            placeholder={briefing.askPlaceholder}
            submitLabel="요청 추가"
            value={requestText}
            onChange={setRequestText}
            onSubmit={submitRequest}
            onCancel={() => setSheetOpen(false)}
            autoFocus
          />
          <ul className={styles.suggestions}>
            {briefing.suggestions.map((item) => (
              <li key={item}>
                <button type="button" onClick={() => setRequestText(item)}>
                  {item}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {!sheetOpen && justRequested ? (
        <p className={styles.requested} role="status">
          <b>“{justRequested}”</b> 를 지켜보기로 했어요. 다음 브리핑부터 반영됩니다.
        </p>
      ) : null}

      {/* 지금 더 찾기 — 화면을 넘기지 않고 대화가 이어붙는다 */}
      {talkOpen ? (
        <div className={styles.talk} ref={talkRef}>
          <div className={styles.bubble}>
            <span className={styles.avatar}>
              <SignalMark size={12} />
            </span>
            <p>무엇을 지켜볼까요? 구간이나 상황을 말해 주시면 그 자리에 와쳐를 겁니다.</p>
          </div>
          <AskRow
            placeholder={briefing.askPlaceholder}
            submitLabel="추적 시작"
            value={askText}
            onChange={setAskText}
            onSubmit={submitAsk}
            onCancel={() => setTalkOpen(false)}
            autoFocus
          />
          <ul className={styles.suggestions} data-indent="1">
            {briefing.suggestions.map((item) => (
              <li key={item}>
                <button type="button" onClick={() => setAskText(item)}>
                  {item}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className={styles.foot}>
        <span>
          관찰 중인 실험 {briefing.watchingCount}건 · 지난 브리핑{" "}
          {briefing.pastDates.map((date) => (
            <span key={date} className={styles.mono}>
              {date}
            </span>
          ))}
        </span>
      </div>
    </div>
  );
}
