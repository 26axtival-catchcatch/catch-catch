"use client";

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import type { AgentActivity } from "../../customer-intelligence/agent-activity";
import { ACTIVITY_STATUS, AGENT_ROLES, buildConversation, type ConversationMessage } from "./agent-conversation";
import { AgentCharacter } from "./AgentCharacter";
import { ConversationMarkdown } from "./ConversationMarkdown";
import styles from "./conversation.module.css";

interface AgentConversationProps {
  activities: readonly AgentActivity[];
  halted?: boolean;
  completed?: boolean;
  loading?: boolean;
  error?: boolean;
  onRetry?: () => void;
  active?: boolean;
}

const KIND_LABELS = { commentary: "진행 설명", summary: "결과 요약" };
const timeFormat = new Intl.DateTimeFormat("ko-KR", {
  hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23", timeZone: "Asia/Seoul",
});
const dateFormat = new Intl.DateTimeFormat("ko-KR", {
  month: "long", day: "numeric", timeZone: "Asia/Seoul",
});
const dayKey = (timestamp: string) => new Date(Date.parse(timestamp) + 9 * 3600_000).toISOString().slice(0, 10);

function Message({ message }: { message: ConversationMessage }) {
  const { activity } = message;
  return (
    <li className={styles.message} data-kind={message.kind}>
      <div className={styles.messageMeta}>
        <span>{KIND_LABELS[message.kind]}</span>
        <time dateTime={activity.occurred_at}>{timeFormat.format(new Date(activity.occurred_at))}</time>
      </div>
      <ConversationMarkdown text={message.text} />
      {activity.details.decisions.length > 0 || activity.details.limitations.length > 0 ? (
        <details className={styles.evidence}>
          <summary>판단 근거 보기</summary>
          {activity.details.decisions.map((decision, index) => (
            <ConversationMarkdown key={`${decision.candidate_id}:${index}`} text={decision.reason} />
          ))}
          {activity.details.limitations.map((limitation, index) => <ConversationMarkdown key={index} text={limitation} />)}
        </details>
      ) : null}
    </li>
  );
}

export function AgentConversation({ activities, halted = false, completed = false,
  loading = false, error = false, onRetry, active = true }: AgentConversationProps) {
  const { agents, messages } = useMemo(() => buildConversation(activities), [activities]);
  const [selected, setSelected] = useState<string | null>(null);
  const [unread, setUnread] = useState(false);
  const viewportRef = useRef<HTMLDivElement>(null);
  const followingRef = useRef(!completed);
  const autoScrollTopRef = useRef<number | null>(null);
  const activeAgent = agents.find(agent => agent.id === selected);
  const visible = activeAgent ? messages.filter(message => message.agentId === activeAgent.id) : messages;
  const groups = useMemo(() => {
    const grouped: { agentId: string; day: string; messages: ConversationMessage[] }[] = [];
    for (const message of visible) {
      const day = dayKey(message.activity.occurred_at);
      const previous = grouped.at(-1);
      if (previous?.agentId === message.agentId && previous.day === day) previous.messages.push(message);
      else grouped.push({ agentId: message.agentId, day, messages: [message] });
    }
    return grouped;
  }, [visible]);
  const lastMessageId = visible.at(-1)?.id;

  const scrollToLatest = () => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    viewport.scrollTop = viewport.scrollHeight;
    autoScrollTopRef.current = viewport.scrollTop;
  };

  useLayoutEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || !active) return;
    if (followingRef.current) scrollToLatest();
    else if (!completed) setUnread(true);
  }, [lastMessageId, completed, active]);

  const selectAgent = (id: string | null) => {
    setSelected(id);
    followingRef.current = !completed;
    setUnread(false);
    if (completed && viewportRef.current) viewportRef.current.scrollTop = 0;
    else scrollToLatest();
  };
  const jumpToLatest = () => {
    followingRef.current = true;
    setUnread(false);
    scrollToLatest();
  };
  const stateLabel = loading ? "기록 불러오는 중" : error ? "기록 연결 확인 필요" : completed ? "분석 기록" : halted ? "일시 정지" : "실시간 대화";

  return (
    <div className={styles.room}>
      <aside className={styles.sidebar} aria-label="참여 에이전트">
        <header className={styles.sidebarHeader}>
          <div><span className={styles.teamKicker}>CATCH TEAM</span><strong>단서를 쫓는 동료들</strong></div>
          <b>{String(agents.length).padStart(2, "0")}</b>
        </header>
        <nav className={styles.participants} aria-label="에이전트별 대화 선택">
          <button type="button" className={styles.participant} aria-pressed={!activeAgent}
            data-role="all" onClick={() => selectAgent(null)}>
            <span className={styles.avatar}><AgentCharacter role="all" /></span>
            <span className={styles.participantText}><strong>전체 대화</strong><small>캐치 팀 모두 모여!</small></span>
            <span className={styles.messageCount}>{messages.length}</span>
          </button>
          {agents.map(agent => (
            <button key={agent.id} type="button" className={styles.participant} data-role={agent.role}
              aria-label={`${agent.nickname} · ${agent.label} · ${ACTIVITY_STATUS[agent.status]}`}
              aria-pressed={activeAgent?.id === agent.id} onClick={() => selectAgent(agent.id)}>
              <span className={styles.avatar} data-active={agent.status === "started" && !halted && !completed}><AgentCharacter role={agent.role} /></span>
              <span className={styles.participantText}>
                <strong>{agent.nickname}</strong>
                <small>{agent.label} · {agent.roundIndex > 0 ? `재조사 ${agent.roundIndex} · ` : ""}{ACTIVITY_STATUS[agent.status]}</small>
              </span>
              <span className={styles.statusDot} data-status={agent.status} data-halted={halted || completed} aria-hidden="true" />
            </button>
          ))}
        </nav>
        <div className={styles.sidebarNote}><span className={styles.clueTrail} aria-hidden="true"><i /><i /><i /><b>↗</b></span>
          <p>작은 단서도 놓치지 않게.<br />함께 찾고, 서로 확인해요.</p></div>
      </aside>

      <section className={styles.thread} aria-label="분석 대화방">
        <header className={styles.threadHeader}>
          <div><h2>{activeAgent ? `${activeAgent.nickname}의 단서 노트` : "캐치캐치 탐정단"}</h2>
            <p>{activeAgent ? AGENT_ROLES[activeAgent.role].description : "고객이 남긴 단서, 함께 따라가 볼까요?"}</p></div>
          <span className={styles.live} data-active={!completed && !halted && !loading && !error}>
            <i aria-hidden="true" />{stateLabel}
          </span>
        </header>
        {error ? <div className={styles.error} role="alert">대화 기록을 불러오지 못했어요.
          <button type="button" onClick={onRetry}>다시 불러오기</button></div> : null}
        <div className={styles.viewport} ref={viewportRef} role="region" aria-label="에이전트 메시지" tabIndex={0}
          onScroll={() => {
            const viewport = viewportRef.current;
            if (!viewport || !active) return;
            // A delayed programmatic scroll can fire after another SSE batch grows the content.
            if (followingRef.current && viewport.scrollTop === autoScrollTopRef.current) return;
            followingRef.current = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 64;
            if (followingRef.current) setUnread(false);
          }}>
          {groups.length ? groups.map((group, index) => {
            const agent = agents.find(item => item.id === group.agentId)!;
            return <div key={group.messages[0].id}>
              {index === 0 || groups[index - 1].day !== group.day ? (
                <p className={styles.day}><span>{dateFormat.format(new Date(group.messages[0].activity.occurred_at))} · 분석 대화</span></p>
              ) : null}
              <div className={styles.messageGroup} data-role={agent.role}>
                <span className={styles.avatar}><AgentCharacter role={agent.role} /></span>
                <div className={styles.groupBody}>
                  <p className={styles.author}>{agent.nickname}<span className={styles.roleLabel}>{agent.label}</span>{agent.roundIndex > 0 ? <small>재조사 {agent.roundIndex}</small> : null}</p>
                  <ol className={styles.messages}>{group.messages.map(message => <Message key={message.id} message={message} />)}</ol>
                </div>
              </div>
            </div>;
          }) : <div className={styles.empty}>
            <span className={styles.emptyMark}><AgentCharacter role="all" /></span>
            <strong>{loading ? "에이전트 대화를 불러오고 있어요" : error ? "기록을 다시 연결해 주세요" : completed ? "저장된 에이전트 대화가 없어요" : halted ? "분석이 잠시 멈춰 있어요" : "에이전트가 전할 이야기를 기다리고 있어요"}</strong>
            <p>{completed ? "이 분석에는 공개된 에이전트 메시지가 기록되지 않았어요." : "에이전트가 단서를 찾고 있어요. 전할 이야기가 생기면 이곳에 이어집니다."}</p>
          </div>}
        </div>
        <footer className={styles.threadFooter}>
          <span role="status">{visible.length}개 메시지 · 시간순{halted && !completed ? " · 새 활동을 기다리고 있어요" : ""}</span>
          <span>한국 표준시</span>
          {unread ? <button type="button" className={styles.latest} onClick={jumpToLatest}>최신 대화로 ↓</button> : null}
        </footer>
      </section>
    </div>
  );
}
