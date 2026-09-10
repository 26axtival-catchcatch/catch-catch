"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";

import type { AgentActivity } from "../../customer-intelligence/agent-activity";
import type { AnyRunStreamEvent } from "../../customer-intelligence/contracts";
import { HeartBurst } from "../brand/Brand";
import type { CatchSession, StageKey, StageTick } from "../state/types";

import { createAgentTopology } from "./agent-topology";
import { ClarificationModal } from "./ClarificationModal";
import { TopologyActivityStream } from "./TopologyActivityStream";
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
  const halted = flatline || failed || Boolean(session.clarification);
  const activeIndex = session.stages.findIndex((stage) => stage.status === "active");
  const active = activeIndex < 0 ? null : session.stages[activeIndex];
  const graphTopology = useMemo(() => createAgentTopology(topologyEvents), [topologyEvents]);
  const { stats: graphStats } = graphTopology;
  const isConnecting = topologyEvents.length === 0;
  const isAssigningRoles = !isConnecting && activities.length === 0;

  const lead = flatline
    ? "연결 문제로 분석이 잠시 멈췄어요"
    : session.clarification
      ? "분석 기준을 정확히 맞추기 위해 확인이 필요해요"
      : isConnecting
        ? "질문을 분석 공간에 연결하고 있어요"
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
                {isConnecting
                  ? "실행 흐름 연결 중"
                  : <>역할 {graphStats.agents}개 · 도구 호출 {graphStats.tools}회 · <b>확정 {graphStats.catches}건</b></>}
              </span>
            </div>

            <div className={styles.workspace}>
              <TopologyActivityStream activities={activities} halted={halted} />
              <section className={styles.graphPanel} aria-labelledby="agent-topology-title">
                <header className={styles.columnHeader}>
                  <div>
                    <p className={styles.columnKicker}>AGENT TOPOLOGY</p>
                    <h2 id="agent-topology-title">실시간 멀티에이전트 실행</h2>
                  </div>
                  <span className={styles.graphLegend}>현재 실행을 따라 이동 · 드래그로 이전 단계 확인</span>
                </header>
                <AgentGraph topology={graphTopology} halted={halted} speed={speed} />
              </section>
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
