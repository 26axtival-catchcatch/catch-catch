import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { AgentGraph } from "../AgentGraph";
import type { AgentTopology } from "../agent-topology";

const flowMocks = vi.hoisted(() => ({
  initialized: true,
  setViewport: vi.fn(),
}));

vi.mock("@xyflow/react", () => ({
  BaseEdge: () => null,
  Handle: () => null,
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
  ReactFlow: ({
    nodes,
    nodeTypes,
  }: {
    nodes: Array<{ id: string; type: string; data: Record<string, unknown> }>;
    nodeTypes: Record<string, (props: { data: Record<string, unknown> }) => ReactNode>;
  }) => (
    <div data-testid="react-flow">
      {nodes.map((node) => {
        const NodeComponent = nodeTypes[node.type];
        return <NodeComponent key={node.id} data={node.data} />;
      })}
    </div>
  ),
  ReactFlowProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  getSmoothStepPath: () => [""],
  getViewportForBounds: () => ({ x: 0, y: 0, zoom: 1 }),
  useNodesInitialized: () => flowMocks.initialized,
  useReactFlow: () => ({ setViewport: flowMocks.setViewport }),
}));

const SETUP_TOPOLOGY: AgentTopology = {
  nodes: [{
    id: "workflow:setup",
    mark: "S",
    eyebrow: "SSE WORKFLOW",
    label: "Run · 목표 · 계획",
    meta: "3개 step · revision 0",
    detail: null,
    badges: ["run_started", "goal_created", "plan_created"],
    state: "done",
    category: "workflow",
    role: null,
    primary: false,
    firstEventId: 1,
    lastEventId: 3,
  }],
  edges: [],
  stats: { agents: 0, tools: 0, catches: 0, rejects: 0, allDone: false },
};

class ResizeObserverStub {
  observe() {}
  disconnect() {}
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverStub);
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn().mockImplementation(() => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  });
});

afterEach(cleanup);

beforeEach(() => {
  flowMocks.initialized = true;
  flowMocks.setViewport.mockClear();
});

describe("AgentGraph planning state", () => {
  it("첫 역할이 도착하기 전 workflow 주변에 계획 확장 신호를 보여준다", () => {
    render(<AgentGraph topology={SETUP_TOPOLOGY} halted={false} speed={1} planning />);

    expect(screen.getByLabelText("멀티에이전트 실행 토폴로지"))
      .toHaveAttribute("data-planning", "true");
    expect(screen.getByRole("status", { name: "분석 역할 경로를 설계하고 있어요" }))
      .toBeInTheDocument();
  });

  it("역할 실행이 시작되면 임시 계획 확장 신호를 제거한다", () => {
    render(<AgentGraph topology={SETUP_TOPOLOGY} halted={false} speed={1} planning={false} />);

    expect(screen.getByLabelText("멀티에이전트 실행 토폴로지"))
      .toHaveAttribute("data-planning", "false");
    expect(screen.queryByRole("status", { name: "분석 역할 경로를 설계하고 있어요" }))
      .not.toBeInTheDocument();
  });

  it("새 노드 측정이 끝난 뒤 변경된 토폴로지 범위로 카메라를 다시 맞춘다", async () => {
    flowMocks.initialized = false;
    const { rerender } = render(
      <AgentGraph topology={SETUP_TOPOLOGY} halted={false} speed={1} planning={false} />,
    );
    const canvas = screen.getByLabelText("멀티에이전트 실행 토폴로지");
    Object.defineProperties(canvas, {
      clientWidth: { configurable: true, value: 960 },
      clientHeight: { configurable: true, value: 560 },
    });

    expect(flowMocks.setViewport).not.toHaveBeenCalled();

    flowMocks.initialized = true;
    rerender(<AgentGraph topology={SETUP_TOPOLOGY} halted={false} speed={1} planning={false} />);

    await waitFor(() => expect(flowMocks.setViewport).toHaveBeenCalledWith({ x: 0, y: 0, zoom: 1 }));
  });
});
