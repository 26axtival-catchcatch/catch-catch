"use client";

import { useEffect, useRef, useState } from "react";

import { Overlay } from "../Overlay";
import type { ClarificationPrompt } from "../state/types";

import styles from "./catching.module.css";

const TYPE_MS = 32;

interface ClarificationModalProps {
  prompt: ClarificationPrompt;
  onAnswer: (answer: string) => void;
}

/** 분석 기준이 모호할 때 결과를 추측하지 않고 사용자에게 한 번 더 확인한다. */
export function ClarificationModal({ prompt, onAnswer }: ClarificationModalProps) {
  const [typed, setTyped] = useState("");
  const [answer, setAnswer] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (typed.length >= prompt.question.length) {
      inputRef.current?.focus();
      return;
    }
    const timer = setTimeout(
      () => setTyped(prompt.question.slice(0, typed.length + 1)),
      TYPE_MS,
    );
    return () => clearTimeout(timer);
  }, [typed, prompt.question]);

  // 백엔드가 답을 기다리는 중이라 닫기 없이 focus 만 가둔다.
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Tab") return;
      const focusable = dialogRef.current?.querySelectorAll<HTMLElement>("input, button");
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
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const done = typed.length >= prompt.question.length;
  const quickOptions =
    prompt.question.includes("검색") && prompt.question.includes("비교")
      ? ["검색 이력만 분석해 주세요", "상품 비교 행동도 함께 분석해 주세요"]
      : [];

  return (
    <Overlay>
      <div className={styles.scrim}>
        <div
          className={styles.modal}
          ref={dialogRef}
          role="dialog"
          aria-modal="true"
          aria-label="분석 범위 추가 확인"
        >
          <p className={styles.modalTag}>분석 기준 확인</p>
          <h2 className={styles.modalTitle}>정확한 분석을 위해 한 가지만 확인할게요</h2>

          <p className={styles.modalQuestion}>
            {typed}
            {done ? null : <i className={styles.block} />}
          </p>

          {done ? <p className={styles.modalHint}>{prompt.hint}</p> : null}

          <form
            className={styles.modalForm}
            onSubmit={(event) => {
              event.preventDefault();
              if (!answer.trim()) return;
              onAnswer(answer.trim());
            }}
          >
            <span className={styles.prompt} aria-hidden="true">
              &gt;
            </span>
            <input
              ref={inputRef}
              className={styles.modalInput}
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
              placeholder="원하는 분석 범위를 입력해 주세요"
              aria-label="추가 조건 답변"
            />
            <button type="submit" className={styles.modalGo} disabled={!answer.trim()}>
              답변하고 계속
            </button>
          </form>

          {quickOptions.length > 0 ? (
            <div className={styles.quick}>
              {quickOptions.map((option) => (
                <button key={option} type="button" onClick={() => onAnswer(option)}>
                  {option}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </Overlay>
  );
}
