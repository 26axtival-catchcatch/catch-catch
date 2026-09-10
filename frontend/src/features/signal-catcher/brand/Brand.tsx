"use client";

import type { Stage } from "../state/types";

import styles from "./brand.module.css";

interface SignalMarkProps {
  size?: number;
  title?: string;
}

/** 돋보기 렌즈 안에 시그널 파형이 들어간 서비스 마크. */
export function SignalMark({ size = 26, title }: SignalMarkProps) {
  return (
    <svg
      className={styles.mark}
      width={size}
      height={size}
      viewBox="0 0 28 28"
      role={title ? "img" : "presentation"}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      <circle className={styles.lens} cx="12" cy="12" r="8.4" />
      <path className={styles.wave} d="M7.4 12h2l1.2-3.1 1.9 6.1 1.4-3h2.7" />
      <path className={styles.handle} d="M18.3 18.3 24 24" />
      <path
        className={styles.spark}
        d="M22.6 8C19.3 5.8 18.6 5 18.6 4c0-1.1.9-1.8 1.8-1.8.8 0 1.7.5 2.2 1.4.5-.9 1.4-1.4 2.2-1.4.9 0 1.8.7 1.8 1.8 0 1-.7 1.8-4 4Z"
      />
    </svg>
  );
}

/**
 * AI 가 만든 것임을 표시하는 스파클.
 * SaaS 관습대로 AI 산출물과 AI 실행 버튼에만 쓴다. 다른 곳에 붙이면 의미가 흐려진다.
 */
export function Sparkle({ size = 16 }: { size?: number }) {
  return (
    <svg
      className={styles.sparkle}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path d="M12 2.5 13.9 8.6 20 10.5 13.9 12.4 12 18.5 10.1 12.4 4 10.5 10.1 8.6Z" />
      <path d="M18.5 15.5 19.4 18.1 22 19 19.4 19.9 18.5 22.5 17.6 19.9 15 19 17.6 18.1Z" />
    </svg>
  );
}

const BEAT_W = 200;
const BASE_Y = 30;

/** 단계 하나에 박동 하나. 다섯 개가 이어져 하나의 심박 라인이 된다. */
function beatPath(index: number): string {
  const x = index * BEAT_W;
  return [
    `M${x} ${BASE_Y}`,
    `H${x + 56}`,
    "l7 -4 l6 4",
    `H${x + 86}`,
    "l7 -19 l11 36 l9 -23 l7 6",
    `H${x + 142}`,
    "l8 -4 l7 4",
    `H${x + BEAT_W}`,
  ].join(" ");
}

interface SignalProgressProps {
  stages: Stage[];
  /** 진행 중인 박동이 그려지는 데 걸리는 시간. */
  activeDurationMs: number;
  /** 대기나 실패로 진행이 멎은 상태. 그리던 자리에서 선다. */
  halted: boolean;
}

/**
 * 진행률이 곧 심박이다.
 * 막대를 채우는 대신 단계마다 박동 하나씩을 그려 나가, 브랜드 파형이
 * 화면에서 이 한 곳으로 모인다.
 */
export function SignalProgress({ stages, activeDurationMs, halted }: SignalProgressProps) {
  return (
    <span className={styles.progress} data-halted={halted} aria-hidden="true">
      <svg viewBox={`0 0 ${stages.length * BEAT_W} 60`} preserveAspectRatio="none">
        <path className={styles.progressGhost} d={`M0 ${BASE_Y} H${stages.length * BEAT_W}`} />
        {stages.map((stage, index) => (
          <path
            key={stage.key}
            className={styles.progressSeg}
            data-status={stage.status}
            d={beatPath(index)}
            pathLength={100}
            strokeDasharray={100}
            strokeDashoffset={stage.status === "done" ? 0 : 100}
            style={{ "--dur": `${activeDurationMs}ms` } as React.CSSProperties}
          />
        ))}
      </svg>
    </span>
  );
}

const HEART_PATH =
  "M50 86C24 68 8 52 8 34.5 8 21.5 18 12 30 12c8 0 15 4.4 20 12 5-7.6 12-12 20-12 12 0 22 9.5 22 22.5C92 52 76 68 50 86Z";

/** 시그널을 찾은 순간의 심쿵 연출. 마젠타가 한 번 화면을 덮고 마크가 번지며 사라진다. */
export function HeartBurst({ mark = "heart" }: { mark?: "heart" | "lens" }) {
  return (
    <div className={styles.burst} aria-hidden="true">
      <div className={styles.burstFlash} />
      <svg viewBox="0 0 100 100">
        {mark === "heart" ? (
          <path className={styles.burstHeart} d={HEART_PATH} />
        ) : (
          <g className={styles.burstHeart} data-lens="true">
            <circle cx="43" cy="43" r="30" />
            <path d="M64 64 L84 84" />
          </g>
        )}
      </svg>
      <p className={styles.burstWord}>찾았다!</p>
    </div>
  );
}
