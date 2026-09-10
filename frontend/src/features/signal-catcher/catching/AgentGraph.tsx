"use client";

import { Graph, layout, type EdgeLabel, type GraphLabel, type NodeLabel } from "@dagrejs/dagre";
import {
  BaseEdge,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  getSmoothStepPath,
  getViewportForBounds,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { memo, useEffect, useMemo, useRef, useState } from "react";

import "@xyflow/react/dist/style.css";

import {
  type AgentTopology,
  type AgentTopologyNode,
  type SignalEdgeState,
  type TopologyEdgeRelation,
} from "./agent-topology";
import styles from "./catching.module.css";

const NODE_DIMENSIONS = {
  workflow: { width: 154, height: 72 },
  step: { width: 172, height: 88 },
  agent: { width: 184, height: 104 },
} as const;

type LayoutDirection = "LR" | "TB";
type AgentNodeData = AgentTopologyNode & {
  direction: LayoutDirection;
} & Record<string, unknown>;
type AgentFlowNode = Node<AgentNodeData, "agent">;
type SignalEdgeData = {
  state: SignalEdgeState;
  relation: TopologyEdgeRelation;
  halted: boolean;
  speed: number;
} & Record<string, unknown>;
type SignalFlowEdge = Edge<SignalEdgeData, "signal">;

interface AgentGraphProps {
  topology: AgentTopology;
  halted: boolean;
  speed: number;
}

const AgentNodeCard = memo(function AgentNodeCard({ data }: NodeProps<AgentFlowNode>) {
  const horizontal = data.direction === "LR";

  return (
    <div
      className={styles.node}
      data-primary={data.primary}
      data-state={data.state}
      data-category={data.category}
      data-role={data.role ?? undefined}
      role="listitem"
      aria-label={`${data.label}, ${data.meta}`}
    >
      <Handle
        className={styles.handle}
        type="target"
        position={horizontal ? Position.Left : Position.Top}
        isConnectable={false}
      />
      <span className={styles.nodeHead}>
        <span className={styles.orbWrap} aria-hidden="true">
          <span className={styles.orb}>{data.mark}</span>
        </span>
        <span className={styles.nodeTitle}>
          <span className={styles.nodeEyebrow}>{data.eyebrow}</span>
          <span className={styles.nodeLabel}>{data.label}</span>
        </span>
      </span>
      <span className={styles.nodeMeta} title={data.meta}>{data.meta}</span>
      {data.detail ? <span className={styles.nodeDetail}>{data.detail}</span> : null}
      <span className={styles.nodeBadges} aria-label="수신한 이벤트 상태">
        {data.badges.map((badge) => <span key={badge}>{badge}</span>)}
      </span>
      <Handle
        className={styles.handle}
        type="source"
        position={horizontal ? Position.Right : Position.Bottom}
        isConnectable={false}
      />
    </div>
  );
});

function SignalEdge({
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
}: EdgeProps<SignalFlowEdge>) {
  const [edgePath] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    borderRadius: 12,
    offset: 22,
  });
  const state = data?.state ?? "idle";
  const duration = Math.max(0.8, 1.55 * (data?.speed ?? 1));

  return (
    <>
      <BaseEdge
        path={edgePath}
        className={styles.edge}
        data-state={state}
        data-relation={data?.relation ?? "stream"}
        style={{ "--pulse-duration": `${duration}s` } as React.CSSProperties}
      />
      {state === "active" && !data?.halted ? (
        <circle className={styles.edgePulse} r="3" aria-hidden="true">
          <animateMotion dur={`${duration}s`} repeatCount="indefinite" path={edgePath} />
        </circle>
      ) : null}
    </>
  );
}

const nodeTypes = { agent: AgentNodeCard };
const edgeTypes = { signal: SignalEdge };

function layoutTopology(
  topology: AgentTopology,
  halted: boolean,
  speed: number,
  direction: LayoutDirection,
): { nodes: AgentFlowNode[]; edges: SignalFlowEdge[] } {
  const graph = new Graph<GraphLabel, NodeLabel, EdgeLabel>();
  graph.setGraph({
    rankdir: direction,
    ranker: "network-simplex",
    align: "UL",
    nodesep: direction === "LR" ? 20 : 12,
    edgesep: 10,
    ranksep: direction === "LR" ? 48 : 18,
    marginx: 16,
    marginy: 16,
  });
  graph.setDefaultEdgeLabel(() => ({}));

  for (const node of topology.nodes) {
    graph.setNode(node.id, { ...NODE_DIMENSIONS[node.category] });
  }
  for (const edge of topology.edges) {
    graph.setEdge(edge.source, edge.target);
  }
  layout(graph);

  const nodes: AgentFlowNode[] = topology.nodes.map((node) => {
    const dimensions = NODE_DIMENSIONS[node.category];
    const dagrePosition = graph.node(node.id);
    const position = {
      x: (dagrePosition.x ?? 0) - dimensions.width / 2,
      y: (dagrePosition.y ?? 0) - dimensions.height / 2,
    };
    return {
      id: node.id,
      type: "agent",
      data: { ...node, direction } as AgentNodeData,
      position,
      sourcePosition: direction === "LR" ? Position.Right : Position.Bottom,
      targetPosition: direction === "LR" ? Position.Left : Position.Top,
      draggable: false,
      selectable: false,
      connectable: false,
      focusable: false,
      className: styles.flowNode,
      style: dimensions,
    };
  });
  const edges: SignalFlowEdge[] = topology.edges.map((edge) => ({
    ...edge,
    type: "signal",
    data: { state: edge.state, relation: edge.relation, halted, speed },
    selectable: false,
    focusable: false,
  }));

  return { nodes, edges };
}

function useLayoutDirection(): LayoutDirection {
  const [compact, setCompact] = useState(() =>
    window.matchMedia("(max-width: 900px)").matches,
  );

  useEffect(() => {
    const query = window.matchMedia("(max-width: 900px)");
    const updateCompact = () => setCompact(query.matches);
    query.addEventListener("change", updateCompact);
    return () => query.removeEventListener("change", updateCompact);
  }, []);

  return compact ? "TB" : "LR";
}

function focusWindow(nodes: readonly AgentFlowNode[]): AgentFlowNode[] {
  if (nodes.length <= 4) return [...nodes];

  const ordered = [...nodes].sort(
    (left, right) => left.data.lastEventId - right.data.lastEventId,
  );
  const activeIds = new Set(
    ordered.filter((node) => node.data.state === "active").map((node) => node.id),
  );
  const currentIndex = activeIds.size > 0
    ? ordered.reduce(
      (latest, node, index) => activeIds.has(node.id) ? Math.max(latest, index) : latest,
      0,
    )
    : ordered.length - 1;
  const start = Math.max(0, currentIndex - 3);
  const focus = ordered.slice(start, currentIndex + 1);

  for (const node of ordered) {
    if (activeIds.has(node.id) && !focus.some((candidate) => candidate.id === node.id)) {
      focus.push(node);
    }
  }
  return focus;
}

function focusBounds(nodes: readonly AgentFlowNode[]) {
  const left = Math.min(...nodes.map((node) => node.position.x));
  const top = Math.min(...nodes.map((node) => node.position.y));
  const right = Math.max(...nodes.map(
    (node) => node.position.x + NODE_DIMENSIONS[node.data.category].width,
  ));
  const bottom = Math.max(...nodes.map(
    (node) => node.position.y + NODE_DIMENSIONS[node.data.category].height,
  ));
  return { x: left, y: top, width: right - left, height: bottom - top };
}

function AgentGraphCanvas({ topology, halted, speed }: AgentGraphProps) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const direction = useLayoutDirection();
  const { nodes, edges } = useMemo(
    () => layoutTopology(topology, halted, speed, direction),
    [topology, halted, speed, direction],
  );
  const focusNodes = useMemo(() => focusWindow(nodes), [nodes]);
  const cameraTarget = useMemo(() => {
    if (!focusNodes.length) return null;
    return {
      bounds: focusBounds(focusNodes),
      // 상태 이벤트만 추가될 때는 카메라를 다시 움직이지 않는다. 노드 구성이나
      // 레이아웃이 실제로 달라질 때만 새 화면 범위를 계산한다.
      key: `${direction}|${focusNodes.map((node) => [
        node.id,
        Math.round(node.position.x),
        Math.round(node.position.y),
        node.data.category,
      ].join(":"))}`,
    };
  }, [direction, focusNodes]);
  const cameraTargetRef = useRef(cameraTarget);
  cameraTargetRef.current = cameraTarget;
  const { setViewport } = useReactFlow<AgentFlowNode, SignalFlowEdge>();

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !cameraTargetRef.current) return;

    let frame = 0;
    const refit = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        const target = cameraTargetRef.current;
        const width = canvas.clientWidth;
        const height = canvas.clientHeight;
        if (!target || width <= 0 || height <= 0) return;
        const viewport = getViewportForBounds(
          target.bounds,
          width,
          height,
          0.66,
          1.05,
          0.28,
        );
        // SSE가 몰릴 때 연속 카메라 애니메이션이 서로 덮어써 빈 화면처럼
        // 보이지 않도록 안정된 위치로 즉시 맞춘다.
        void setViewport(viewport);
      });
    };
    const observer = new ResizeObserver(refit);
    observer.observe(canvas);
    refit();

    return () => {
      observer.disconnect();
      window.cancelAnimationFrame(frame);
    };
  }, [cameraTarget?.key, setViewport]);

  return (
    <div
      ref={canvasRef}
      className={styles.canvas}
      data-halted={halted}
      role={nodes.length > 0 ? "list" : undefined}
      aria-label="멀티에이전트 실행 토폴로지"
    >
      {nodes.length > 0 ? (
        <ReactFlow<AgentFlowNode, SignalFlowEdge>
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          minZoom={0.28}
          maxZoom={1.35}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          panOnDrag
          zoomOnScroll={false}
          zoomOnPinch
          zoomOnDoubleClick={false}
          preventScrolling={false}
        />
      ) : (
        <div className={styles.graphEmpty} role="status">
          <i aria-hidden="true" />
          <strong>분석 역할을 연결하고 있어요</strong>
          <span>첫 실행 흐름이 도착하면 여기에 바로 펼쳐져요.</span>
        </div>
      )}
    </div>
  );
}

export function AgentGraph(props: AgentGraphProps) {
  return (
    <ReactFlowProvider>
      <AgentGraphCanvas {...props} />
    </ReactFlowProvider>
  );
}
