import { describe, expect, it, vi } from "vitest";

import { SignalClient } from "../signal-client";

describe("SignalClient", () => {
  it("reads measured proposal metrics for a completed run", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(Response.json({
      items: [{
        proposal_id: "proposal-1",
        title: "검색 기능 반복 실패 고객",
        description: "반복 실패를 계속 측정합니다.",
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
});
