/** Public execution activity. Raw model/provider data is never part of this contract. */
export interface AgentActivity {
  schema_version: 1;
  node_id: string;
  parent_node_id: string | null;
  depends_on: string[];
  kind: "agent" | "model" | "tool" | "assessment";
  role: "coordinator" | "investigator" | "verifier" | "reporter";
  task_id: string;
  round_index: number;
  status: "queued" | "started" | "completed" | "failed" | "cancelled";
  name: string;
  display_text: string;
  message_kind?: "commentary" | "summary" | null;
  message_text?: string | null;
  occurred_at: string;
  duration_ms: number | null;
  model: string | null;
  details: ActivityDetails;
}

export interface ActivityDetails {
  query_id?: string | null;
  measurement_id?: string | null;
  candidate_id?: string | null;
  error_code?: string | null;
  row_count?: number | null;
  event_count?: number | null;
  customer_count?: number | null;
  table_count?: number | null;
  item_count?: number | null;
  tool_count?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  truncated?: boolean | null;
  candidates: {
    candidate_id: string; title: string; cohort_query_id: string; evidence_query_ids: string[];
  }[];
  decisions: {
    candidate_id: string;
    verdict: "confirmed" | "candidate" | "rejected" | "reinvestigate";
    reason: string;
    cohort_query_id?: string | null;
    evidence_query_ids: string[];
    followup_question?: string | null;
  }[];
  limitations: string[];
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid activity object");
  return value as Record<string, unknown>;
}
function text(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) throw new Error("invalid activity text");
  return value;
}
function integer(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) throw new Error("invalid activity number");
  return value;
}
function list<T>(value: unknown, decode: (v: unknown) => T): T[] {
  if (!Array.isArray(value)) throw new Error("invalid activity list");
  return value.map(decode);
}
function choice<const T extends readonly string[]>(value: unknown, choices: T): T[number] {
  const result = text(value);
  if (!choices.includes(result)) throw new Error("invalid activity choice");
  return result as T[number];
}

export function decodeAgentActivity(value: unknown): AgentActivity {
  const p = object(value);
  if (p.schema_version !== 1) throw new Error("unsupported activity version");
  const occurred_at = text(p.occurred_at);
  if (!Number.isFinite(Date.parse(occurred_at))) throw new Error("invalid activity timestamp");
  const d = object(p.details);
  const details: ActivityDetails = {
    candidates: list(d.candidates, value => {
      const c = object(value);
      return { candidate_id: text(c.candidate_id), title: text(c.title),
        cohort_query_id: text(c.cohort_query_id), evidence_query_ids: list(c.evidence_query_ids, text) };
    }),
    decisions: list(d.decisions, value => {
      const c = object(value);
      return { candidate_id: text(c.candidate_id),
        verdict: choice(c.verdict, ["confirmed", "candidate", "rejected", "reinvestigate"]),
        reason: text(c.reason), cohort_query_id: c.cohort_query_id == null ? null : text(c.cohort_query_id),
        evidence_query_ids: list(c.evidence_query_ids, text),
        followup_question: c.followup_question == null ? null : text(c.followup_question) };
    }),
    limitations: list(d.limitations, text),
  };
  for (const key of ["query_id", "measurement_id", "candidate_id", "error_code"] as const) {
    if (key in d) details[key] = d[key] === null ? null : text(d[key]);
  }
  for (const key of ["row_count", "event_count", "customer_count", "table_count", "item_count", "tool_count", "input_tokens", "output_tokens"] as const) {
    if (key in d) details[key] = d[key] === null ? null : integer(d[key]);
  }
  if ("truncated" in d) {
    if (d.truncated !== null && typeof d.truncated !== "boolean") throw new Error("invalid truncated flag");
    details.truncated = d.truncated;
  }
  return {
    schema_version: 1, node_id: text(p.node_id),
    parent_node_id: p.parent_node_id === null ? null : text(p.parent_node_id),
    depends_on: list(p.depends_on, text), kind: choice(p.kind, ["agent", "model", "tool", "assessment"]),
    role: choice(p.role, ["coordinator", "investigator", "verifier", "reporter"]),
    task_id: text(p.task_id), round_index: integer(p.round_index),
    status: choice(p.status, ["queued", "started", "completed", "failed", "cancelled"]),
    name: text(p.name), display_text: text(p.display_text), occurred_at,
    ...("message_kind" in p ? {
      message_kind: p.message_kind == null ? null : choice(p.message_kind, ["commentary", "summary"]),
    } : {}),
    ...("message_text" in p ? { message_text: p.message_text == null ? null : text(p.message_text) } : {}),
    duration_ms: p.duration_ms === null ? null : integer(p.duration_ms),
    model: p.model === null ? null : text(p.model), details,
  };
}
