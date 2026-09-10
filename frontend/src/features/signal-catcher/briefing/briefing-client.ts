import { DEFAULT_API_BASE_URL } from "../../customer-intelligence/run-client";

import type { Briefing, BriefingMetric, BriefingSignal } from "./types";

interface ApiMetric {
  key: string;
  label: string;
  value: number | null;
  unit: string;
}

interface ApiMeasurement {
  startAt: string;
  endAt: string;
  status: "success" | "unavailable";
  reason: string | null;
  values: ApiMetric[];
}

interface ApiMetricChange {
  key: string;
  absoluteChange: number;
  changeUnit: string;
}

interface ApiBriefingSignal {
  signalId: string;
  title: string;
  description: string;
  sourceIds: string[];
  populationDescription: string;
  latestMeasurement: ApiMeasurement | null;
  comparable: boolean;
  comparisonLimitations: string[];
  changes: ApiMetricChange[];
  trendComparable: boolean;
  points: ApiMeasurement[];
}

export class BriefingClientError extends Error {
  constructor(message: string, readonly status?: number) {
    super(message);
    this.name = "BriefingClientError";
  }
}

function recordOf(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new BriefingClientError(`${path} 응답 형식이 올바르지 않습니다.`);
  }
  return value as Record<string, unknown>;
}

function stringOf(value: unknown, path: string): string {
  if (typeof value !== "string") throw new BriefingClientError(`${path} 응답 형식이 올바르지 않습니다.`);
  return value;
}

function numberOf(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new BriefingClientError(`${path} 응답 형식이 올바르지 않습니다.`);
  }
  return value;
}

function stringArrayOf(value: unknown, path: string): string[] {
  if (!Array.isArray(value)) throw new BriefingClientError(`${path} 응답 형식이 올바르지 않습니다.`);
  return value.map((item, index) => stringOf(item, `${path}[${index}]`));
}

function metricOf(value: unknown, path: string): ApiMetric {
  const metric = recordOf(value, path);
  return {
    key: stringOf(metric.key, `${path}.key`),
    label: stringOf(metric.label, `${path}.label`),
    value: metric.value === null ? null : numberOf(metric.value, `${path}.value`),
    unit: stringOf(metric.unit, `${path}.unit`),
  };
}

function measurementOf(value: unknown, path: string): ApiMeasurement {
  const measurement = recordOf(value, path);
  if (!Array.isArray(measurement.values)) {
    throw new BriefingClientError(`${path}.values 응답 형식이 올바르지 않습니다.`);
  }
  if (measurement.status !== "success" && measurement.status !== "unavailable") {
    throw new BriefingClientError(`${path}.status 응답 형식이 올바르지 않습니다.`);
  }
  return {
    startAt: stringOf(measurement.start_at, `${path}.start_at`),
    endAt: stringOf(measurement.end_at, `${path}.end_at`),
    status: measurement.status,
    reason: measurement.reason === null ? null : stringOf(measurement.reason, `${path}.reason`),
    values: measurement.values.map((item, index) => metricOf(item, `${path}.values[${index}]`)),
  };
}

function signalOf(value: unknown, path: string): ApiBriefingSignal {
  const signal = recordOf(value, path);
  const comparison = recordOf(signal.comparison, `${path}.comparison`);
  const trend = recordOf(signal.trend, `${path}.trend`);
  if (!Array.isArray(comparison.metrics) || !Array.isArray(trend.points)) {
    throw new BriefingClientError(`${path} 응답 형식이 올바르지 않습니다.`);
  }
  return {
    signalId: stringOf(signal.signal_id, `${path}.signal_id`),
    title: stringOf(signal.title, `${path}.title`),
    description: stringOf(signal.description, `${path}.description`),
    sourceIds: stringArrayOf(signal.source_ids, `${path}.source_ids`),
    populationDescription: stringOf(signal.population_description, `${path}.population_description`),
    latestMeasurement: signal.latest_measurement === null
      ? null
      : measurementOf(signal.latest_measurement, `${path}.latest_measurement`),
    comparable: comparison.comparable === true,
    comparisonLimitations: stringArrayOf(comparison.comparison_limitations, `${path}.comparison.comparison_limitations`),
    changes: comparison.metrics.map((item, index) => {
      const change = recordOf(item, `${path}.comparison.metrics[${index}]`);
      return {
        key: stringOf(change.key, `${path}.comparison.metrics[${index}].key`),
        absoluteChange: numberOf(change.absolute_change, `${path}.comparison.metrics[${index}].absolute_change`),
        changeUnit: stringOf(change.change_unit, `${path}.comparison.metrics[${index}].change_unit`),
      };
    }),
    trendComparable: trend.comparable === true,
    points: trend.points.map((item, index) => measurementOf(item, `${path}.trend.points[${index}]`)),
  };
}

function displayUnit(unit: string): string {
  const normalized = unit.toLowerCase();
  if (normalized === "customers") return "명";
  if (normalized === "percent") return "%";
  if (normalized === "percentage_points") return "%p";
  if (normalized === "records") return "건";
  if (normalized === "events") return "회";
  return unit;
}

function formatValue(value: number, unit: string): string {
  return `${value.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}${displayUnit(unit)}`;
}

function normalizedTrend(points: ApiMeasurement[], metricKey: string): number[] {
  const values = points.flatMap((point) => {
    const metric = point.values.find((item) => item.key === metricKey);
    return metric?.value === null || metric?.value === undefined ? [] : [metric.value];
  });
  if (!values.length) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (min === max) return values.map(() => 0.5);
  return values.map((value) => (value - min) / (max - min));
}

function metricViews(signal: ApiBriefingSignal): BriefingMetric[] {
  if (signal.latestMeasurement?.status !== "success") return [];
  const changeByKey = new Map(signal.changes.map((change) => [change.key, change]));
  return signal.latestMeasurement.values
    .filter((metric) => metric.value !== null && metric.key !== "val_count" && !/확인용/.test(metric.label))
    .slice(0, 4)
    .map((metric) => {
      const change = signal.comparable ? changeByKey.get(metric.key) : undefined;
      if (!change || change.absoluteChange === 0) {
        return {
          label: metric.label,
          value: formatValue(metric.value as number, metric.unit),
          delta: change ? "변화 없음" : "첫 측정",
          direction: "flat" as const,
        };
      }
      return {
        label: metric.label,
        value: formatValue(metric.value as number, metric.unit),
        delta: formatValue(Math.abs(change.absoluteChange), change.changeUnit),
        direction: change.absoluteChange > 0 ? "up" as const : "down" as const,
      };
    });
}

function cardOf(signal: ApiBriefingSignal): BriefingSignal {
  const metrics = metricViews(signal);
  const primary = signal.latestMeasurement?.values.find((metric) =>
    metric.value !== null && metric.key !== "denominator_customer_count" && metric.key !== "val_count",
  );
  const statusNote = signal.latestMeasurement?.status === "unavailable"
    ? signal.latestMeasurement.reason ?? "이번 관측은 측정할 수 없었어요."
    : signal.description;
  return {
    id: signal.signalId,
    name: signal.title,
    chipLabel: signal.title,
    headline: primary?.value === null || primary?.value === undefined
      ? signal.title
      : `${signal.title} · *${primary.label} ${formatValue(primary.value, primary.unit)}*`,
    body: statusNote,
    metrics,
    trend: primary && signal.trendComparable ? normalizedTrend(signal.points, primary.key) : [],
    evidenceNote: `${signal.sourceIds.length}개 소스 · ${signal.populationDescription}`,
    sourceIds: signal.sourceIds,
    periodLabel: signal.latestMeasurement
      ? `${shortDate(signal.latestMeasurement.startAt)} – ${shortDate(new Date(new Date(signal.latestMeasurement.endAt).getTime() - 1).toISOString())}`
      : null,
    limitation: signal.latestMeasurement === null
      ? "측정 이력이 아직 없어요."
      : signal.latestMeasurement.status === "unavailable"
        ? signal.latestMeasurement.reason ?? "이번 관측은 측정할 수 없었어요."
        : !signal.comparable
          ? signal.comparisonLimitations.join(" ") || null
          : !signal.trendComparable
            ? "서로 다른 관측 기간은 추이로 연결하지 않았어요."
            : null,
    fromRequest: false,
  };
}

function dateLabel(timestamp: string): string {
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(new Date(timestamp));
}

function shortDate(timestamp: string): string {
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "numeric",
    day: "numeric",
  }).format(new Date(timestamp)).replace(/\. /g, "/").replace(/\.$/, "");
}

export class BriefingClient {
  private readonly apiBaseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: { apiBaseUrl?: string; fetchImpl?: typeof fetch } = {}) {
    this.apiBaseUrl = (options.apiBaseUrl ?? DEFAULT_API_BASE_URL).replace(/\/$/, "");
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  }

  async getBriefing(signal?: AbortSignal, offset = 0): Promise<Briefing> {
    let response: Response;
    try {
      response = await this.fetchImpl(
        `${this.apiBaseUrl}/api/signals/briefing?status=active&limit=20&offset=${offset}`,
        { signal },
      );
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      throw new BriefingClientError("브리핑을 불러오지 못했습니다.");
    }
    if (!response.ok) throw new BriefingClientError("브리핑을 불러오지 못했습니다.", response.status);
    const payload = recordOf(await response.json(), "briefing");
    if (!Array.isArray(payload.items)) {
      throw new BriefingClientError("briefing.items 응답 형식이 올바르지 않습니다.");
    }
    const generatedAt = stringOf(payload.generated_at, "briefing.generated_at");
    const total = numberOf(payload.total, "briefing.total");
    const items = payload.items.map((item, index) => signalOf(item, `briefing.items[${index}]`));
    const pastDates = [...new Set(items.flatMap((item) => item.points.map((point) =>
      shortDate(new Date(new Date(point.endAt).getTime() - 1).toISOString()),
    )))]
      .slice(-3)
      .reverse();
    return {
      dateLabel: dateLabel(generatedAt),
      lede: items.length ? `지금 *${total}개 변화*를 지켜보고 있어요.` : "오늘 먼저 알려드릴 변화는 없어요.",
      signals: items.map(cardOf),
      total,
      nextOffset: payload.next_offset === null ? null : numberOf(payload.next_offset, "briefing.next_offset"),
      requestCount: 0,
      watchingCount: total,
      pastDates,
      backlogCount: 0,
      askPlaceholder: "상담 뒤에도 같은 문의를 반복한 고객",
      suggestions: [
        "앱 알림을 끈 뒤 접속이 줄어든 고객",
        "요금제 변경 후 7일 안에 되돌린 고객",
        "상담 뒤에도 같은 문의를 반복한 고객",
      ],
    };
  }
}
