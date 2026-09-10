"use client";

import dynamic from "next/dynamic";
import { useId, useMemo, useState } from "react";
import type { AnyRunStreamEvent } from "../../customer-intelligence/contracts";
import { AgentConversation } from "../conversation/AgentConversation";
import { createAgentTopology } from "./agent-topology";
import { TopologyActivityStream } from "./TopologyActivityStream";
import styles from "./catching.module.css";
import viewStyles from "./workspace.module.css";

const AgentGraph = dynamic(() => import("./AgentGraph").then(module => module.AgentGraph), {
  ssr: false,
  loading: () => <div className={`${styles.canvas} ${styles.canvasLoading}`} aria-label="분석 흐름 준비 중">분석 흐름을 준비하고 있어요</div>,
});

interface AgentWorkspaceProps {
  events: AnyRunStreamEvent[];
  halted?: boolean;
  completed?: boolean;
  speed?: number;
  loading?: boolean;
  error?: boolean;
  onRetry?: () => void;
}

export function AgentWorkspace({ events, halted = false, completed = false, speed = 1,
  loading = false, error = false, onRetry }: AgentWorkspaceProps) {
  const [view, setView] = useState<"conversation" | "topology">("conversation");
  const id = useId();
  const topology = useMemo(() => createAgentTopology(events), [events]);
  const activities = useMemo(() => events.flatMap(event => event.type === "agent_activity" ? [event.data] : []), [events]);
  return <div className={viewStyles.container}>
    <div className={viewStyles.toolbar}>
      <div className={viewStyles.switch} role="group" aria-label="분석 과정 보기 방식">
        <button type="button" aria-pressed={view === "conversation"} aria-controls={`${id}-content`}
          onClick={() => setView("conversation")}>에이전트 대화</button>
        <button type="button" aria-pressed={view === "topology"} aria-controls={`${id}-content`}
          onClick={() => setView("topology")}>토폴로지</button>
      </div>
      <p className={viewStyles.hint}>{completed ? "캐치까지 이어진 대화를 살펴보세요" : "함께 단서를 찾고 있어요"}</p>
    </div>
    <div id={`${id}-content`}>
      <div hidden={view !== "conversation"}>
        <AgentConversation activities={activities} halted={halted} completed={completed}
          loading={loading} error={error} onRetry={onRetry} active={view === "conversation"} />
      </div>
      {view === "topology" ? <>
        {error ? <p role="alert" className={viewStyles.notice}>실행 기록을 불러오지 못했어요. <button type="button" onClick={onRetry}>다시 불러오기</button></p> : null}
        <div className={`${styles.workspace} ${viewStyles.topology}`}>
          <TopologyActivityStream activities={activities} halted={halted} />
          <section className={styles.graphPanel} aria-labelledby={`${id}-topology-title`}>
            <header className={styles.columnHeader}><div><p className={styles.columnKicker}>AGENT TOPOLOGY</p>
              <h2 id={`${id}-topology-title`}>{completed ? "멀티에이전트 실행 기록" : "실시간 멀티에이전트 실행"}</h2></div>
              <span className={styles.graphLegend}>현재 실행을 따라 이동 · 드래그로 이전 단계 확인</span>
            </header>
            <AgentGraph topology={topology} halted={halted || completed} speed={speed}
              planning={events.length > 0 && activities.length === 0 && !halted && !completed} />
          </section>
        </div>
      </> : null}
    </div>
  </div>;
}
