import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const backendPort = process.env.E2E_BACKEND_PORT ?? "38100";
const backendUrl = `http://127.0.0.1:${backendPort}`;
const repository = path.resolve(import.meta.dirname, "../..");
const artifacts = process.env.E2E_ARTIFACT_DIRECTORY ?? path.join(repository, `frontend/node_modules/.cache/run-artifacts-${backendPort}`);
const sources = process.env.ONBOARDED_SOURCES_DIR;

test.skip(!sources, "ONBOARDED_SOURCES_DIR에 승인된 investigation-demo-sources를 지정합니다.");
// Headless Shell reports Notification.permission=denied even after a grant.
// Use full Chromium's new headless mode so native notification APIs really run.
test.use({ channel: "chromium" });

test.beforeEach(async ({ request }) => {
  const response = await request.get(`${backendUrl}/api/signals`);
  for (const signal of (await response.json()).items) {
    if (signal.status === "active" && signal.definition.population_description.includes("(E2E ")) {
      await request.patch(`${backendUrl}/api/signals/${signal.signal_id}`, { data: { status: "paused" } });
    }
  }
});

async function registerFromAnalysis(page: Page) {
  const accepted = await page.request.post(`${backendUrl}/api/runs`, { data: {
    question: "최근 부정 피드백이 많은 Topic과 관련 고객 Segment를 알려줘.",
    start_at: "2026-09-04T00:00:00+09:00", end_at: "2026-09-11T00:00:00+09:00",
    enabled_sources: ["hackathon_search_history"],
  } });
  expect(accepted.ok()).toBe(true);
  const { run_id: runId } = await accepted.json();
  await expect.poll(async () => (await (await page.request.get(`${backendUrl}/api/runs/${runId}`)).json()).status).toBe("completed");
  const seed = JSON.parse(execFileSync("uv", [
    "run", "--no-env-file", "--project", "backend", "python", "frontend/e2e/seed-signal-proposal.py",
    "--run-id", runId, "--artifacts", artifacts, "--sources", sources!,
  ], { cwd: repository, encoding: "utf8", env: { ...process.env, LANGSMITH_TRACING: "false", LANGCHAIN_TRACING_V2: "false" } }));
  await page.goto(`/runs/${runId}`);
  const registration = page.waitForResponse((response) => response.url().endsWith("/api/signals") && response.request().method() === "POST");
  await page.getByRole("button", { name: "변화 캐치 맡기기" }).click();
  // Reuse the measured signal directly, with no second AI recommendation step.
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "어떤 변화가 생기면 알려드릴까요?" })).toBeVisible();
  const threshold = dialog.getByRole("spinbutton", { name: "대상 고객 수 기준값" });
  await expect(threshold).toBeVisible();
  await expect(dialog.getByText("이상이면 알려드려요").first()).toBeVisible();
  expect(await dialog.getByText(/AI.*제안/).count()).toBe(0);
  await dialog.screenshot({ path: test.info().outputPath("signal-metric-thresholds.png"), animations: "disabled" });
  await threshold.fill("1");
  // Select only the original count metric for this alert flow.
  const rate = dialog.getByRole("checkbox", { name: /대상 고객 비율/ });
  if (await rate.count() && await rate.isChecked()) await rate.locator("..").click();
  await dialog.getByRole("button", { name: "변화 캐치 시작하기" }).click();
  await expect(dialog.getByRole("heading", { name: "이제 변화는 캐치캐치가 볼게요" })).toBeVisible();
  const registered = await (await registration).json();
  expect(registered.proposal_id).toBe(seed.proposal_id);
  expect(registered.alert_recommendations.source).toBe("measurement");
  expect(registered.alert_recommendations.items.every((item: { kind: string; operator: string }) => item.kind === "value" && item.operator === "gte")).toBe(true);
  await dialog.getByRole("button", { name: "메인화면으로 돌아가기" }).click();
  return registered.signal_id as string;
}

async function advance(page: Page) {
  const response = page.waitForResponse((item) => item.url().endsWith("/api/signals/fast-forward") && item.request().method() === "POST");
  await page.getByRole("button", { name: "하루 빨리감기", exact: true }).click();
  const result = await response;
  expect(result.ok()).toBe(true);
  return result.json();
}

async function nativeNotifications(page: Page) {
  return page.evaluate(async () => (await (await navigator.serviceWorker.ready).getNotifications()).map((item) => ({
    title: item.title, body: item.body, tag: item.tag, signalId: item.data.signalId,
  })));
}

test("등록 → 다음 날짜 실제 분석 → 네이티브 알림 → 상세, 여러 탭과 새로고침에도 한 번 표시", async ({ page, context }, testInfo) => {
  test.setTimeout(90_000);
  await context.grantPermissions(["notifications"]);
  // Instrument the real native method without replacing its behavior.
  await context.addInitScript(() => {
    const original = ServiceWorkerRegistration.prototype.showNotification;
    ServiceWorkerRegistration.prototype.showNotification = function (...args) {
      localStorage.setItem("e2e.native-calls", String(Number(localStorage.getItem("e2e.native-calls") ?? 0) + 1));
      return original.apply(this, args);
    };
  });
  const signalId = await registerFromAnalysis(page);
  const second = await context.newPage();
  await second.goto("/");
  await second.getByRole("button", { name: /^알림/ }).click();
  await expect(second.getByText("브라우저 알림이 켜져 있어요.")).toBeVisible();
  const result = await advance(page);
  const item = result.items.find((value: { signal_id: string }) => value.signal_id === signalId);
  const day = item.daily_results[0];
  expect(day.start_at).toBe("2026-09-10T15:00:00Z");
  expect(day.end_at).toBe("2026-09-11T15:00:00Z");
  expect(day.measurement.status).toBe("success");
  expect(day.measurement.values).toEqual(expect.arrayContaining([
    expect.objectContaining({ key: "affected_customer_count", value: 28 }),
    expect.objectContaining({ key: "denominator_customer_count", value: 50 }),
  ]));
  expect(day.measurement.values.find((value: { key: string }) => value.key === "affected_customer_rate").value).toBeCloseTo(56);
  expect(item.alert_events).toHaveLength(1);
  expect(item.alert_events[0].measurement_id).toBe(day.measurement.measurement_id);
  await expect.poll(() => nativeNotifications(page)).toEqual([
    expect.objectContaining({ title: "캐치캐치 · 부가서비스 반복 검색", body: "대상 고객 수 28명", signalId }),
  ]);
  await expect(second.getByRole("button", { name: /부가서비스 반복 검색/ })).toBeVisible({ timeout: 20_000 });
  expect(await page.evaluate(() => localStorage.getItem("e2e.native-calls"))).toBe("1");
  await page.reload();
  await page.getByRole("button", { name: /^알림/ }).click();
  await expect(page.getByText("브라우저 알림이 켜져 있어요.")).toBeVisible();
  expect(await nativeNotifications(page)).toHaveLength(1);
  expect(await page.evaluate(() => localStorage.getItem("e2e.native-calls"))).toBe("1");
  // Chromium exposes the real worker. Dispatch its notificationclick handler;
  // an OS-level banner click itself is outside headless automation.
  const worker = context.serviceWorkers().find((value) => value.url().endsWith("signal-notifications-sw.js"))!;
  await second.close();
  await worker.evaluate(async () => {
    const scope = globalThis as unknown as { registration: ServiceWorkerRegistration; dispatchEvent: (event: Event) => void };
    const [notification] = await scope.registration.getNotifications();
    const NotificationEventClass = (globalThis as unknown as { NotificationEvent: new (type: string, init: { notification: Notification }) => Event }).NotificationEvent;
    scope.dispatchEvent(new NotificationEventClass("notificationclick", { notification }));
  });
  const detail = page.getByRole("dialog");
  await expect(detail.getByRole("heading", { name: "부가서비스 반복 검색" })).toBeVisible();
  // A native click must reveal an unobstructed modal even with the inbox open.
  await expect(detail.getByRole("button", { name: "닫기", exact: true })).toBeVisible();
  await detail.getByRole("button", { name: "닫기", exact: true }).click({ trial: true });
  await expect(detail.locator("time").filter({ hasText: "2026-09-11 – 2026-09-11" }).first()).toBeVisible();
  await expect(detail.getByText(/28명/).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("native-alert-detail.png"), fullPage: true });
  await testInfo.attach("real-sql-and-alert", { body: JSON.stringify(item, null, 2), contentType: "application/json" });
  await page.request.patch(`${backendUrl}/api/signals/${signalId}`, { data: { status: "paused" } });
});

test("네이티브 알림을 차단해도 실제 이벤트가 알림함과 상세에 도착한다", async ({ page, context }) => {
  test.setTimeout(90_000);
  // Chromium's permission override denies permissions omitted from this list.
  await context.grantPermissions([]);
  const signalId = await registerFromAnalysis(page);
  await page.getByRole("button", { name: /^알림/ }).click();
  await expect(page.getByText(/브라우저 알림이 차단되어 있어요/)).toBeVisible();
  await advance(page);
  await page.getByRole("region", { name: "변화 알림" }).getByRole("button", { name: /부가서비스 반복 검색/ }).click();
  await expect(page.getByRole("dialog").getByText(/28명/).first()).toBeVisible();
  await page.request.patch(`${backendUrl}/api/signals/${signalId}`, { data: { status: "paused" } });
});

test("완료 응답 유실 후 새로고침하고 재시도해도 같은 날짜와 요청 ID를 유지한다", async ({ page, context }) => {
  test.setTimeout(90_000);
  await context.grantPermissions([]);
  const signalId = await registerFromAnalysis(page);
  let firstId = "";
  let replayId = "";
  await page.route("**/api/signals/fast-forward", async (route) => {
    firstId = route.request().postDataJSON().request_id;
    const completed = await route.fetch();
    expect(completed.ok()).toBe(true);
    // The server committed real SQL results; only its first response is lost.
    await route.abort("failed");
  }, { times: 1 });
  await page.getByRole("button", { name: "하루 빨리감기", exact: true }).click();
  await expect(page.getByRole("button", { name: "같은 요청 재시도", exact: true })).toBeEnabled();
  await page.reload();
  const retry = page.getByRole("button", { name: "같은 요청 재시도", exact: true });
  await expect(retry).toBeVisible();
  const response = page.waitForResponse((item) => item.url().endsWith("/api/signals/fast-forward") && item.request().method() === "POST");
  await retry.click();
  const replay = await response;
  replayId = replay.request().postDataJSON().request_id;
  expect(replay.ok()).toBe(true);
  expect(replayId).toBe(firstId);
  const item = (await replay.json()).items.find((value: { signal_id: string }) => value.signal_id === signalId);
  expect(item.daily_results[0].start_at).toBe("2026-09-10T15:00:00Z");
  const history = await (await page.request.get(`${backendUrl}/api/signals/${signalId}/daily-results`)).json();
  expect(history.items).toHaveLength(1);
  expect(history.items[0].measurement.measurement_id).toBe(item.daily_results[0].measurement.measurement_id);
  await page.request.patch(`${backendUrl}/api/signals/${signalId}`, { data: { status: "paused" } });
});
