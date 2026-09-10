"use client";

import { HeartBurst, SignalProgress } from "../brand/Brand";
import { markOf } from "../state/tick-marks";
import { STAGE_DURATIONS } from "../state/use-catch-session";
import type { CatchSession, StageKey, StageTick } from "../state/types";

import { ClarificationModal } from "./ClarificationModal";
import styles from "./catching.module.css";

/**
 * 레일에 남겨 둘 최근 진행 문장 수.
 * 위쪽 줄은 마스크로 흐려지며 사라지므로 실제로 읽히는 건 아래 서너 줄이다.
 */
const RAIL_WINDOW = 9;

interface CatchingScreenProps {
  session: CatchSession;
  bursting: boolean;
  flatline: boolean;
  burstMark: "heart" | "lens";
  /** 진행 속도 배수. 심박이 그려지는 시간도 같이 늘어난다. */
  speed: number;
  log: (StageTick & { stage: StageKey })[];
  onAnswerClarification: (answer: string) => void;
  onRetry: () => void;
  onGiveUp: () => void;
}

export function CatchingScreen({
  session,
  bursting,
  flatline,
  burstMark,
  speed,
  log,
  onAnswerClarification,
  onRetry,
  onGiveUp,
}: CatchingScreenProps) {
  const failed = session.outcome === "failed";
  const halted = flatline || failed || Boolean(session.clarification);
  const activeIndex = session.stages.findIndex((stage) => stage.status === "active");
  const active = activeIndex < 0 ? null : session.stages[activeIndex];
  const recent = log.slice(-RAIL_WINDOW);

  const tools = log.filter((entry) => entry.kind === "tool").length;
  const catches = log.filter((entry) => entry.kind === "fact").length;

  const lead = flatline
    ? "신호가 끊겼어요"
    : session.clarification
      ? "조금만 더 알려주세요"
      : (active?.label ?? "신호를 잡는 중");

  return (
    <div className={styles.screen}>
      {bursting ? <HeartBurst mark={burstMark} /> : null}

      <p className={styles.context}>{session.question}</p>

      <div className={styles.stage}>
        {failed ? (
          <div className={styles.failure} role="alert">
            <p className={styles.failureTitle}>
              <span className={styles.failureBadge}>연결 끊김</span>
              신호가 끊겼어요
            </p>
            <p className={styles.failureReason}>{session.failureReason}</p>
            <p className={styles.failureNote}>
              질문과 조건은 그대로 두었어요. 다시 캐치하면 멈춘 지점부터 이어서 분석합니다.
            </p>
            <div className={styles.failureActions}>
              <button type="button" className={styles.failureRetry} onClick={onRetry}>
                다시 캐치하기
              </button>
              <button type="button" className={styles.failureGhost} onClick={onGiveUp}>
                질문 바꾸기
              </button>
            </div>
          </div>
        ) : bursting ? null : (
          <div className={styles.panel}>
            {/*
              같은 정보를 두 번 쓰지 않는다.
              현재 단계는 여기 한 줄에만 두고, 레일 안에는 단계 이름을 적지 않는다.
            */}
            <div className={styles.head}>
              <div className={styles.headTop}>
                {halted || activeIndex < 0 ? null : (
                  <>
                    <span className={styles.badge}>
                      {active?.short}
                      <b>
                        {activeIndex + 1}/{session.stages.length}
                      </b>
                    </span>
                    {/* 다섯 칸 중 어디쯤인지. 막대 대신 박동이 하나씩 그려진다. */}
                    <SignalProgress
                      stages={session.stages}
                      activeDurationMs={
                        (active ? STAGE_DURATIONS[active.key] : 1200) * speed
                      }
                      halted={halted}
                    />
                  </>
                )}
                <span className={styles.count}>
                  도구 {tools} · <b>포착 {catches}</b>
                </span>
              </div>
              <p className={styles.lead} data-halted={halted}>
                {halted ? null : <span className={styles.spin} aria-hidden="true" />}
                {lead}
              </p>
            </div>

            <div className={styles.railViewport}>
              <ol className={styles.rail} aria-live="polite">
                {recent.map((entry, index) => {
                  const now = index === recent.length - 1;
                  return (
                    <li
                      key={entry.text}
                      className={styles.row}
                      data-kind={entry.kind}
                      data-now={now}
                    >
                      <span className={styles.mark} aria-hidden="true">
                        {markOf(entry)}
                      </span>
                      <div className={styles.body}>
                        {entry.kind === "tool" && entry.primitive ? (
                          <code className={styles.primitive}>{entry.primitive}</code>
                        ) : null}
                        {entry.kind === "fact" && entry.short ? (
                          <span className={styles.caught}>포착 · {entry.short}</span>
                        ) : null}
                        {entry.kind === "reject" ? (
                          <span className={styles.dropped}>근거 부족</span>
                        ) : null}
                        <span className={styles.text}>{entry.text}</span>
                      </div>
                      {entry.kind === "tool" ? (
                        <span className={styles.result}>{entry.meta}</span>
                      ) : null}
                    </li>
                  );
                })}
                {halted ? (
                  <li className={styles.row} data-kind="halted">
                    <span className={styles.mark} aria-hidden="true">
                      ⏸
                    </span>
                    <div className={styles.body}>
                      <span className={styles.text}>{lead}</span>
                    </div>
                  </li>
                ) : null}
              </ol>
            </div>
          </div>
        )}
      </div>

      {session.clarification ? (
        <ClarificationModal
          prompt={session.clarification}
          onAnswer={onAnswerClarification}
        />
      ) : null}
    </div>
  );
}
