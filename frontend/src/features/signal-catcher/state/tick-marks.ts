import type { StageTick } from "./types";

/** primitive 마다 다른 기호를 준다. 같은 도구를 다시 부른 것이 눈에 띄어야 한다. */
const PRIMITIVE_MARK: Record<string, string> = {
  catalog_sources: "⌘",
  aggregate_events: "∑",
  build_segment: "◑",
  match_sequence: "⇄",
  profile_customers: "◎",
  validate_claims: "✓",
};

const KIND_MARK: Record<StageTick["kind"], string> = {
  think: "✎",
  tool: "•",
  fact: "◈",
  reject: "✕",
};

/**
 * 진행 문장 하나에 붙는 기호.
 * 분석 중 흘러가는 레일과 결과 화면에서 다시 펼쳐 보는 과정이 같은 기호를 써야
 * 로딩 때 스쳐 지나간 줄을 나중에 그대로 알아볼 수 있다.
 */
export function markOf(entry: StageTick): string {
  if (entry.kind !== "tool") return KIND_MARK[entry.kind];
  return (entry.primitive && PRIMITIVE_MARK[entry.primitive]) ?? KIND_MARK.tool;
}
