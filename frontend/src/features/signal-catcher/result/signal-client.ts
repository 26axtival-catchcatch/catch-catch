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
  limitations: string[];
  sourceIds: string[];
  populationDescription: string;
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
  windowSeconds: number;
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

export type RegistrySignalStatus = "active" | "paused" | "archived";

export interface RegistrySignal {
  signalId: string;
  title: string;
  description: string;
  status: RegistrySignalStatus;
  origin: "analysis" | "user_defined";
  createdAt: string;
  sourceIds: string[];
  populationDescription: string;
}

export interface RegistryMetricValue {
  key: string;
  label: string;
  value: number | null;
  unit: string;
}

export interface SignalMeasurement {
  measurementId: string;
  startAt: string;
  endAt: string;
  measuredAt: string;
  status: "success" | "unavailable";
  reason: string | null;
  values: RegistryMetricValue[];
}

export interface DailySchedule {
  signalId: string;
  enabled: boolean;
  nextRunAt: string;
  updatedAt: string;
  signalStatus: RegistrySignalStatus;
}

export interface DailyResult {
  executionId: string;
  startAt: string;
  endAt: string;
  status: "running" | "success" | "unavailable";
  measurement: SignalMeasurement | null;
}

export interface DailyResults {
  items: DailyResult[];
  nextBefore: string | null;
  pendingDays: number;
}

export interface FastForwardResult {
  requestId: string;
  items: Array<{
    signalId: string;
    status: "completed" | "skipped";
    reason: string | null;
    dailyResults: DailyResult[];
    alertCount: number;
  }>;
}

export interface MeasurementHistory {
  items: SignalMeasurement[];
  latestByWindow: SignalMeasurement[];
  comparable: boolean;
  limitations: string[];
}

export interface MetricChange {
  key: string;
  label: string;
  unit: string;
  baselineValue: number;
  targetValue: number;
  absoluteChange: number;
  changeUnit: string;
  relativeChangePercent: number | null;
}

export interface MeasurementComparison {
  baseline: SignalMeasurement | null;
  target: SignalMeasurement | null;
  comparable: boolean;
  limitations: string[];
  metrics: MetricChange[];
}

export interface AlertEvent {
  sequence: number;
  eventId: string;
  signalId: string;
  signalTitle: string;
  rule: AlertRecommendation & { ruleId: string };
  observedValue: number;
  metricValue: number;
  baselineValue: number | null;
  occurredAt: string;
}

export interface AlertEventPage {
  items: AlertEvent[];
  nextCursor: number;
  latestCursor: number;
  hasMore: boolean;
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

function booleanOf(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") throw new SignalClientError(`${path} 응답 형식이 올바르지 않습니다.`);
  return value;
}

function stringArrayOf(value: unknown, path: string): string[] {
  if (!Array.isArray(value)) throw new SignalClientError(`${path} 응답 형식이 올바르지 않습니다.`);
  return value.map((item, index) => stringOf(item, `${path}[${index}]`));
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
  const definition = recordOf(proposal.definition, `${path}.definition`);
  if (!Array.isArray(measurement.values)) {
    throw new SignalClientError(`${path}.measurement.values 응답 형식이 올바르지 않습니다.`);
  }
  return {
    proposalId: stringOf(proposal.proposal_id, `${path}.proposal_id`),
    title: stringOf(proposal.title, `${path}.title`),
    description: stringOf(proposal.description, `${path}.description`),
    limitations: stringArrayOf(proposal.limitations, `${path}.limitations`),
    sourceIds: stringArrayOf(definition.source_ids, `${path}.definition.source_ids`),
    populationDescription: stringOf(definition.population_description, `${path}.definition.population_description`),
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
    windowSeconds: numberOf(item.window_seconds, `${path}.window_seconds`),
    rationale: stringOf(item.rationale, `${path}.rationale`),
  };
}

function registryMetricOf(value: unknown, path: string): RegistryMetricValue {
  const metric = recordOf(value, path);
  return {
    key: stringOf(metric.key, `${path}.key`),
    label: stringOf(metric.label, `${path}.label`),
    value: metric.value === null ? null : numberOf(metric.value, `${path}.value`),
    unit: stringOf(metric.unit, `${path}.unit`),
  };
}

function measurementOf(value: unknown, path: string): SignalMeasurement {
  const measurement = recordOf(value, path);
  if (!Array.isArray(measurement.values)) throw new SignalClientError(`${path}.values 응답 형식이 올바르지 않습니다.`);
  return {
    measurementId: stringOf(measurement.measurement_id, `${path}.measurement_id`),
    startAt: stringOf(measurement.start_at, `${path}.start_at`),
    endAt: stringOf(measurement.end_at, `${path}.end_at`),
    measuredAt: stringOf(measurement.measured_at, `${path}.measured_at`),
    status: oneOf(measurement.status, ["success", "unavailable"], `${path}.status`),
    reason: measurement.reason === null ? null : stringOf(measurement.reason, `${path}.reason`),
    values: measurement.values.map((item, index) => registryMetricOf(item, `${path}.values[${index}]`)),
  };
}

function registrySignalOf(value: unknown, path: string): RegistrySignal {
  const item = recordOf(value, path);
  const definition = recordOf(item.definition, `${path}.definition`);
  return {
    signalId: stringOf(item.signal_id, `${path}.signal_id`),
    title: stringOf(item.title, `${path}.title`),
    description: stringOf(item.description, `${path}.description`),
    status: oneOf(item.status, ["active", "paused", "archived"], `${path}.status`),
    origin: oneOf(item.origin, ["analysis", "user_defined"], `${path}.origin`),
    createdAt: stringOf(item.created_at, `${path}.created_at`),
    sourceIds: stringArrayOf(definition.source_ids, `${path}.definition.source_ids`),
    populationDescription: stringOf(definition.population_description, `${path}.definition.population_description`),
  };
}

function scheduleOf(value: unknown, path: string): DailySchedule {
  const item = recordOf(value, path);
  return {
    signalId: stringOf(item.signal_id, `${path}.signal_id`),
    enabled: booleanOf(item.enabled, `${path}.enabled`),
    nextRunAt: stringOf(item.next_run_at, `${path}.next_run_at`),
    updatedAt: stringOf(item.updated_at, `${path}.updated_at`),
    signalStatus: oneOf(item.signal_status, ["active", "paused", "archived"], `${path}.signal_status`),
  };
}

function dailyResultsOf(value: unknown, path: string): DailyResults {
  const page = recordOf(value, path);
  if (!Array.isArray(page.items)) throw new SignalClientError(`${path}.items 응답 형식이 올바르지 않습니다.`);
  return {
    items: page.items.map((value, index) => {
      const item = recordOf(value, `${path}.items[${index}]`);
      return {
        executionId: stringOf(item.execution_id, `${path}.items[${index}].execution_id`),
        startAt: stringOf(item.start_at, `${path}.items[${index}].start_at`),
        endAt: stringOf(item.end_at, `${path}.items[${index}].end_at`),
        status: oneOf(item.status, ["running", "success", "unavailable"], `${path}.items[${index}].status`),
        measurement: item.measurement === null ? null : measurementOf(item.measurement, `${path}.items[${index}].measurement`),
      };
    }),
    nextBefore: page.next_before === null ? null : stringOf(page.next_before, `${path}.next_before`),
    pendingDays: numberOf(page.pending_days, `${path}.pending_days`),
  };
}

function historyOf(value: unknown, path: string): MeasurementHistory {
  const history = recordOf(value, path);
  if (!Array.isArray(history.items) || !Array.isArray(history.latest_by_window)) {
    throw new SignalClientError(`${path} 응답 형식이 올바르지 않습니다.`);
  }
  return {
    items: history.items.map((item, index) => measurementOf(item, `${path}.items[${index}]`)),
    latestByWindow: history.latest_by_window.map((item, index) => measurementOf(item, `${path}.latest_by_window[${index}]`)),
    comparable: booleanOf(history.comparable, `${path}.comparable`),
    limitations: stringArrayOf(history.comparison_limitations, `${path}.comparison_limitations`),
  };
}

function comparisonOf(value: unknown, path: string): MeasurementComparison {
  const item = recordOf(value, path);
  if (!Array.isArray(item.comparison_limitations) || !Array.isArray(item.metrics)) {
    throw new SignalClientError(`${path} 응답 형식이 올바르지 않습니다.`);
  }
  return {
    baseline: item.baseline === null ? null : measurementOf(item.baseline, `${path}.baseline`),
    target: item.target === null ? null : measurementOf(item.target, `${path}.target`),
    comparable: booleanOf(item.comparable, `${path}.comparable`),
    limitations: stringArrayOf(item.comparison_limitations, `${path}.comparison_limitations`),
    metrics: item.metrics.map((value, index) => {
      const metric = recordOf(value, `${path}.metrics[${index}]`);
      return {
        key: stringOf(metric.key, `${path}.metrics[${index}].key`),
        label: stringOf(metric.label, `${path}.metrics[${index}].label`),
        unit: stringOf(metric.unit, `${path}.metrics[${index}].unit`),
        baselineValue: numberOf(metric.baseline_value, `${path}.metrics[${index}].baseline_value`),
        targetValue: numberOf(metric.target_value, `${path}.metrics[${index}].target_value`),
        absoluteChange: numberOf(metric.absolute_change, `${path}.metrics[${index}].absolute_change`),
        changeUnit: stringOf(metric.change_unit, `${path}.metrics[${index}].change_unit`),
        relativeChangePercent: metric.relative_change_percent === null
          ? null
          : numberOf(metric.relative_change_percent, `${path}.metrics[${index}].relative_change_percent`),
      };
    }),
  };
}

function alertEventPageOf(value: unknown, path: string): AlertEventPage {
  const page = recordOf(value, path);
  if (!Array.isArray(page.items)) throw new SignalClientError(`${path}.items 응답 형식이 올바르지 않습니다.`);
  return {
    items: page.items.map((value, index) => {
      const item = recordOf(value, `${path}.items[${index}]`);
      const rule = recordOf(item.rule, `${path}.items[${index}].rule`);
      return {
        sequence: numberOf(item.sequence, `${path}.items[${index}].sequence`),
        eventId: stringOf(item.event_id, `${path}.items[${index}].event_id`),
        signalId: stringOf(item.signal_id, `${path}.items[${index}].signal_id`),
        signalTitle: stringOf(item.signal_title, `${path}.items[${index}].signal_title`),
        rule: {
          ...recommendationOf(rule, `${path}.items[${index}].rule`),
          ruleId: stringOf(rule.rule_id, `${path}.items[${index}].rule.rule_id`),
        },
        observedValue: numberOf(item.observed_value, `${path}.items[${index}].observed_value`),
        metricValue: numberOf(item.metric_value, `${path}.items[${index}].metric_value`),
        baselineValue: item.baseline_value === null ? null : numberOf(item.baseline_value, `${path}.items[${index}].baseline_value`),
        occurredAt: stringOf(item.occurred_at, `${path}.items[${index}].occurred_at`),
      };
    }),
    nextCursor: numberOf(page.next_cursor, `${path}.next_cursor`),
    latestCursor: numberOf(page.latest_cursor, `${path}.latest_cursor`),
    hasMore: booleanOf(page.has_more, `${path}.has_more`),
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

  async fastForward(requestId: string): Promise<FastForwardResult> {
    const response = await this.request("/api/signals/fast-forward", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request_id: requestId, days: 1 }),
    });
    const payload = recordOf(await response.json(), "fast-forward");
    if (!Array.isArray(payload.items)) throw new SignalClientError("빨리감기 응답 형식이 올바르지 않습니다.");
    return {
      requestId: stringOf(payload.request_id, "fast-forward.request_id"),
      items: payload.items.map((value, index) => {
        const path = `fast-forward.items[${index}]`;
        const item = recordOf(value, path);
        if (!Array.isArray(item.alert_events)) throw new SignalClientError("빨리감기 알림 응답 형식이 올바르지 않습니다.");
        return {
          signalId: stringOf(item.signal_id, `${path}.signal_id`),
          status: oneOf(item.status, ["completed", "skipped"], `${path}.status`),
          reason: nullableStringOf(item.reason, `${path}.reason`),
          dailyResults: dailyResultsOf({ items: item.daily_results, next_before: null, pending_days: 0 }, path).items,
          alertCount: item.alert_events.length,
        };
      }),
    };
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

  async registerProposal(proposalId: string, signal?: AbortSignal): Promise<RegisteredSignal> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.apiBaseUrl}/api/signals`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ proposal_id: proposalId }),
        ...(signal ? { signal } : {}),
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
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

  async getAlertRules(signalId: string, signal?: AbortSignal): Promise<AlertRules> {
    const response = await this.request(
      `/api/signals/${encodeURIComponent(signalId)}/alert-rules`,
      signal ? { signal } : undefined,
    );
    return rulesOf(await response.json(), "alert-rules");
  }

  async getAlertRecommendations(signalId: string, signal?: AbortSignal): Promise<AlertRecommendationSet | null> {
    const response = await this.request(
      `/api/signals/${encodeURIComponent(signalId)}/alert-recommendations`,
      signal ? { signal } : undefined,
    );
    const payload: unknown = await response.json();
    return payload === null ? null : recommendationSetOf(payload, "alert-recommendations");
  }

  async generateAlertRecommendations(signalId: string, signal?: AbortSignal): Promise<AlertRecommendationSet> {
    const response = await this.request(
      `/api/signals/${encodeURIComponent(signalId)}/alert-recommendations`,
      { method: "POST", ...(signal ? { signal } : {}) },
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

  async getSignal(signalId: string, signal?: AbortSignal): Promise<RegistrySignal> {
    const response = await this.request(`/api/signals/${encodeURIComponent(signalId)}`, { signal });
    return registrySignalOf(await response.json(), "signal");
  }

  async updateSignalStatus(signalId: string, status: RegistrySignalStatus): Promise<RegistrySignal> {
    const response = await this.request(`/api/signals/${encodeURIComponent(signalId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    return registrySignalOf(await response.json(), "signal");
  }

  async getSchedule(signalId: string, signal?: AbortSignal): Promise<DailySchedule> {
    const response = await this.request(`/api/signals/${encodeURIComponent(signalId)}/schedule`, { signal });
    return scheduleOf(await response.json(), "schedule");
  }

  async updateSchedule(signalId: string, enabled: boolean, nextRunAt?: string): Promise<DailySchedule> {
    const response = await this.request(`/api/signals/${encodeURIComponent(signalId)}/schedule`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled, ...(nextRunAt ? { next_run_at: nextRunAt } : {}) }),
    });
    return scheduleOf(await response.json(), "schedule");
  }

  async measure(signalId: string, startAt: string, endAt: string): Promise<SignalMeasurement> {
    const response = await this.request(`/api/signals/${encodeURIComponent(signalId)}/measurements`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start_at: startAt, end_at: endAt }),
    });
    return measurementOf(await response.json(), "measurement");
  }

  async getDailyResults(signalId: string, before?: string, signal?: AbortSignal): Promise<DailyResults> {
    const query = new URLSearchParams({ limit: "30" });
    if (before) query.set("before", before);
    const response = await this.request(
      `/api/signals/${encodeURIComponent(signalId)}/daily-results?${query}`,
      { signal },
    );
    return dailyResultsOf(await response.json(), "daily-results");
  }

  async getMeasurementHistory(signalId: string, signal?: AbortSignal): Promise<MeasurementHistory> {
    const response = await this.request(`/api/signals/${encodeURIComponent(signalId)}/measurements`, { signal });
    return historyOf(await response.json(), "measurements");
  }

  async getComparison(
    signalId: string,
    signal?: AbortSignal,
    selection?: { baselineId: string; targetId: string },
  ): Promise<MeasurementComparison> {
    const query = selection
      ? `?${new URLSearchParams({ baseline_measurement_id: selection.baselineId, target_measurement_id: selection.targetId })}`
      : "";
    const response = await this.request(`/api/signals/${encodeURIComponent(signalId)}/comparison${query}`, { signal });
    return comparisonOf(await response.json(), "comparison");
  }

  async getAlertEvents(after: number | null, signal?: AbortSignal): Promise<AlertEventPage> {
    const query = after === null ? "" : `?after=${after}&limit=100`;
    const response = await this.request(`/api/signal-alert-events${query}`, { signal });
    return alertEventPageOf(await response.json(), "signal-alert-events");
  }

  private async request(path: string, init?: RequestInit): Promise<Response> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.apiBaseUrl}${path}`, init);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      throw new SignalClientError("시그널 요청을 완료하지 못했습니다.");
    }
    if (!response.ok) throw new SignalClientError(await errorMessage(response), response.status);
    return response;
  }
}
