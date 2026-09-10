"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  AnalysisFact,
  AnalysisPlan,
  AnyRunStreamEvent,
  CustomerSignalReport,
  PublicSourceList,
  RunAccepted,
  RunError,
  RunSnapshot,
  CustomerJourneyResult,
  EvidenceResult,
} from "../../customer-intelligence/contracts";
import { RunClient, RunClientError } from "../../customer-intelligence/run-client";

import {
  LIVE_END_AT,
  LIVE_START_AT,
  activeSourceListOf,
  completedStages,
  makeTick,
  sourceLabelsOf,
  sourceOptionsOf,
  stageForStep,
  toCatchReport,
} from "./live-adapter";
import { STAGES } from "./mock";
import type {
  CatchSession,
  EvidenceMap,
  RunOutcome,
  Stage,
  StageKey,
  StageTick,
} from "./types";
import type {
  CatchSessionController,
  CatchStartOptions,
  ViewParam,
} from "./use-catch-session";

const BURST_MS = 700;
const STAGE_ORDER: StageKey[] = ["goal", "plan", "analyze", "insight", "verify"];

function freshStages(): Stage[] {
  return STAGES.map((stage) => ({ ...stage, detail: null, status: "pending" }));
}

function idleSession(): CatchSession {
  return {
    phase: "ask",
    question: "",
    stages: freshStages(),
    activeStage: null,
    clarification: null,
    outcome: null,
    report: null,
    failureReason: null,
    suggestedQuestions: [],
  };
}

function isAbort(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === "AbortError") ||
    (error instanceof Error && error.name === "AbortError")
  );
}

function publicError(error: unknown): RunError {
  if (error instanceof RunClientError) {
    return { code: error.code, message: error.message };
  }
  return {
    code: "network_error",
    message: "분석 서버에 연결하지 못했어요. 잠시 후 같은 조건으로 다시 시도해 주세요.",
  };
}

function isCustomerSignalReport(
  report: RunSnapshot["report"],
): report is CustomerSignalReport {
  return report?.report_kind === "customer_signal";
}

function uniquePlan(plans: AnalysisPlan[], plan: AnalysisPlan): AnalysisPlan[] {
  return plans.some(
    (item) => item.plan_id === plan.plan_id && item.revision === plan.revision,
  )
    ? plans
    : [...plans, plan];
}

function metricTick(fact: AnalysisFact): string {
  const metric = fact.metrics[0];
  if (!metric) return "조회 결과를 분석 기록에 반영했어요";
  return `${metric.label} ${metric.value.toLocaleString("ko-KR")}${metric.unit}을 확인했어요`;
}

function firstJourneyCustomer(facts: readonly AnalysisFact[]): string | null {
  for (const fact of facts) {
    if (fact.payload.kind !== "get_customer_journey") continue;
    const customerId = fact.payload.customer_id;
    if (typeof customerId === "string" && customerId.trim()) return customerId;
  }
  return null;
}

function seoulMidnight(value: string): string {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00+09:00` : value;
}

export interface SignalCatcherClient {
  listSources(signal?: AbortSignal): Promise<PublicSourceList>;
  createRun(request: {
    question: string;
    start_at: string;
    end_at: string;
    enabled_sources: string[];
  }, signal?: AbortSignal): Promise<RunAccepted>;
  getRun(runId: string, signal?: AbortSignal): Promise<RunSnapshot>;
  streamRunEvents(
    runId: string,
    options?: { signal?: AbortSignal; lastEventId?: number },
  ): AsyncIterable<AnyRunStreamEvent>;
  submitClarification(runId: string, answer: string, signal?: AbortSignal): Promise<RunAccepted>;
  getJourney(runId: string, customerId: string, signal?: AbortSignal): Promise<CustomerJourneyResult>;
  getEvidence(runId: string, evidenceId: string, signal?: AbortSignal): Promise<EvidenceResult>;
}

async function terminalSnapshot(
  client: SignalCatcherClient,
  runId: string,
  signal: AbortSignal,
): Promise<RunSnapshot> {
  let snapshot = await client.getRun(runId, signal);
  // done SSE가 journal에 먼저 보이고 RunStore의 terminal 반영이 바로 뒤따르는 짧은 구간을 흡수한다.
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (snapshot.status === "completed" || snapshot.status === "degraded" || snapshot.status === "failed") {
      return snapshot;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
    signal.throwIfAborted();
    snapshot = await client.getRun(runId, signal);
  }
  return snapshot;
}

/** Signal Catcher 전용 실제 API/SSE 상태 어댑터. */
export function useLiveCatchSession(providedClient?: SignalCatcherClient): CatchSessionController {
  const defaultClient = useMemo(() => new RunClient({ agentMode: "bedrock" }), []);
  const client = providedClient ?? defaultClient;
  const [session, setSession] = useState<CatchSession>(idleSession);
  const [bursting, setBursting] = useState(false);
  const [flatline, setFlatline] = useState(false);
  const [tick, setTick] = useState<StageTick | null>(null);
  const [log, setLog] = useState<(StageTick & { stage: StageKey })[]>([]);
  const [topologyEvents, setTopologyEvents] = useState<AnyRunStreamEvent[]>([]);
  const [evidence, setEvidence] = useState<EvidenceMap>({});
  const [evidenceLoadingId, setEvidenceLoadingId] = useState<string | null>(null);
  const [evidenceErrorId, setEvidenceErrorId] = useState<string | null>(null);
  const [sourceCount, setSourceCount] = useState<number | null>(null);
  const [sourceOptions, setSourceOptions] = useState(() => sourceOptionsOf({ items: [] }));

  const mountedRef = useRef(true);
  const versionRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const streamActiveRef = useRef(false);
  const runIdRef = useRef<string | null>(null);
  const lastEventIdRef = useRef(0);
  const plansRef = useRef<AnalysisPlan[]>([]);
  const factsRef = useRef<AnalysisFact[]>([]);
  const durationsRef = useRef<Record<string, number>>({});
  const traceRef = useRef<(StageTick & { stage: StageKey })[]>([]);
  const topologyEventLogRef = useRef<AnyRunStreamEvent[]>([]);
  const reportRef = useRef<CustomerSignalReport | null>(null);
  const sourceListRef = useRef<PublicSourceList>({ items: [] });
  const startedAtRef = useRef(0);
  const publishingFactsRef = useRef(false);
  const burstTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastStartOptionsRef = useRef<CatchStartOptions | undefined>(undefined);

  const appendTick = useCallback((entry: StageTick & { stage: StageKey }) => {
    traceRef.current = [...traceRef.current, entry];
    setLog(traceRef.current);
    setTick(entry);
  }, []);

  const appendTopologyEvent = useCallback((event: AnyRunStreamEvent) => {
    topologyEventLogRef.current = [...topologyEventLogRef.current, event];
    setTopologyEvents(topologyEventLogRef.current);
  }, []);

  const activities = useMemo(
    () => topologyEvents.flatMap((event) => event.type === "agent_activity" ? [event.data] : []),
    [topologyEvents],
  );

  const advance = useCallback((stage: StageKey, detail: string) => {
    const requestedIndex = STAGE_ORDER.indexOf(stage);
    setSession((current) => {
      const currentIndex = current.activeStage
        ? STAGE_ORDER.indexOf(current.activeStage)
        : current.stages.filter((item) => item.status === "done").length - 1;
      const targetIndex = Math.max(currentIndex, requestedIndex);
      const target = STAGE_ORDER[targetIndex] ?? stage;
      return {
        ...current,
        activeStage: target,
        stages: current.stages.map((item, index) => ({
          ...item,
          detail: item.key === target ? detail : item.detail,
          status: index < targetIndex ? "done" : index === targetIndex ? "active" : "pending",
        })),
      };
    });
  }, []);

  const fail = useCallback((error: RunError) => {
    setTick(null);
    setFlatline(true);
    if (error.suggested_questions?.length) {
      setSession((current) => ({
        ...idleSession(),
        question: current.question,
        failureReason: error.message,
        suggestedQuestions: error.suggested_questions ?? [],
      }));
      return;
    }
    setSession((current) => ({
      ...current,
      outcome: "failed",
      failureReason: error.message,
    }));
  }, []);

  const settle = useCallback(
    async (
      runId: string,
      status: "completed" | "degraded",
      version: number,
      controller: AbortController,
    ) => {
      let snapshot: RunSnapshot;
      try {
        snapshot = await terminalSnapshot(client, runId, controller.signal);
      } catch (error) {
        if (!reportRef.current) throw error;
        snapshot = {
          run_id: runId,
          status,
          request: {
            question: "",
            start_at: LIVE_START_AT,
            end_at: LIVE_END_AT,
            enabled_sources: sourceListRef.current.items.map((item) => item.source_id),
          },
          created_at: new Date(startedAtRef.current).toISOString(),
          updated_at: new Date().toISOString(),
          agent_mode: "bedrock",
          report: reportRef.current,
          error: null,
          plan_history: plansRef.current,
          facts: factsRef.current,
        };
      }
      if (
        !mountedRef.current || controller.signal.aborted ||
        versionRef.current !== version
      ) return;
      if (snapshot.status === "failed") {
        fail(snapshot.error ?? { code: "run_failed", message: "분석을 완료하지 못했어요." });
        return;
      }
      const report = isCustomerSignalReport(snapshot.report)
        ? snapshot.report
        : reportRef.current;
      if (!report) {
        fail({
          code: "unsupported_report",
          message: "분석은 완료됐지만 결과를 불러오지 못했어요. 다시 시도해 주세요.",
        });
        return;
      }

      const facts = snapshot.facts.length ? snapshot.facts : factsRef.current;
      factsRef.current = facts;
      let journey = report.representative_journeys;
      const customerId = firstJourneyCustomer(factsRef.current);
      if (customerId) {
        try {
          const detail = await client.getJourney(runId, customerId, controller.signal);
          journey = detail.events;
        } catch (error) {
          if (controller.signal.aborted || isAbort(error)) return;
          // 공개 리포트의 대표 여정이 있으므로 상세 조회 실패만으로 Run을 실패시키지 않는다.
        }
      }
      if (
        !mountedRef.current || controller.signal.aborted ||
        versionRef.current !== version
      ) return;

      const outcome: RunOutcome = snapshot.status === "degraded" || status === "degraded"
        ? "degraded"
        : "completed";
      const catchReport = toCatchReport({
        runId,
        report,
        plans: snapshot.plan_history.length ? snapshot.plan_history : plansRef.current,
        facts,
        stepDurations: durationsRef.current,
        traceLog: traceRef.current,
        sourceLabels: sourceLabelsOf(sourceListRef.current),
        journey,
        startedAt: startedAtRef.current,
        completedAt: snapshot.updated_at,
      });
      setTick(null);
      setFlatline(false);
      setBursting(true);
      setSession((current) => ({
        ...current,
        activeStage: null,
        stages: completedStages(),
        clarification: null,
        outcome,
        report: catchReport,
      }));
      if (burstTimerRef.current) clearTimeout(burstTimerRef.current);
      burstTimerRef.current = setTimeout(() => {
        if (!mountedRef.current || versionRef.current !== version) return;
        setBursting(false);
        setSession((current) => ({ ...current, phase: "result" }));
      }, BURST_MS);
    },
    [client, fail],
  );

  const consumeStream = useCallback(
    async (
      runId: string,
      controller: AbortController,
      version: number,
      lastEventId = 0,
    ) => {
      streamActiveRef.current = true;
      try {
        for await (const event of client.streamRunEvents(runId, {
          signal: controller.signal,
          lastEventId,
        })) {
          if (
            !mountedRef.current || controller.signal.aborted ||
            versionRef.current !== version
          ) continue;
          lastEventIdRef.current = event.id;
          appendTopologyEvent(event);

          switch (event.type) {
            case "agent_activity":
              break;
            case "run_started": {
              const entry = makeTick("goal", "think", "질문에서 분석 목적과 범위를 확인하고 있어요");
              advance("goal", entry.text);
              appendTick(entry);
              break;
            }
            case "goal_created": {
              const entry = makeTick("goal", "think", "분석할 대상과 범위를 정했어요", {
                meta: event.data.goal.population.description,
              });
              advance("goal", entry.text);
              appendTick(entry);
              advance("plan", "확인할 데이터와 분석 순서를 정하고 있어요");
              break;
            }
            case "clarification_required":
              setSession((current) => ({
                ...current,
                clarification: {
                  clarificationId: event.data.clarification_id,
                  question: event.data.question,
                  hint: "답변을 반영한 뒤 진행 중인 분석을 이어갈게요.",
                },
              }));
              break;
            case "plan_created":
            case "plan_revised": {
              plansRef.current = uniquePlan(plansRef.current, event.data.plan);
              const entry = makeTick(
                "plan",
                "think",
                `확인 과정을 ${event.data.plan.steps.length}단계로 나누었어요`,
                { meta: `plan revision ${event.data.plan.revision}` },
              );
              advance("plan", entry.text);
              appendTick(entry);
              advance("analyze", "선택한 데이터에서 관련 기록을 확인하고 있어요");
              break;
            }
            case "step_started": {
              const stage = publishingFactsRef.current
                ? "verify"
                : stageForStep(event.data.step_id);
              const text = event.data.objective ?? event.data.selection_reason ?? `${event.data.primitive} 실행 중`;
              const entry = makeTick(stage, "tool", text, {
                primitive: event.data.primitive,
                meta: event.data.step_id,
              });
              advance(stage, text);
              appendTick(entry);
              break;
            }
            case "fact_created": {
              if (!factsRef.current.some((fact) => fact.fact_id === event.data.fact.fact_id)) {
                factsRef.current = [...factsRef.current, event.data.fact];
              }
              const stage = publishingFactsRef.current
                ? "verify"
                : stageForStep(event.data.step_id);
              const text = metricTick(event.data.fact);
              const metric = event.data.fact.metrics[0];
              const entry = makeTick(stage, "fact", text, {
                short: metric ? `${metric.value.toLocaleString("ko-KR")}${metric.unit}` : undefined,
                meta: event.data.fact.fact_id,
              });
              advance(stage, text);
              appendTick(entry);
              break;
            }
            case "analysis_note_created": {
              const stage = publishingFactsRef.current
                ? "verify"
                : stageForStep(event.data.note.step_id);
              const text = event.data.note.claims[0]?.rendered_text ?? event.data.note.next_action;
              const entry = makeTick(stage, "think", text, {
                meta: event.data.note.note_id,
              });
              advance(stage, text);
              appendTick(entry);
              break;
            }
            case "step_completed": {
              durationsRef.current = {
                ...durationsRef.current,
                [event.data.step_id]: event.data.duration_ms,
              };
              const stage = publishingFactsRef.current
                ? "verify"
                : stageForStep(event.data.step_id);
              advance(stage, "현재 단계의 데이터 확인을 마쳤어요");
              break;
            }
            case "report_validating": {
              publishingFactsRef.current = true;
              const entry = makeTick("insight", "think", "발견한 내용이 원본 근거와 맞는지 확인하고 있어요", {
                meta: `확인된 사실 ${event.data.fact_ids.length}건`,
              });
              advance("insight", entry.text);
              appendTick(entry);
              break;
            }
            case "plan": {
              const entry = makeTick("plan", "think", `확인 과정을 ${event.data.steps.length}단계로 나누었어요`);
              advance("plan", entry.text);
              appendTick(entry);
              break;
            }
            case "tool_started": {
              const entry = makeTick("analyze", "tool", "선택한 데이터에서 관련 기록을 조회하고 있어요", {
                primitive: event.data.tool,
                meta: event.data.source.join(", "),
              });
              advance("analyze", entry.text);
              appendTick(entry);
              break;
            }
            case "tool_completed": {
              const entry = makeTick("analyze", "fact", `${event.data.count.toLocaleString("ko-KR")}건을 확인했어요`, {
                short: `${event.data.count.toLocaleString("ko-KR")}건`,
                meta: event.data.result_id,
              });
              advance("analyze", entry.text);
              appendTick(entry);
              break;
            }
            case "validating": {
              const entry = makeTick("verify", "tool", "발견한 내용이 원본 데이터와 맞는지 확인하고 있어요", {
                primitive: "validate_claims",
                meta: `결과 ${event.data.result_ids.length}개`,
              });
              advance("verify", entry.text);
              appendTick(entry);
              break;
            }
            case "result":
              if (event.data.report.report_kind === "customer_signal") {
                reportRef.current = event.data.report;
                advance("verify", "근거 확인을 마치고 결과를 정리했어요");
              }
              break;
            case "fallback":
              appendTick(makeTick(
                "analyze",
                "reject",
                event.data.reason ?? event.data.message
                  ?? "일부 데이터를 사용할 수 없어 확인 가능한 범위에서 계속 분석하고 있어요",
              ));
              break;
            case "error":
              fail(event.data);
              break;
            case "done":
              if (event.data.status === "failed") {
                fail({ code: "run_failed", message: "분석을 완료하지 못했어요." });
              } else {
                await settle(runId, event.data.status, version, controller);
              }
              return;
          }
        }
      } catch (error) {
        if (
          !mountedRef.current || controller.signal.aborted || isAbort(error) ||
          versionRef.current !== version
        ) return;
        try {
          const snapshot = await client.getRun(runId, controller.signal);
          if (snapshot.status === "completed" || snapshot.status === "degraded") {
            if (isCustomerSignalReport(snapshot.report)) reportRef.current = snapshot.report;
            await settle(runId, snapshot.status, version, controller);
            return;
          }
          if (snapshot.status === "failed") {
            fail(snapshot.error ?? { code: "run_failed", message: "분석을 완료하지 못했어요." });
            return;
          }
        } catch (snapshotError) {
          if (controller.signal.aborted || isAbort(snapshotError)) return;
        }
        fail(publicError(error));
      } finally {
        streamActiveRef.current = false;
      }
    },
    [advance, appendTick, appendTopologyEvent, client, fail, settle],
  );

  const start = useCallback(
    (question: string, options?: CatchStartOptions) => {
      const normalized = question.trim();
      if (!normalized) {
        setSession((current) => ({ ...current, failureReason: "분석할 질문을 입력해 주세요." }));
        return;
      }
      versionRef.current += 1;
      const version = versionRef.current;
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      if (burstTimerRef.current) clearTimeout(burstTimerRef.current);
      runIdRef.current = null;
      lastEventIdRef.current = 0;
      plansRef.current = [];
      factsRef.current = [];
      durationsRef.current = {};
      traceRef.current = [];
      topologyEventLogRef.current = [];
      reportRef.current = null;
      publishingFactsRef.current = false;
      startedAtRef.current = Date.now();
      lastStartOptionsRef.current = options;
      setBursting(false);
      setFlatline(false);
      setTick(null);
      setLog([]);
      setTopologyEvents([]);
      setEvidence({});
      setEvidenceLoadingId(null);
      setEvidenceErrorId(null);
      setSession({
        ...idleSession(),
        phase: "catching",
        question: normalized,
      });

      void (async () => {
        try {
          // 등록 디렉터리가 런타임에 바뀔 수 있으므로 매 Run 직전에 반드시 다시 조회한다.
          const previousSourceIds = sourceListRef.current.items.map((item) => item.source_id);
          const sources = activeSourceListOf(await client.listSources(controller.signal));
          if (!sources.items.length) {
            throw new RunClientError("invalid_response", "분석에 사용할 수 있는 데이터가 없어요.");
          }
          sourceListRef.current = sources;
          setSourceCount(sources.items.length);
          setSourceOptions(sourceOptionsOf(sources));
          const availableIds = new Set(sources.items.map((item) => item.source_id));
          const requestedSources = options?.enabledSources ?? [];
          const selectedAllPreviouslyKnown = previousSourceIds.length > 0 &&
            requestedSources.length === previousSourceIds.length &&
            previousSourceIds.every((id) => requestedSources.includes(id));
          const enabledSources = !requestedSources.length || selectedAllPreviouslyKnown
            ? sources.items.map((item) => item.source_id)
            : requestedSources.filter((id) => availableIds.has(id));
          if (!enabledSources.length) {
            throw new RunClientError("invalid_response", "분석에 사용할 데이터를 하나 이상 선택해 주세요.");
          }
          const accepted = await client.createRun(
            {
              question: normalized,
              start_at: seoulMidnight(options?.startAt ?? LIVE_START_AT),
              end_at: seoulMidnight(options?.endAt ?? LIVE_END_AT),
              enabled_sources: enabledSources,
            },
            controller.signal,
          );
          if (
            !mountedRef.current || controller.signal.aborted ||
            versionRef.current !== version
          ) return;
          runIdRef.current = accepted.run_id;
          // status_url 계약을 실제로 확인하고, SSE는 독립적으로 즉시 구독한다.
          void client.getRun(accepted.run_id, controller.signal).then((snapshot) => {
            if (
              snapshot.status === "failed" && mountedRef.current &&
              versionRef.current === version && !controller.signal.aborted
            ) {
              fail(snapshot.error ?? { code: "run_failed", message: "분석을 완료하지 못했어요." });
            }
          }).catch(() => {
            // SSE가 authoritative 진행 채널이므로 초기 snapshot 실패만으로 중단하지 않는다.
          });
          void consumeStream(accepted.run_id, controller, version);
        } catch (error) {
          if (
            !mountedRef.current || controller.signal.aborted || isAbort(error) ||
            versionRef.current !== version
          ) return;
          fail(publicError(error));
        }
      })();
    },
    [client, consumeStream, fail],
  );

  const retry = useCallback(() => {
    setSession((current) => {
      queueMicrotask(() => start(current.question, lastStartOptionsRef.current));
      return current;
    });
  }, [start]);

  const answerClarification = useCallback(
    (answer: string) => {
      const runId = runIdRef.current;
      const controller = abortRef.current;
      if (!runId || !controller || controller.signal.aborted) return;
      const version = versionRef.current;
      void client.submitClarification(runId, answer, controller.signal).then(() => {
        if (
          !mountedRef.current || controller.signal.aborted ||
          versionRef.current !== version
        ) return;
        setSession((current) => ({ ...current, clarification: null }));
        if (!streamActiveRef.current) {
          void consumeStream(runId, controller, version, lastEventIdRef.current);
        }
      }).catch((error) => {
        if (!controller.signal.aborted && !isAbort(error)) fail(publicError(error));
      });
    },
    [client, consumeStream, fail],
  );

  const restore = useCallback((view: ViewParam) => {
    setSession((current) =>
      current.report || view === "action" ? { ...current, phase: view } : current,
    );
  }, []);

  const restoreRun = useCallback(
    (rawRunId: string, view: ViewParam = "result") => {
      const runId = rawRunId.trim();
      if (!runId) return;

      versionRef.current += 1;
      const version = versionRef.current;
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      runIdRef.current = runId;
      lastEventIdRef.current = 0;
      plansRef.current = [];
      factsRef.current = [];
      durationsRef.current = {};
      traceRef.current = [];
      topologyEventLogRef.current = [];
      reportRef.current = null;
      startedAtRef.current = Date.now();
      setBursting(false);
      setFlatline(false);
      setTick(null);
      setLog([]);
      setTopologyEvents([]);
      setEvidence({});
      setEvidenceLoadingId(null);
      setEvidenceErrorId(null);
      setSession({ ...idleSession(), phase: "catching" });

      void (async () => {
        try {
          const snapshotPromise = client.getRun(runId, controller.signal);
          const sourcesPromise = client.listSources(controller.signal).catch(
            () => sourceListRef.current,
          );
          const [snapshot, sourceResponse] = await Promise.all([
            snapshotPromise,
            sourcesPromise,
          ]);
          if (
            !mountedRef.current || controller.signal.aborted ||
            versionRef.current !== version
          ) return;

          const sources = activeSourceListOf(sourceResponse);
          sourceListRef.current = sources;
          setSourceCount(sources.items.length);
          setSourceOptions(sourceOptionsOf(sources));
          plansRef.current = snapshot.plan_history;
          factsRef.current = snapshot.facts;
          lastEventIdRef.current = snapshot.last_event_id ?? 0;
          startedAtRef.current = Date.parse(snapshot.created_at);
          reportRef.current = isCustomerSignalReport(snapshot.report)
            ? snapshot.report
            : null;
          setSession((current) => ({
            ...current,
            question: snapshot.request.question,
          }));

          if (snapshot.status === "failed") {
            fail(snapshot.error ?? {
              code: "run_failed",
              message: "분석을 완료하지 못했어요.",
            });
            return;
          }

          if (snapshot.status !== "completed" && snapshot.status !== "degraded") {
            void consumeStream(
              runId,
              controller,
              version,
              snapshot.last_event_id ?? 0,
            );
            return;
          }

          const report = reportRef.current;
          if (!report) {
            fail({
              code: "unsupported_report",
              message: "분석은 완료됐지만 결과를 불러오지 못했어요. 다시 시도해 주세요.",
            });
            return;
          }

          let journey = report.representative_journeys;
          const customerId = firstJourneyCustomer(snapshot.facts);
          if (customerId) {
            try {
              const detail = await client.getJourney(runId, customerId, controller.signal);
              journey = detail.events;
            } catch (error) {
              if (controller.signal.aborted || isAbort(error)) return;
              // 저장된 공개 리포트의 대표 여정으로 결과 화면을 계속 복원한다.
            }
          }
          if (
            !mountedRef.current || controller.signal.aborted ||
            versionRef.current !== version
          ) return;

          const catchReport = toCatchReport({
            runId,
            report,
            plans: snapshot.plan_history,
            facts: snapshot.facts,
            stepDurations: {},
            traceLog: [],
            sourceLabels: sourceLabelsOf(sources),
            journey,
            startedAt: Date.parse(snapshot.created_at),
            completedAt: snapshot.updated_at,
          });
          setSession({
            ...idleSession(),
            phase: view,
            question: snapshot.request.question,
            stages: completedStages(),
            outcome: snapshot.status === "degraded" ? "degraded" : "completed",
            report: catchReport,
          });
        } catch (error) {
          if (
            !mountedRef.current || controller.signal.aborted || isAbort(error) ||
            versionRef.current !== version
          ) return;
          fail(publicError(error));
        }
      })();
    },
    [client, consumeStream, fail],
  );
  const openTrace = useCallback(() => {
    setSession((current) => current.report ? { ...current, phase: "trace" } : current);
  }, []);
  const closeTrace = useCallback(() => {
    setSession((current) => current.phase === "trace" ? { ...current, phase: "result" } : current);
  }, []);
  const openAction = useCallback(() => {
    setSession((current) => current.report ? { ...current, phase: "action" } : current);
  }, []);
  const closeAction = useCallback(() => {
    setSession((current) => current.phase === "action"
      ? { ...current, phase: current.report ? "result" : "ask" }
      : current);
  }, []);

  const loadEvidence = useCallback(
    (evidenceId: string) => {
      const runId = runIdRef.current;
      const controller = abortRef.current;
      if (!runId || !controller || controller.signal.aborted || evidence[evidenceId]) return;
      const version = versionRef.current;
      setEvidenceLoadingId(evidenceId);
      setEvidenceErrorId(null);
      void client.getEvidence(runId, evidenceId, controller.signal).then((result) => {
        if (
          !mountedRef.current || controller.signal.aborted ||
          versionRef.current !== version
        ) return;
        setEvidence((current) => ({
          ...current,
          ...Object.fromEntries(result.records.map((record) => [record.evidence_id, record])),
        }));
        setEvidenceLoadingId(null);
        if (!result.records.some((record) => record.evidence_id === evidenceId)) {
          setEvidenceErrorId(evidenceId);
        }
      }).catch((error) => {
        if (controller.signal.aborted || isAbort(error)) return;
        setEvidenceLoadingId(null);
        setEvidenceErrorId(evidenceId);
      });
    },
    [client, evidence],
  );

  const reset = useCallback(() => {
    versionRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    runIdRef.current = null;
    if (burstTimerRef.current) clearTimeout(burstTimerRef.current);
    setBursting(false);
    setFlatline(false);
    setTick(null);
    setLog([]);
    topologyEventLogRef.current = [];
    setTopologyEvents([]);
    setEvidence({});
    setEvidenceLoadingId(null);
    setEvidenceErrorId(null);
    setSession(idleSession());
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    const controller = new AbortController();
    void client.listSources(controller.signal).then((response) => {
      if (!controller.signal.aborted) {
        const sources = activeSourceListOf(response);
        sourceListRef.current = sources;
        setSourceCount(sources.items.length);
        setSourceOptions(sourceOptionsOf(sources));
      }
    }).catch(() => {
      // 첫 Run 직전에 재조회하므로 초기 연결 실패는 입력 화면을 막지 않는다.
    });
    return () => {
      mountedRef.current = false;
      controller.abort();
      abortRef.current?.abort();
      if (burstTimerRef.current) clearTimeout(burstTimerRef.current);
    };
  }, [client]);

  return useMemo(
    () => ({
      session,
      bursting,
      flatline,
      tick,
      log,
      activities,
      topologyEvents,
      start,
      retry,
      answerClarification,
      restore,
      restoreRun,
      openTrace,
      closeTrace,
      openAction,
      closeAction,
      evidence,
      evidenceLoadingId,
      evidenceErrorId,
      loadEvidence,
      sourceCount,
      periodLabel: "2026.09.04 – 09.17",
      conditionsLocked: false,
      periodLocked: true,
      sourceOptions,
      periodStartAt: "2026-09-04",
      periodEndAt: "2026-09-18",
      reset,
    }),
    [
      session,
      bursting,
      flatline,
      tick,
      log,
      activities,
      topologyEvents,
      start,
      retry,
      answerClarification,
      restore,
      restoreRun,
      openTrace,
      closeTrace,
      openAction,
      closeAction,
      evidence,
      evidenceLoadingId,
      evidenceErrorId,
      loadEvidence,
      sourceCount,
      sourceOptions,
      reset,
    ],
  );
}
