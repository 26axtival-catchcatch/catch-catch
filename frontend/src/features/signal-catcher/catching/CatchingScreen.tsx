"use client";

import { useMemo } from "react";

import type { AgentActivity } from "../../customer-intelligence/agent-activity";
import type { AnyRunStreamEvent } from "../../customer-intelligence/contracts";
import { HeartBurst } from "../brand/Brand";
import type { CatchSession, StageKey, StageTick } from "../state/types";

import { createAgentTopology } from "./agent-topology";
import { ClarificationModal } from "./ClarificationModal";
import { AgentWorkspace } from "./AgentWorkspace";
import styles from "./catching.module.css";

interface CatchingScreenProps {
  session: CatchSession;
  bursting: boolean;
  flatline: boolean;
  burstMark: "heart" | "lens";
  /** URL speed 옵션과 캔버스의 pulse 속도를 함께 맞춘다. */
  speed: number;
  log: (StageTick & { stage: StageKey })[];
  activities: AgentActivity[];
  topologyEvents: AnyRunStreamEvent[];
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
  activities,
  topologyEvents,
  onAnswerClarification,
  onRetry,
  onGiveUp,
}: CatchingScreenProps) {
  const failed = session.outcome === "failed";
  const inputBlocked = session.failureCode === "input_out_of_scope"
    || session.failureCode === "input_unsafe";
  const halted = flatline || failed || Boolean(session.clarification);
  const activeIndex = session.stages.findIndex((stage) => stage.status === "active");
  const active = activeIndex < 0 ? null : session.stages[activeIndex];
  const graphTopology = useMemo(() => createAgentTopology(topologyEvents), [topologyEvents]);
  const { stats: graphStats } = graphTopology;
  const isConnecting = topologyEvents.length === 0;
  const isCheckingInput = !topologyEvents.some((event) => event.type === "goal_created")
    && (session.activeStage === null || session.activeStage === "goal");
  const isAssigningRoles = !isConnecting && activities.length === 0;

  const lead = flatline
    ? "연결 문제로 분석이 잠시 멈췄어요"
    : session.clarification
      ? "분석 기준을 정확히 맞추기 위해 확인이 필요해요"
      : isCheckingInput
        ? "입력한 질문이 분석 가능한지 확인하고 있어요"
        : isAssigningRoles
          ? "분석 목표를 정하고 역할을 나누고 있어요"
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
              <span className={styles.failureBadge}>{inputBlocked ? "질문 확인" : "분석 중단"}</span>
              {inputBlocked ? "이 질문으로는 분석을 시작할 수 없어요" : "분석을 완료하지 못했어요"}
            </p>
            <p className={styles.failureReason}>{session.failureReason}</p>
            <p className={styles.failureNote}>
              {inputBlocked
                ? "고객 행동이나 상담 데이터로 확인하고 싶은 내용을 질문으로 적어 주세요."
                : "질문과 조건은 그대로 유지했어요. 같은 조건으로 처음부터 다시 분석할 수 있어요."}
            </p>
            <div className={styles.failureActions}>
              {inputBlocked ? null : <button type="button" className={styles.failureRetry} onClick={onRetry}>
                같은 조건으로 다시 분석
              </button>}
              <button type="button" className={inputBlocked ? styles.failureRetry : styles.failureGhost} onClick={onGiveUp}>
                질문 수정하기
              </button>
            </div>
          </div>
        ) : (
          <div className={styles.panel}>
            <div className={styles.head}>
              <div>
                <p className={styles.kicker}>
                  {isCheckingInput ? "질문 확인 중" : activeIndex >= 0
                    ? `분석 진행 · ${String(activeIndex + 1).padStart(2, "0")} / ${String(session.stages.length).padStart(2, "0")}`
                    : "분석 완료"}
                </p>
                <p className={styles.lead} data-halted={halted}>
                  {halted ? null : <span className={styles.spin} aria-hidden="true" />}
                  {lead}
                </p>
              </div>
              <span className={styles.count}>
                {isCheckingInput
                  ? "입력 확인 중"
                  : <>역할 {graphStats.agents}개 · 도구 호출 {graphStats.tools}회 · <b>확정 {graphStats.catches}건</b></>}
              </span>
            </div>

            <AgentWorkspace events={topologyEvents} halted={halted} speed={speed} />
          </div>
        )}
        {failed ? <div className={styles.panel}><AgentWorkspace events={topologyEvents} halted speed={speed} /></div> : null}
      </div>

      {session.clarification ? (
        <ClarificationModal
          key={session.clarification.clarificationId}
          prompt={session.clarification}
          onAnswer={onAnswerClarification}
        />
      ) : null}
    </div>
  );
}
