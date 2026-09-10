import { describe, expect, it } from "vitest";

import type { CatchSession, Stage, StageKey, StageTick } from "../../state/types";
import { createAgentTopology } from "../agent-topology";

const STAGE_KEYS: StageKey[] = ["goal", "plan", "analyze", "insight", "verify"];

function sessionAt(activeStage: StageKey | null): CatchSession {
  const activeIndex = activeStage === null ? -1 : STAGE_KEYS.indexOf(activeStage);
  const stages: Stage[] = STAGE_KEYS.map((key, index) => ({
    key,
    label: key,
    short: key,
    event: key,
    detail: null,
    status: activeIndex < 0 ? "done" : index < activeIndex ? "done" : index === activeIndex ? "active" : "pending",
  }));

  return {
    phase: "catching",
    question: "테스트 질문",
    stages,
    activeStage,
    clarification: null,
    outcome: activeStage === null ? "completed" : null,
    report: null,
    failureReason: null,
    suggestedQuestions: [],
  };
}

function tick(kind: StageTick["kind"], index: number): StageTick & { stage: StageKey } {
  return {
    stage: "analyze",
    kind,
    primitive: kind === "tool" ? `tool_${index}` : null,
    text: `${kind} ${index}`,
    meta: "",
    short: kind === "fact" ? `fact ${index}` : null,
    ms: 100,
  };
}

describe("createAgentTopology", () => {
  it("처음에는 총괄 노드만 만든다", () => {
    const topology = createAgentTopology(sessionAt("goal"), []);

    expect(topology.nodes.map((node) => node.id)).toEqual(["lead"]);
    expect(topology.edges).toEqual([]);
  });

  it("도구가 등장하면 조사 가지를 만들고 검증으로 합류시킨다", () => {
    const topology = createAgentTopology(sessionAt("analyze"), [tick("tool", 1)]);

    expect(topology.nodes.map((node) => node.id)).toEqual([
      "lead",
      "research",
      "search",
      "verify",
    ]);
    expect(topology.edges.map(({ source, target }) => `${source}->${target}`)).toEqual([
      "lead->research",
      "research->search",
      "search->verify",
    ]);
  });

  it("로그가 늘면 양쪽 병렬 가지와 합류 연결을 동적으로 확장한다", () => {
    const log = [
      ...Array.from({ length: 5 }, (_, index) => tick("tool", index)),
      tick("fact", 1),
      tick("fact", 2),
      tick("reject", 1),
    ];
    const topology = createAgentTopology(sessionAt("verify"), log);
    const connections = topology.edges.map(({ source, target }) => `${source}->${target}`);

    expect(topology.nodes).toHaveLength(10);
    expect(connections).toContain("research->behavior");
    expect(connections).toContain("counsel->verify");
    expect(connections).toContain("verify->cross");
    expect(connections).toContain("rebuttal->report");
    expect(topology.nodes.find((node) => node.id === "rebuttal")?.state).toBe("rejected");
  });

  it("완료 상태에서도 현재 토폴로지를 유효한 경로로 유지한다", () => {
    const topology = createAgentTopology(sessionAt(null), []);

    expect(topology.nodes.map((node) => node.id)).toEqual([
      "lead",
      "research",
      "verify",
      "rebuttal",
      "report",
    ]);
    expect(topology.edges.at(-1)).toMatchObject({ source: "rebuttal", target: "report" });
    expect(topology.nodes.every((node) => node.state === "done")).toBe(true);
  });
});
