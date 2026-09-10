"use client";

import { memo, useEffect, useMemo, useRef } from "react";

import type { AgentActivity } from "../../customer-intelligence/agent-activity";

import styles from "./catching.module.css";

interface TopologyActivityStreamProps {
  activities: AgentActivity[];
  halted: boolean;
}

const ROLE_LABELS: Record<AgentActivity["role"], string> = {
  coordinator: "분석 조율",
  investigator: "가설 조사",
  verifier: "독립 검증",
  reporter: "결과 정리",
};

const KIND_LABELS: Record<AgentActivity["kind"], string> = {
  agent: "역할",
  model: "모델",
  tool: "도구",
  assessment: "판정",
};

const STATUS_LABELS: Record<AgentActivity["status"], string> = {
  queued: "대기",
  started: "진행",
  completed: "완료",
  failed: "실패",
  cancelled: "중단",
};

const KIND_MARKS: Record<AgentActivity["kind"], string> = {
  agent: "◎",
  model: "✦",
  tool: "∑",
  assessment: "✓",
};

function compactNumber(value: number): string {
  return value.toLocaleString("ko-KR");
}

function durationLabel(durationMs: number | null): string | null {
  if (durationMs === null) return null;
  if (durationMs < 1000) return `${durationMs}ms`;
  return `${(durationMs / 1000).toFixed(durationMs < 10_000 ? 1 : 0)}초`;
}

function activityDetails(activity: AgentActivity): string[] {
  const details = activity.details;
  const values: string[] = [];
  const identifiers: Array<[string, string | null | undefined]> = [
    ["query_id", details.query_id],
    ["measurement_id", details.measurement_id],
    ["candidate_id", details.candidate_id],
  ];
  const counts: Array<[string, number | null | undefined]> = [
    ["row_count", details.row_count],
    ["event_count", details.event_count],
    ["customer_count", details.customer_count],
    ["table_count", details.table_count],
    ["item_count", details.item_count],
    ["tool_count", details.tool_count],
    ["input_tokens", details.input_tokens],
    ["output_tokens", details.output_tokens],
  ];

  for (const [key, value] of identifiers) {
    if (value !== null && value !== undefined) values.push(`${key}: ${value}`);
  }
  for (const [key, value] of counts) {
    if (value !== null && value !== undefined) values.push(`${key}: ${compactNumber(value)}`);
  }
  if (details.truncated !== null && details.truncated !== undefined) {
    values.push(`truncated: ${String(details.truncated)}`);
  }
  if (details.candidates.length > 0) {
    for (const candidate of details.candidates) {
      values.push(`candidate: ${candidate.candidate_id} · ${candidate.title}`);
      values.push(`cohort_query_id: ${candidate.cohort_query_id}`);
      if (candidate.evidence_query_ids.length > 0) {
        values.push(`evidence_query_ids: ${candidate.evidence_query_ids.join(", ")}`);
      }
    }
  }
  if (details.decisions.length > 0) {
    for (const decision of details.decisions) {
      values.push(`decision: ${decision.candidate_id} · ${decision.verdict} · ${decision.reason}`);
      if (decision.cohort_query_id) values.push(`cohort_query_id: ${decision.cohort_query_id}`);
      if (decision.evidence_query_ids.length > 0) {
        values.push(`evidence_query_ids: ${decision.evidence_query_ids.join(", ")}`);
      }
      if (decision.followup_question) values.push(`followup_question: ${decision.followup_question}`);
    }
  }
  for (const limitation of details.limitations) values.push(`limitation: ${limitation}`);
  if (details.error_code) values.push(`error_code: ${details.error_code}`);
  return values;
}

interface ActivityGroup {
  id: string;
  role: AgentActivity["role"];
  roundIndex: number;
  events: AgentActivity[];
}

function groupActivities(activities: AgentActivity[]): ActivityGroup[] {
  const groups = new Map<string, ActivityGroup>();

  for (const activity of activities) {
    const groupId = activity.kind === "agent"
      ? activity.node_id
      : activity.parent_node_id ?? activity.node_id;
    const group = groups.get(groupId);
    if (group) group.events.push(activity);
    else {
      groups.set(groupId, {
        id: groupId,
        role: activity.role,
        roundIndex: activity.round_index,
        events: [activity],
      });
    }
  }

  return [...groups.values()];
}

const ActivityRow = memo(function ActivityRow({
  activity,
  child = false,
}: { activity: AgentActivity; child?: boolean }) {
  const details = activityDetails(activity);
  const duration = durationLabel(activity.duration_ms);
  // Conversation prose is reserved for the chat panel, including in this debug disclosure.
  const rawPayload = JSON.stringify(activity,
    (key, value) => key === "message_kind" || key === "message_text" ? undefined : value, 2);
  const context = [
    activity.role,
    activity.task_id,
    `round ${activity.round_index}`,
    activity.model,
  ].filter(Boolean).join(" · ");

  return (
    <li
      className={styles.activityRow}
      data-child={child}
      data-status={activity.status}
      data-kind={activity.kind}
    >
      <span className={styles.activityMark} aria-hidden="true">{KIND_MARKS[activity.kind]}</span>
      <div className={styles.activityBody}>
        <div className={styles.activityEyebrow}>
          <span>{KIND_LABELS[activity.kind]} · <code>{activity.name}</code></span>
          <span className={styles.activityStatus}>
            {STATUS_LABELS[activity.status]} · {activity.status}
          </span>
        </div>
        <p className={styles.activityText}>{activity.display_text}</p>
        <p className={styles.activityContext}>{context}</p>
        {details.length > 0 ? (
          <div className={styles.activityDetails}>
            {details.map((detail, index) => <span key={`${detail}-${index}`}>{detail}</span>)}
          </div>
        ) : null}
        <details className={styles.activityRaw}>
          <summary>원본 agent_activity payload</summary>
          <pre>{rawPayload}</pre>
        </details>
      </div>
      {duration ? (
        <time className={styles.activityDuration} dateTime={activity.occurred_at}>{duration}</time>
      ) : null}
    </li>
  );
});

export function TopologyActivityStream({ activities, halted }: TopologyActivityStreamProps) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const groups = useMemo(() => groupActivities(activities), [activities]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (viewport) viewport.scrollTop = viewport.scrollHeight;
  }, [activities.length]);

  const currentState = useMemo(() => {
    const latestByNode = new Map<string, AgentActivity["status"]>();
    for (const activity of activities) latestByNode.set(activity.node_id, activity.status);
    const statuses = [...latestByNode.values()];
    return {
      activeCount: statuses.filter((status) => status === "started").length,
      allDone: statuses.length > 0 && statuses.every((status) =>
        status === "completed" || status === "failed" || status === "cancelled"
      ),
    };
  }, [activities]);
  const { activeCount, allDone } = currentState;

  return (
    <section className={styles.activityPanel} aria-labelledby="activity-stream-title">
      <header className={styles.columnHeader}>
        <div>
          <p className={styles.columnKicker}>LIVE EXECUTION</p>
          <h2 id="activity-stream-title">토폴로지별 액티비티</h2>
        </div>
        <span className={styles.liveCount} data-active={activeCount > 0 && !halted}>
          {halted
            ? "일시 정지"
            : activeCount > 0
              ? `${activeCount}개 진행 중`
              : allDone
                ? "실행 완료"
                : "실행 준비"}
        </span>
      </header>

      <div className={styles.activityViewport} ref={viewportRef} aria-live="polite">
        {groups.length > 0 ? (
          <div className={styles.activityGroups}>
            {groups.map((group) => (
              <section className={styles.activityGroup} key={group.id}>
                <p className={styles.roleLabel}>
                  {ROLE_LABELS[group.role]}
                  <span>{group.role}</span>
                  {group.roundIndex > 0 ? <span>재조사 {group.roundIndex}</span> : null}
                </p>
                <ol className={styles.activityList}>
                  {group.events.map((activity, index) => (
                    <ActivityRow
                      activity={activity}
                      child={activity.kind !== "agent"}
                      key={`${activity.node_id}:${activity.status}:${index}`}
                    />
                  ))}
                </ol>
              </section>
            ))}
          </div>
        ) : (
          <div className={styles.activityEmpty} role="status">
            <i aria-hidden="true" />
            <strong>분석 공간을 연결하고 있어요</strong>
            <span>질문과 데이터 범위를 넘긴 뒤 첫 활동을 바로 보여드릴게요.</span>
          </div>
        )}
      </div>
    </section>
  );
}
