import { describe, expect, it, vi } from "vitest";

import { SignalClient } from "../signal-client";

describe("SignalClient", () => {
  it("reads measured proposal metrics for a completed run", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(Response.json({
      items: [{
        proposal_id: "proposal-1",
        title: "검색 기능 반복 실패 고객",
        description: "반복 실패를 계속 측정합니다.",
        limitations: [],
        definition: {
          source_ids: ["app_behavior"],
          population_description: "검색 고객",
        },
        measurement: {
          values: [
            { key: "affected_customer_count", label: "대상 고객 수", value: 327, unit: "customers" },
            { key: "affected_customer_rate", label: "대상 고객 비율", value: 30.2, unit: "percent" },
            { key: "unavailable", label: "측정 불가", value: null, unit: "records" },
          ],
        },
      }],
    }));
    const client = new SignalClient({ apiBaseUrl: "http://api.test/", fetchImpl });

    await expect(client.listProposals("run 1")).resolves.toEqual([{
      proposalId: "proposal-1",
      title: "검색 기능 반복 실패 고객",
      description: "반복 실패를 계속 측정합니다.",
      limitations: [],
      sourceIds: ["app_behavior"],
      populationDescription: "검색 고객",
      metrics: [
        { key: "affected_customer_count", label: "대상 고객 수", value: 327, unit: "customers" },
        { key: "affected_customer_rate", label: "대상 고객 비율", value: 30.2, unit: "percent" },
      ],
    }]);
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://api.test/api/signal-proposals?run_id=run%201",
      { signal: undefined },
    );
  });

  it("registers the proposal selected by the user", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(Response.json({
      signal_id: "signal-1",
      proposal_id: "proposal-1",
      alert_recommendations: {
        status: "ready",
        source: "model",
        items: [{
          recommendation_id: "rec-1",
          metric_key: "affected_customer_rate",
          metric_label: "대상 고객 비율",
          metric_unit: "percent",
          kind: "absolute_change",
          operator: "gte",
          threshold: 10,
          comparison_unit: "percentage_points",
          window_seconds: 86400,
          rationale: "직전 하루보다 10%p 늘면 확인해요.",
        }],
        reason: null,
        generated_at: "2026-09-10T11:00:00Z",
      },
    }));
    const client = new SignalClient({ apiBaseUrl: "http://api.test", fetchImpl });

    await expect(client.registerProposal("proposal-1")).resolves.toEqual({
      signalId: "signal-1",
      proposalId: "proposal-1",
      alertRecommendations: {
        status: "ready",
        source: "model",
        items: [{
          recommendationId: "rec-1",
          metricKey: "affected_customer_rate",
          metricLabel: "대상 고객 비율",
          metricUnit: "percent",
          kind: "absolute_change",
          operator: "gte",
          threshold: 10,
          comparisonUnit: "percentage_points",
          windowSeconds: 86400,
          rationale: "직전 하루보다 10%p 늘면 확인해요.",
        }],
        reason: null,
      },
    });
    expect(fetchImpl).toHaveBeenCalledWith("http://api.test/api/signals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ proposal_id: "proposal-1" }),
    });
  });

  it("reads and replaces server-owned alert rules", async () => {
    const item = {
      rule_id: "rule-1",
      recommendation_id: "rec-1",
      metric_key: "affected_customer_rate",
      metric_label: "대상 고객 비율",
      metric_unit: "percent",
      kind: "absolute_change",
      operator: "gte",
      threshold: 8,
      comparison_unit: "percentage_points",
      window_seconds: 86400,
      rationale: "변화를 확인해요.",
    };
    const fetchImpl = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({ signal_id: "signal-1", revision: 2, items: [item] }))
      .mockResolvedValueOnce(Response.json({ signal_id: "signal-1", revision: 3, items: [item] }));
    const client = new SignalClient({ apiBaseUrl: "http://api.test", fetchImpl });

    await expect(client.getAlertRules("signal-1")).resolves.toMatchObject({
      signalId: "signal-1",
      revision: 2,
      items: [{ ruleId: "rule-1", recommendationId: "rec-1", threshold: 8 }],
    });
    await expect(client.replaceAlertRules("signal-1", 2, [{ recommendationId: "rec-1", threshold: 8 }]))
      .resolves.toMatchObject({ revision: 3 });
    expect(fetchImpl).toHaveBeenLastCalledWith("http://api.test/api/signals/signal-1/alert-rules", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        revision: 2,
        items: [{ recommendation_id: "rec-1", threshold: 8 }],
      }),
    });
  });

  it("decodes schedule, history, comparison, and alert polling contracts", async () => {
    const measurement = {
      measurement_id: "measurement-1",
      start_at: "2026-09-09T15:00:00Z",
      end_at: "2026-09-10T15:00:00Z",
      measured_at: "2026-09-10T15:01:00Z",
      status: "success",
      reason: null,
      values: [{ key: "affected_customer_count", label: "대상 고객 수", value: 40, unit: "customers" }],
    };
    const recommendation = {
      recommendation_id: "rec-1",
      metric_key: "affected_customer_count",
      metric_label: "대상 고객 수",
      metric_unit: "customers",
      kind: "value",
      operator: "gt",
      threshold: 30,
      comparison_unit: "customers",
      window_seconds: 86400,
      rationale: "30명을 넘으면 확인해요.",
    };
    const fetchImpl = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(Response.json({
        signal_id: "signal-1", enabled: true, interval: "daily", timezone: "Asia/Seoul",
        next_run_at: "2026-09-10T15:00:00Z", updated_at: "2026-09-10T11:00:00Z", signal_status: "active",
      }))
      .mockResolvedValueOnce(Response.json({
        items: [measurement], latest_by_window: [measurement], comparable: false,
        comparison_limitations: ["비교할 기간이 더 필요합니다."],
      }))
      .mockResolvedValueOnce(Response.json({
        baseline: null, target: null, comparable: false,
        comparison_limitations: ["비교할 기간이 더 필요합니다."], metrics: [],
      }))
      .mockResolvedValueOnce(Response.json({
        items: [{
          sequence: 1, event_id: "event-1", event_type: "threshold_crossed",
          signal_id: "signal-1", signal_title: "반복 검색", rule: { ...recommendation, rule_id: "rule-1" },
          measurement_id: "measurement-1", baseline_measurement_id: null,
          observed_value: 40, metric_value: 40, baseline_value: null,
          start_at: "2026-09-09T15:00:00Z", end_at: "2026-09-10T15:00:00Z", occurred_at: "2026-09-10T15:01:00Z",
        }], next_cursor: 1, latest_cursor: 1, has_more: false,
      }));
    const client = new SignalClient({ apiBaseUrl: "http://api.test", fetchImpl });

    await expect(client.getSchedule("signal-1")).resolves.toMatchObject({ enabled: true, signalStatus: "active" });
    await expect(client.getMeasurementHistory("signal-1")).resolves.toMatchObject({ latestByWindow: [{ measurementId: "measurement-1" }] });
    await expect(client.getComparison("signal-1")).resolves.toMatchObject({ comparable: false, limitations: ["비교할 기간이 더 필요합니다."] });
    await expect(client.getAlertEvents(0)).resolves.toMatchObject({
      nextCursor: 1,
      items: [{ eventId: "event-1", rule: { windowSeconds: 86400 }, observedValue: 40 }],
    });
  });
});
