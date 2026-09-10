import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";

const backend = `http://127.0.0.1:${process.env.E2E_BACKEND_PORT?.trim() || "38100"}`;
test.skip(!process.env.ONBOARDED_SOURCES_DIR, "Requires the approved synthetic sources");

test("데이터 끝에서 중단 → 시작일 재설정 → 실제 일별 값과 알림 → 재시작 응답 복구", async ({ page }) => {
  test.setTimeout(120_000);
  const registered = await page.request.post(`${backend}/api/signals`, { data: {
    title: "빨리감기 경계 검증", description: "합성 데이터의 실제 일별 측정",
    start_at: "2026-09-04T00:00:00+09:00", end_at: "2026-09-18T00:00:00+09:00",
    definition: {
      source_ids: ["hackathon_search_history"],
      cohort_sql: "SELECT DISTINCT customer_id FROM events WHERE topic='부가서비스 조회/해지' AND dim_query_type='repeat'",
      denominator_sql: "SELECT DISTINCT customer_id FROM events WHERE topic='부가서비스 조회/해지'",
      population_description: `부가서비스 검색 고객 (E2E ${randomUUID()})`,
      normal_comparison: "반복하지 않은 검색 고객",
    },
  } });
  expect(registered.ok()).toBe(true);
  const signal = await registered.json();
  const sid = signal.signal_id;
  try {
    const recommendation = signal.alert_recommendations.items.find((item: { metric_key: string; kind: string }) => item.metric_key === "affected_customer_count" && item.kind === "value");
    expect(recommendation).toBeTruthy();
    expect((await page.request.put(`${backend}/api/signals/${sid}/alert-rules`, { data: {
      revision: 0, items: [{ recommendation_id: recommendation.recommendation_id, threshold: 1 }],
    } })).ok()).toBe(true);
    await page.goto("/");
    await page.getByRole("button", { name: "하루 빨리감기", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "관측 데이터가 없어 멈췄습니다" })).toBeVisible();
    await page.getByRole("button", { name: "시작일 설정", exact: true }).click();
    await page.getByLabel("다음 분석일").fill("2026-09-11");
    await page.getByRole("button", { name: "이 날짜부터 다시 시작", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "9월 11일부터 분석할 준비" })).toBeVisible();
    const next = page.waitForResponse((r) => r.url().endsWith("/api/signals/fast-forward") && r.request().method() === "POST");
    await page.getByRole("button", { name: "하루 빨리감기", exact: true }).click();
    const item = (await (await next).json()).items.find((value: { signal_id: string }) => value.signal_id === sid);
    expect(item.daily_results[0].measurement.values[0].value).toBe(28);
    expect(item.alert_events).toHaveLength(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `node_modules/.cache/fast-forward-${test.info().project.name}.png`, fullPage: true });

    const edge = await page.request.post(`${backend}/api/signals/fast-forward`, { data: {
      request_id: randomUUID(), days: 7, signal_ids: [sid],
    } });
    const stopped = (await edge.json()).items[0];
    expect(stopped.status).toBe("blocked");
    expect(stopped.daily_results).toHaveLength(6);
    const before = await (await page.request.get(`${backend}/api/signals/${sid}/measurements`)).json();
    await page.getByRole("button", { name: "하루 빨리감기", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "관측 데이터가 없어 멈췄습니다" })).toBeVisible();
    const after = await (await page.request.get(`${backend}/api/signals/${sid}/measurements`)).json();
    expect(after.items).toEqual(before.items);
    expect(after.items.every((m: { status: string }) => m.status === "success")).toBe(true);

    let firstRequest: unknown;
    await page.route("**/api/signals/fast-forward/reset", async (route) => {
      firstRequest = route.request().postDataJSON();
      expect((await route.fetch()).ok()).toBe(true);
      await route.abort("failed");
    }, { times: 1 });
    await page.getByRole("button", { name: "시작일 설정", exact: true }).click();
    await page.getByRole("button", { name: "이 날짜부터 다시 시작", exact: true }).click();
    await expect(page.getByRole("button", { name: "같은 요청 재시도", exact: true })).toBeVisible();
    await page.reload();
    const retry = page.waitForResponse((r) => r.url().endsWith("/api/signals/fast-forward/reset"));
    await page.getByRole("button", { name: "같은 요청 재시도", exact: true }).click();
    const recovered = await retry;
    expect(recovered.request().postDataJSON()).toEqual(firstRequest);
    expect(recovered.ok()).toBe(true);
    const history = await (await page.request.get(`${backend}/api/signals/${sid}/measurements`)).json();
    expect(history.items).toHaveLength(1);
    expect(history.items[0].end_at).toBe("2026-09-10T15:00:00Z");
  } finally {
    await page.request.patch(`${backend}/api/signals/${sid}`, { data: { status: "paused" } });
  }
});
