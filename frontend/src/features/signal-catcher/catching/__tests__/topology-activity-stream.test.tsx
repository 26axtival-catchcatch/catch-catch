import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { AgentActivity } from "../../../customer-intelligence/agent-activity";

import { TopologyActivityStream } from "../TopologyActivityStream";

afterEach(cleanup);

function activity(overrides: Partial<AgentActivity> = {}): AgentActivity {
  return {
    schema_version: 1,
    node_id: "agent-investigator-1",
    parent_node_id: null,
    depends_on: [],
    kind: "agent",
    role: "investigator",
    task_id: "task-investigate",
    round_index: 0,
    status: "started",
    name: "investigator",
    display_text: "이탈 위험 가설을 조사하고 있어요.",
    occurred_at: "2026-09-10T08:00:00Z",
    duration_ms: null,
    model: null,
    details: { candidates: [], decisions: [], limitations: [] },
    ...overrides,
  };
}

describe("TopologyActivityStream", () => {
  it("groups model and tool activity below its topology role and exposes public details", () => {
    render(
      <TopologyActivityStream
        activities={[
          activity(),
          activity({
            node_id: "tool-query-1",
            parent_node_id: "agent-investigator-1",
            kind: "tool",
            status: "completed",
            name: "query_data",
            display_text: "해지 전 행동 기록을 조회했어요.",
            duration_ms: 1240,
            details: {
              row_count: 328,
              candidates: [],
              decisions: [],
              limitations: [],
            },
          }),
        ]}
        halted={false}
      />,
    );

    const group = screen.getByText("가설 조사").closest("section");
    expect(group).not.toBeNull();
    expect(within(group!).getByText("이탈 위험 가설을 조사하고 있어요.")).toBeInTheDocument();
    expect(within(group!).getByText("해지 전 행동 기록을 조회했어요.")).toBeInTheDocument();
    expect(within(group!).getByText("row_count: 328")).toBeInTheDocument();
    expect(within(group!).getAllByText("investigator · task-investigate · round 0")).toHaveLength(2);
    expect(group).toHaveTextContent("query_data");
    expect(group).toHaveTextContent("완료 · completed");
    expect(within(group!).getByText("1.2초")).toBeInTheDocument();
    expect(within(group!).getAllByText("원본 agent_activity payload")).toHaveLength(2);
    expect(group).toHaveTextContent('"node_id": "tool-query-1"');
    expect(group).toHaveTextContent('"display_text": "해지 전 행동 기록을 조회했어요."');
  });

  it("does not invent activity rows before agent_activity events arrive", () => {
    render(
      <TopologyActivityStream
        activities={[]}
        halted={false}
      />,
    );

    expect(screen.getByText("분석 공간을 연결하고 있어요")).toBeInTheDocument();
    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
    expect(screen.getByText("실행 준비")).toBeInTheDocument();
  });

  it("같은 node_id의 상태 변경 이벤트도 받은 순서대로 모두 표시한다", () => {
    render(
      <TopologyActivityStream
        activities={[
          activity({ status: "queued", display_text: "분석을 기다리고 있어요." }),
          activity({ status: "started", display_text: "분석하고 있어요." }),
          activity({ status: "completed", display_text: "분석을 마쳤어요." }),
        ]}
        halted={false}
      />,
    );

    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText("분석을 기다리고 있어요.")).toBeInTheDocument();
    expect(screen.getByText("분석하고 있어요.")).toBeInTheDocument();
    expect(screen.getByText("분석을 마쳤어요.")).toBeInTheDocument();
    expect(screen.getByText("실행 완료")).toBeInTheDocument();
  });
});
