"use client";

import dynamic from "next/dynamic";

import { HeartBurst } from "../brand/Brand";
import { markOf } from "../state/tick-marks";
import type { CatchSession, StageKey, StageTick } from "../state/types";

import { createAgentTopology } from "./agent-topology";
import { ClarificationModal } from "./ClarificationModal";
import styles from "./catching.module.css";

const AgentGraph = dynamic(
  () => import("./AgentGraph").then((module) => module.AgentGraph),
  {
    ssr: false,
    loading: () => (
      <div className={`${styles.canvas} ${styles.canvasLoading}`} aria-label="분석 흐름 준비 중">
        <span>분석 흐름을 준비하고 있어요</span>
      </div>
    ),
  },
);

interface CatchingScreenProps {
  session: CatchSession;
  bursting: boolean;
  flatline: boolean;
  burstMark: "heart" | "lens";
  /** URL speed 옵션과 캔버스의 pulse 속도를 함께 맞춘다. */
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
  const current = log.at(-1) ?? null;
  const graphTopology = createAgentTopology(session, log);
  const { stats: graphStats } = graphTopology;

  const lead = flatline
    ? "연결 문제로 분석이 잠시 멈췄어요"
    : session.clarification
      ? "분석 기준을 정확히 맞추기 위해 확인이 필요해요"
      : active?.key === "analyze" || active?.key === "verify"
        ? "여러 데이터에서 찾은 내용을 근거와 함께 확인하고 있어요"
        : (active?.label ?? "확인된 결과를 정리하고 있어요");

  return (
    <div className={styles.screen}>
      {bursting ? <HeartBurst mark={burstMark} /> : null}

      <p className={styles.context}>{session.question}</p>

      <div className={styles.stage}>
        {failed ? (
          <div className={styles.failure} role="alert">
            <p className={styles.failureTitle}>
              <span className={styles.failureBadge}>분석 중단</span>
              분석을 완료하지 못했어요
            </p>
            <p className={styles.failureReason}>{session.failureReason}</p>
            <p className={styles.failureNote}>
              질문과 조건은 그대로 유지했어요. 같은 조건으로 처음부터 다시 분석할 수 있어요.
            </p>
            <div className={styles.failureActions}>
              <button type="button" className={styles.failureRetry} onClick={onRetry}>
                같은 조건으로 다시 분석
              </button>
              <button type="button" className={styles.failureGhost} onClick={onGiveUp}>
                질문 수정하기
              </button>
            </div>
          </div>
        ) : (
          <div className={styles.panel}>
            <div className={styles.head}>
              <div>
                <p className={styles.kicker}>
                  {activeIndex >= 0
                    ? `분석 진행 · ${String(activeIndex + 1).padStart(2, "0")} / ${String(session.stages.length).padStart(2, "0")}`
                    : "분석 완료"}
                </p>
                <p className={styles.lead} data-halted={halted}>
                  {halted ? null : <span className={styles.spin} aria-hidden="true" />}
                  {lead}
                </p>
              </div>
              <span className={styles.count}>
                작업 {graphTopology.nodes.length}개 · 데이터 조회 {graphStats.tools}회 · <b>발견 {graphStats.catches}건</b>
              </span>
            </div>

            <AgentGraph session={session} log={log} halted={halted} speed={speed} />

            <div className={styles.eventRail} aria-live="polite">
              <span className={styles.eventMark} aria-hidden="true">
                {halted ? "⏸" : current ? markOf(current) : "✎"}
              </span>
              {current?.kind === "tool" && current.primitive ? (
                <code className={styles.primitive}>{current.primitive}</code>
              ) : null}
              {current?.kind === "fact" && current.short ? (
                <strong className={styles.caught}>발견 · {current.short}</strong>
              ) : null}
              {current?.kind === "reject" ? (
                <strong className={styles.dropped}>제외 · 근거 부족</strong>
              ) : null}
              <span className={styles.eventText}>
                {halted ? lead : (current?.text ?? "질문에서 분석 조건을 확인하고 있어요")}
              </span>
              {current?.kind === "tool" ? <span className={styles.eventMeta}>{current.meta}</span> : null}
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
