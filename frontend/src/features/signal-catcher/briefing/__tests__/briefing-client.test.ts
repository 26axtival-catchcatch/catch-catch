import { describe, expect, it, vi } from "vitest";

import { BriefingClient } from "../briefing-client";

describe("BriefingClient", () => {
  it("maps registered signals into briefing cards", async () => {
    const measurement = {
      measurement_id: "measurement-1",
      start_at: "2026-09-09T15:00:00Z",
      end_at: "2026-09-10T15:00:00Z",
      measured_at: "2026-09-10T15:01:00Z",
      status: "success",
      reason: null,
      values: [
        { key: "affected_customer_count", label: "대상 고객 수", value: 327, unit: "customers" },
        { key: "affected_customer_rate", label: "대상 고객 비율", value: 30.2, unit: "percent" },
      ],
    };
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(Response.json({
      generated_at: "2026-09-10T16:00:00Z",
      items: [{
        signal_id: "signal-1",
        title: "검색 기능 반복 실패 고객",
        description: "반복 실패 고객을 매일 측정합니다.",
        status: "active",
        origin: "analysis",
        created_at: "2026-09-10T15:02:00Z",
        source_ids: ["app_behavior"],
        population_description: "최근 일주일 검색 고객",
        latest_measurement: measurement,
        comparison: {
          baseline_measurement_id: null,
          target_measurement_id: "measurement-1",
          comparable: false,
          comparison_limitations: ["첫 측정"],
          metrics: [],
        },
        trend: { comparable: true, comparison_limitations: [], points: [measurement] },
      }],
      total: 1,
      limit: 20,
      offset: 0,
      next_offset: null,
    }));
    const client = new BriefingClient({ apiBaseUrl: "http://api.test/", fetchImpl });

    await expect(client.getBriefing()).resolves.toMatchObject({
      signals: [{
        id: "signal-1",
        name: "검색 기능 반복 실패 고객",
        metrics: [
          { label: "대상 고객 수", value: "327명", delta: "첫 측정", direction: "flat" },
          { label: "대상 고객 비율", value: "30.2%", delta: "첫 측정", direction: "flat" },
        ],
        fromRequest: false,
      }],
      watchingCount: 1,
    });
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://api.test/api/signals/briefing?status=active&limit=20&offset=0",
      { signal: undefined },
    );
  });
});
