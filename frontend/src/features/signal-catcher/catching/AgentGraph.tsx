"use client";

import { Graph, layout, type EdgeLabel, type GraphLabel, type NodeLabel } from "@dagrejs/dagre";
import {
  BaseEdge,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  getSmoothStepPath,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { memo, useEffect, useMemo, useRef, useState } from "react";

import "@xyflow/react/dist/style.css";

import type { CatchSession, StageKey, StageTick } from "../state/types";

import {
  createAgentTopology,
  type AgentTopology,
  type AgentTopologyNode,
  type SignalEdgeState,
} from "./agent-topology";
import styles from "./catching.module.css";

const NODE_WIDTH = 132;
const NODE_HEIGHT = 78;

type LayoutDirection = "LR" | "TB";
type AgentNodeData = AgentTopologyNode & {
  direction: LayoutDirection;
} & Record<string, unknown>;
type AgentFlowNode = Node<AgentNodeData, "agent">;
type SignalEdgeData = {
  state: SignalEdgeState;
  halted: boolean;
  speed: number;
} & Record<string, unknown>;
type SignalFlowEdge = Edge<SignalEdgeData, "signal">;

interface AgentGraphProps {
  session: CatchSession;
  log: (StageTick & { stage: StageKey })[];
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
      role="listitem"
      aria-label={`${data.label}, ${data.meta}`}
    >
      <Handle
        className={styles.handle}
        type="target"
        position={horizontal ? Position.Left : Position.Top}
        isConnectable={false}
      />
      <span className={styles.orb} aria-hidden="true">{data.mark}</span>
      <span className={styles.nodeLabel}>{data.label}</span>
      <span className={styles.nodeMeta}>{data.meta}</span>
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
    nodesep: direction === "LR" ? 20 : 14,
    edgesep: 12,
    ranksep: direction === "LR" ? 62 : 44,
    marginx: 16,
    marginy: 16,
  });
  graph.setDefaultEdgeLabel(() => ({}));

  for (const node of topology.nodes) {
    graph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const edge of topology.edges) {
    graph.setEdge(edge.source, edge.target);
  }

  layout(graph);

  const nodes: AgentFlowNode[] = topology.nodes.map((node) => {
    const position = graph.node(node.id);
    return {
      id: node.id,
      type: "agent",
      data: { ...node, direction } as AgentNodeData,
      position: {
        x: (position.x ?? 0) - NODE_WIDTH / 2,
        y: (position.y ?? 0) - NODE_HEIGHT / 2,
      },
      sourcePosition: direction === "LR" ? Position.Right : Position.Bottom,
      targetPosition: direction === "LR" ? Position.Left : Position.Top,
      draggable: false,
      selectable: false,
      connectable: false,
      focusable: false,
      className: styles.flowNode,
      style: { width: NODE_WIDTH, height: NODE_HEIGHT },
    };
  });
  const edges: SignalFlowEdge[] = topology.edges.map((edge) => ({
    ...edge,
    type: "signal",
    data: { state: edge.state, halted, speed },
    selectable: false,
    focusable: false,
  }));

  return { nodes, edges };
}

function useLayoutDirection(): LayoutDirection {
  const [direction, setDirection] = useState<LayoutDirection>(() =>
    window.matchMedia("(max-width: 700px)").matches ? "TB" : "LR",
  );

  useEffect(() => {
    const query = window.matchMedia("(max-width: 700px)");
    const updateDirection = () => setDirection(query.matches ? "TB" : "LR");
    query.addEventListener("change", updateDirection);
    return () => query.removeEventListener("change", updateDirection);
  }, []);

  return direction;
}

function AgentGraphCanvas({ session, log, halted, speed }: AgentGraphProps) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const direction = useLayoutDirection();
  const topology = useMemo(() => createAgentTopology(session, log), [session, log]);
  const { nodes, edges } = useMemo(
    () => layoutTopology(topology, halted, speed, direction),
    [topology, halted, speed, direction],
  );
  const topologyKey = `${direction}|${nodes.map((node) => node.id).join(",")}|${edges.map((edge) => edge.id).join(",")}`;
  const { fitView } = useReactFlow<AgentFlowNode, SignalFlowEdge>();

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    let frame = 0;
    const refit = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        void fitView({ padding: 0.16, duration: 420, maxZoom: 1.12 });
      });
    };
    const observer = new ResizeObserver(refit);
    observer.observe(canvas);
    refit();

    return () => {
      observer.disconnect();
      window.cancelAnimationFrame(frame);
    };
  }, [fitView, topologyKey]);

  return (
    <div
      ref={canvasRef}
      className={styles.canvas}
      data-halted={halted}
      role="list"
      aria-label="멀티에이전트 실행 토폴로지"
    >
      <ReactFlow<AgentFlowNode, SignalFlowEdge>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        fitViewOptions={{ padding: 0.16, maxZoom: 1.12 }}
        minZoom={0.28}
        maxZoom={1.35}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        preventScrolling={false}
      />
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
