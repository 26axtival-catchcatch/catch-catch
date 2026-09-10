import { DEFAULT_API_BASE_URL } from "../../customer-intelligence/run-client";

export interface SignalMetricValue {
  key: string;
  label: string;
  value: number;
  unit: string;
}

export interface SignalProposal {
  proposalId: string;
  title: string;
  description: string;
  metrics: SignalMetricValue[];
}

export interface RegisteredSignal {
  signalId: string;
  proposalId: string | null;
  alertRecommendations: AlertRecommendationSet | null;
}

export type AlertOperator = "gt" | "gte" | "lt" | "lte";
export type AlertKind = "value" | "absolute_change" | "relative_change_percent";

export interface AlertRecommendation {
  recommendationId: string;
  metricKey: string;
  metricLabel: string;
  metricUnit: string;
  kind: AlertKind;
  operator: AlertOperator;
  threshold: number;
  comparisonUnit: string;
  rationale: string;
}

export interface AlertRecommendationSet {
  status: "ready" | "unavailable";
  source: "model" | "fixture";
  items: AlertRecommendation[];
  reason: string | null;
}

export interface AlertRules {
  signalId: string;
  revision: number;
  items: Array<AlertRecommendation & { ruleId: string }>;
}

interface SignalClientOptions {
  apiBaseUrl?: string;
  fetchImpl?: typeof fetch;
}

export class SignalClientError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = "SignalClientError";
  }
}

function recordOf(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new SignalClientError(`${path} 응답 형식이 올바르지 않습니다.`);
  }
  return value as Record<string, unknown>;
}

function stringOf(value: unknown, path: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new SignalClientError(`${path} 응답 형식이 올바르지 않습니다.`);
  }
  return value;
}

function nullableStringOf(value: unknown, path: string): string | null {
  return value === null ? null : stringOf(value, path);
}

function numberOf(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new SignalClientError(`${path} 응답 형식이 올바르지 않습니다.`);
  }
  return value;
}

function oneOf<const Value extends string>(
  value: unknown,
  allowed: readonly Value[],
  path: string,
): Value {
  if (typeof value !== "string" || !allowed.includes(value as Value)) {
    throw new SignalClientError(`${path} 응답 형식이 올바르지 않습니다.`);
  }
  return value as Value;
}

function metricOf(value: unknown, path: string): SignalMetricValue | null {
  const metric = recordOf(value, path);
  if (metric.value === null) return null;
  if (typeof metric.value !== "number" || !Number.isFinite(metric.value)) {
    throw new SignalClientError(`${path}.value 응답 형식이 올바르지 않습니다.`);
  }
  return {
    key: stringOf(metric.key, `${path}.key`),
    label: stringOf(metric.label, `${path}.label`),
    value: metric.value,
    unit: stringOf(metric.unit, `${path}.unit`),
  };
}

function proposalOf(value: unknown, path: string): SignalProposal {
  const proposal = recordOf(value, path);
  const measurement = recordOf(proposal.measurement, `${path}.measurement`);
  if (!Array.isArray(measurement.values)) {
    throw new SignalClientError(`${path}.measurement.values 응답 형식이 올바르지 않습니다.`);
  }
  return {
    proposalId: stringOf(proposal.proposal_id, `${path}.proposal_id`),
    title: stringOf(proposal.title, `${path}.title`),
    description: stringOf(proposal.description, `${path}.description`),
    metrics: measurement.values
      .map((metric, index) => metricOf(metric, `${path}.measurement.values[${index}]`))
      .filter((metric): metric is SignalMetricValue => metric !== null),
  };
}

function recommendationOf(value: unknown, path: string): AlertRecommendation {
  const item = recordOf(value, path);
  return {
    recommendationId: stringOf(item.recommendation_id, `${path}.recommendation_id`),
    metricKey: stringOf(item.metric_key, `${path}.metric_key`),
    metricLabel: stringOf(item.metric_label, `${path}.metric_label`),
    metricUnit: stringOf(item.metric_unit, `${path}.metric_unit`),
    kind: oneOf(item.kind, ["value", "absolute_change", "relative_change_percent"], `${path}.kind`),
    operator: oneOf(item.operator, ["gt", "gte", "lt", "lte"], `${path}.operator`),
    threshold: numberOf(item.threshold, `${path}.threshold`),
    comparisonUnit: stringOf(item.comparison_unit, `${path}.comparison_unit`),
    rationale: stringOf(item.rationale, `${path}.rationale`),
  };
}

function recommendationSetOf(value: unknown, path: string): AlertRecommendationSet {
  const set = recordOf(value, path);
  if (!Array.isArray(set.items)) {
    throw new SignalClientError(`${path}.items 응답 형식이 올바르지 않습니다.`);
  }
  return {
    status: oneOf(set.status, ["ready", "unavailable"], `${path}.status`),
    source: oneOf(set.source, ["model", "fixture"], `${path}.source`),
    items: set.items.map((item, index) => recommendationOf(item, `${path}.items[${index}]`)),
    reason: set.reason === null ? null : stringOf(set.reason, `${path}.reason`),
  };
}

function rulesOf(value: unknown, path: string): AlertRules {
  const rules = recordOf(value, path);
  if (!Array.isArray(rules.items)) {
    throw new SignalClientError(`${path}.items 응답 형식이 올바르지 않습니다.`);
  }
  return {
    signalId: stringOf(rules.signal_id, `${path}.signal_id`),
    revision: numberOf(rules.revision, `${path}.revision`),
    items: rules.items.map((item, index) => {
      const record = recordOf(item, `${path}.items[${index}]`);
      return {
        ...recommendationOf(record, `${path}.items[${index}]`),
        ruleId: stringOf(record.rule_id, `${path}.items[${index}].rule_id`),
      };
    }),
  };
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const payload = recordOf(await response.json(), "error");
    if (typeof payload.detail === "string") return payload.detail;
  } catch {
    // JSON 오류도 HTTP 상태를 포함한 공통 문장으로 처리한다.
  }
  return `요청을 완료하지 못했습니다. (${response.status})`;
}

export class SignalClient {
  private readonly apiBaseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: SignalClientOptions = {}) {
    this.apiBaseUrl = (options.apiBaseUrl ?? DEFAULT_API_BASE_URL).replace(/\/$/, "");
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  }

  async listProposals(runId: string, signal?: AbortSignal): Promise<SignalProposal[]> {
    let response: Response;
    try {
      response = await this.fetchImpl(
        `${this.apiBaseUrl}/api/signal-proposals?run_id=${encodeURIComponent(runId)}`,
        { signal },
      );
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      throw new SignalClientError("변화 추적 후보를 불러오지 못했습니다.");
    }
    if (!response.ok) throw new SignalClientError(await errorMessage(response), response.status);
    const payload = recordOf(await response.json(), "signal-proposals");
    if (!Array.isArray(payload.items)) {
      throw new SignalClientError("signal-proposals.items 응답 형식이 올바르지 않습니다.");
    }
    return payload.items.map((item, index) => proposalOf(item, `signal-proposals.items[${index}]`));
  }

  async registerProposal(proposalId: string): Promise<RegisteredSignal> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.apiBaseUrl}/api/signals`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ proposal_id: proposalId }),
      });
    } catch {
      throw new SignalClientError("변화 캐치를 시작하지 못했습니다.");
    }
    if (!response.ok) throw new SignalClientError(await errorMessage(response), response.status);
    const payload = recordOf(await response.json(), "signal");
    const recommendations = payload.alert_recommendations;
    return {
      signalId: stringOf(payload.signal_id, "signal.signal_id"),
      proposalId: nullableStringOf(payload.proposal_id, "signal.proposal_id"),
      alertRecommendations: recommendations == null
        ? null
        : recommendationSetOf(recommendations, "signal.alert_recommendations"),
    };
  }

  async getAlertRules(signalId: string): Promise<AlertRules> {
    const response = await this.request(
      `/api/signals/${encodeURIComponent(signalId)}/alert-rules`,
    );
    return rulesOf(await response.json(), "alert-rules");
  }

  async generateAlertRecommendations(signalId: string): Promise<AlertRecommendationSet> {
    const response = await this.request(
      `/api/signals/${encodeURIComponent(signalId)}/alert-recommendations`,
      { method: "POST" },
    );
    return recommendationSetOf(await response.json(), "alert-recommendations");
  }

  async replaceAlertRules(
    signalId: string,
    revision: number,
    items: Array<{ recommendationId: string; threshold: number }>,
  ): Promise<AlertRules> {
    const response = await this.request(
      `/api/signals/${encodeURIComponent(signalId)}/alert-rules`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          revision,
          items: items.map((item) => ({
            recommendation_id: item.recommendationId,
            threshold: item.threshold,
          })),
        }),
      },
    );
    return rulesOf(await response.json(), "alert-rules");
  }

  private async request(path: string, init?: RequestInit): Promise<Response> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.apiBaseUrl}${path}`, init);
    } catch {
      throw new SignalClientError("알림 기준 요청을 완료하지 못했습니다.");
    }
    if (!response.ok) throw new SignalClientError(await errorMessage(response), response.status);
    return response;
  }
}
