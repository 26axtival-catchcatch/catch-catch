"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  CLARIFICATION,
  DEMO_QUESTION,
  DEGRADED_LIMITATIONS,
  EVIDENCE,
  REPORT,
  SOURCE_OPTIONS,
  STAGES,
  STAGE_TICKS,
  UNSUPPORTED_SUGGESTIONS,
} from "./mock";
import type {
  CatchReport,
  CatchSession,
  EvidenceMap,
  RunOutcome,
  Stage,
  StageKey,
  StageTick,
  SourceOption,
} from "./types";
import { useLiveCatchSession } from "./use-live-catch-session";

/**
 * 데모 시연용 분기. `?clarify=1` 처럼 붙여 엣지케이스 화면을 그대로 재현한다.
 * STEP 6에서 실제 Run Controller를 붙이면 이 분기는 백엔드 이벤트로 대체된다.
 */
export type DemoFlag = "clarify" | "degraded" | "failed" | "unsupported";

/** 로딩 연출을 판단하려고 특정 시점에 화면을 얼려 두는 시연용 옵션. */
export type PauseAt = StageKey | "complete" | "clarify";

/** 전환 순간의 마크. 팀 의견을 받아 보려고 시연 중 바꿀 수 있게 열어 뒀다. */
export type BurstMark = "heart" | "lens";

/** 결과와 검증 기록은 새로고침해도 살아남아야 한다. 시연 중 사고 방지. */
export type ViewParam = "result" | "trace" | "action";

/**
 * 첫 화면을 무엇으로 둘지. `?main=briefing` 으로 브리핑 안을 켜 본다.
 * 갈아끼울 때는 아래 useDemoOptions 의 기본값만 "briefing" 으로 바꾸면 된다.
 */
export type MainScreen = "ask" | "briefing";

/** 일반 접속은 목업 시그널 없이 실제 API 질문을 받는 empty-briefing 화면이다. */
const DEFAULT_MAIN: MainScreen = "briefing";

const PAUSE_KEYS: PauseAt[] = ["goal", "plan", "analyze", "insight", "verify", "complete", "clarify"];

function sumTicks(key: StageKey): number {
  return (STAGE_TICKS[key] ?? []).reduce((total, tick) => total + tick.ms, 0);
}

/** 진행 심박이 각 단계를 그리는 데 쓰는 시간. */
export const STAGE_DURATIONS: Record<StageKey, number> = {
  goal: sumTicks("goal"),
  plan: sumTicks("plan"),
  analyze: sumTicks("analyze"),
  insight: sumTicks("insight"),
  verify: sumTicks("verify"),
};



const BURST_MS = 1000;
const FLATLINE_MS = 1300;

function freshStages(): Stage[] {
  return STAGES.map((stage) => ({ ...stage, detail: null, status: "pending" }));
}

const IDLE_SESSION: CatchSession = {
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

function degradedReport(): CatchReport {
  return {
    ...REPORT,
    headlineTrailer: "다만 2개 소스는 확인하지 못했어요",
    limitations: [...DEGRADED_LIMITATIONS, ...REPORT.limitations],
    metrics: REPORT.metrics.map((metric) =>
      // 상담 소스가 빠지면 계산할 수 없는 지표는 숫자를 지어내지 않고 비워 둔다.
      metric.metric_key === "research_gap_days" ? { ...metric, value: Number.NaN } : metric,
    ),
    score: { ...REPORT.score, claimsPassed: 9, claimsTotal: 14, evidenceCoverage: 86, sources: 3 },
  };
}

export interface DemoOptions {
  flags: Set<DemoFlag>;
  pause: PauseAt | null;
  /** 전체 진행 속도 배수. 리허설이나 큰 무대에서 늦추고 싶을 때 쓴다. */
  speed: number;
  burst: BurstMark;
  /** 새로고침으로 들어온 화면. 로딩을 건너뛰고 바로 복원한다. */
  view: ViewParam | null;
  /** ask 단계에서 그릴 첫 화면. */
  main: MainScreen;
  /** 브리핑 API가 시그널을 하나도 주지 않은 경우를 재현한다. */
  briefingEmpty: boolean;
}

export function useDemoOptions(): DemoOptions {
  const [options, setOptions] = useState<DemoOptions>(() => ({
    flags: new Set(),
    pause: null,
    speed: 1,
    burst: "heart",
    view: null,
    main: DEFAULT_MAIN,
    briefingEmpty: true,
  }));

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const flags = new Set<DemoFlag>();
    for (const flag of ["clarify", "degraded", "failed", "unsupported"] as const) {
      // 시연 중에 `?clarify` 처럼 값 없이 붙여도 켜지도록 존재 여부만 본다.
      if (!params.has(flag)) continue;
      const value = params.get(flag);
      if (value === "0" || value === "false") continue;
      flags.add(flag);
    }
    const raw = params.get("pause");
    const pause = PAUSE_KEYS.find((key) => key === raw) ?? null;
    const parsedSpeed = Number(params.get("speed"));
    const speed = Number.isFinite(parsedSpeed) && parsedSpeed > 0
      ? Math.min(3, Math.max(0.25, parsedSpeed))
      : 1;
    const burst: BurstMark = params.get("burst") === "lens" ? "lens" : "heart";
    const viewRaw = params.get("view");
    const view: ViewParam | null =
      viewRaw === "result" || viewRaw === "trace" || viewRaw === "action" ? viewRaw : null;
    const main: MainScreen = params.get("main") === "briefing"
      ? "briefing"
      : params.get("main") === "ask"
        ? "ask"
        : DEFAULT_MAIN;
    // 기본은 실제 API용 빈 브리핑이다. 목업 카드는 명시적인 QA 옵션에서만 연다.
    const briefingEmpty = params.get("briefing") !== "mock";
    setOptions({ flags, pause, speed, burst, view, main, briefingEmpty });
  }, []);

  return options;
}

export interface CatchSessionController {
  session: CatchSession;
  /** 완료 직전 하트가 터지는 구간. 결과 화면 진입 연출에만 쓴다. */
  bursting: boolean;
  /** 실패 시 심박이 멎는 구간. */
  flatline: boolean;
  tick: StageTick | null;
  /** 지나간 진행 문장까지 포함한 로그. 화면은 뒤에서 몇 줄만 보여준다. */
  log: (StageTick & { stage: StageKey })[];
  start: (question: string, options?: CatchStartOptions) => void;
  /** 실패 화면에서 같은 질문으로 다시 실행한다. */
  retry: () => void;
  answerClarification: (answer: string) => void;
  restore: (view: ViewParam, question: string) => void;
  openTrace: () => void;
  closeTrace: () => void;
  /** 액션 상세로 이동. 어떤 액션인지는 셸이 따로 들고 있는다. */
  openAction: () => void;
  closeAction: () => void;
  evidence: EvidenceMap;
  evidenceLoadingId: string | null;
  evidenceErrorId: string | null;
  loadEvidence: (evidenceId: string) => void;
  sourceCount: number | null;
  periodLabel: string;
  conditionsLocked: boolean;
  periodLocked: boolean;
  sourceOptions: readonly SourceOption[];
  periodStartAt: string;
  periodEndAt: string;
  reset: () => void;
}

export interface CatchStartOptions {
  ignoreFlags?: boolean;
  enabledSources?: string[];
  startAt?: string;
  endAt?: string;
}

function useMockCatchSession({ flags, pause, speed, view }: DemoOptions): CatchSessionController {
  const [session, setSession] = useState<CatchSession>(IDLE_SESSION);
  const [bursting, setBursting] = useState(false);
  const [flatline, setFlatline] = useState(false);
  const [tick, setTick] = useState<StageTick | null>(null);
  const [log, setLog] = useState<(StageTick & { stage: StageKey })[]>([]);

  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const resumeAt = useRef<StageKey | null>(null);
  /** 재시도할 때는 시연용 분기를 한 번 무시해 정상 완주시킨다. */
  const suppressFlags = useRef(false);

  const clearTimers = useCallback(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  }, []);

  useEffect(() => clearTimers, [clearTimers]);

  const later = useCallback((ms: number, fn: () => void) => {
    timers.current.push(setTimeout(fn, ms));
  }, []);

  const settle = useCallback(
    (outcome: RunOutcome) => {
      setTick(null);
      setBursting(true);
      later(BURST_MS * speed, () => {
        setBursting(false);
        setSession((prev) => ({
          ...prev,
          phase: "result",
          outcome,
          report: outcome === "degraded" ? degradedReport() : REPORT,
        }));
      });
    },
    [later, speed],
  );

  /** 남은 단계를 순서대로 재생한다. clarification 이후 재개할 때도 같은 함수를 쓴다. */
  const playFrom = useCallback(
    (startKey: StageKey) => {
      const order = STAGES.map((stage) => stage.key);
      const startIndex = order.indexOf(startKey);
      let offset = 0;

      let interrupted = false;

      for (const key of order.slice(startIndex)) {
        const ticks = STAGE_TICKS[key] ?? [];

        later(offset, () => {
          setSession((prev) => ({
            ...prev,
            activeStage: key,
            stages: prev.stages.map((stage) =>
              stage.key === key
                ? { ...stage, status: "active" }
                : order.indexOf(stage.key) < order.indexOf(key)
                  ? { ...stage, status: "done" }
                  : stage,
            ),
          }));
        });

        let tickOffset = 0;
        ticks.forEach((entry) => {
          const at = tickOffset;
          tickOffset += entry.ms * speed;
          later(offset + at, () => {
            setTick(entry);
            setLog((prev) =>
              prev.some((item) => item.text === entry.text)
                ? prev
                : [...prev, { ...entry, stage: key }],
            );
            setSession((prev) => ({
              ...prev,
              stages: prev.stages.map((stage) =>
                stage.key === key ? { ...stage, detail: entry.text } : stage,
              ),
            }));
          });
        });

        offset += tickOffset;

        // 데모 분기: 특정 단계가 끝나는 시점에 엣지케이스로 빠진다.
        if (key === "goal" && !suppressFlags.current && flags.has("clarify")) {
          later(offset, () => {
            resumeAt.current = "plan";
            setTick(null);
            setSession((prev) => ({ ...prev, clarification: CLARIFICATION }));
          });
          interrupted = true;
          break;
        }

        if (key === "goal" && !suppressFlags.current && flags.has("unsupported")) {
          later(offset, () => {
            setTick(null);
            setSession((prev) => ({
              ...IDLE_SESSION,
              question: prev.question,
              failureReason:
                "이 질문은 지금 연결된 데이터로 답하기 어려워요. 대신 아래 질문은 바로 캐치할 수 있어요.",
              suggestedQuestions: UNSUPPORTED_SUGGESTIONS,
            }));
          });
          interrupted = true;
          break;
        }

        if (key === "analyze" && !suppressFlags.current && flags.has("failed")) {
          later(offset, () => {
            setTick(null);
            setFlatline(true);
            setSession((prev) => ({
              ...prev,
              outcome: "failed",
              failureReason: "앱 행동로그를 읽는 중에 연결이 끊겼어요.",
            }));
          });
          interrupted = true;
          break;
        }
      }

      if (interrupted) return;

      later(offset, () => {
        setSession((prev) => ({
          ...prev,
          activeStage: null,
          stages: prev.stages.map((stage) => ({ ...stage, status: "done" })),
        }));
        settle(!suppressFlags.current && flags.has("degraded") ? "degraded" : "completed");
      });
    },
    [flags, later, settle, speed],
  );

  /** 정지 모드: 타이머를 걸지 않고 지정한 시점의 화면을 그대로 만들어 둔다. */
  const freeze = useCallback(
    (at: PauseAt, question: string) => {
      const order = STAGES.map((stage) => stage.key);
      const stageKey: StageKey = at === "complete" ? "verify" : at === "clarify" ? "goal" : at;
      const index = order.indexOf(stageKey);
      const filled = at === "complete";

      const stages = freshStages().map((stage, i) => ({
        ...stage,
        status: filled || i < index ? "done" : i === index ? "active" : "pending",
        detail: i <= index ? (STAGE_TICKS[stage.key]?.at(-1)?.text ?? null) : null,
      })) as Stage[];

      setSession({
        ...IDLE_SESSION,
        phase: "catching",
        question,
        stages,
        activeStage: filled ? null : stageKey,
        clarification: at === "clarify" ? CLARIFICATION : null,
      });
      setTick(STAGE_TICKS[stageKey]?.at(-1) ?? null);
      setLog(
        stages
          .filter((stage) => stage.status !== "pending")
          .flatMap((stage) =>
            (STAGE_TICKS[stage.key] ?? []).map((entry) => ({ ...entry, stage: stage.key })),
          ),
      );
      setBursting(filled);
      setFlatline(false);
    },
    [],
  );

  const start = useCallback(
    (question: string, options?: CatchStartOptions) => {
      clearTimers();
      setBursting(false);
      setFlatline(false);
      setTick(null);
      resumeAt.current = null;
      suppressFlags.current = Boolean(options?.ignoreFlags);
      if (pause) {
        freeze(pause, question);
        return;
      }
      setLog([]);
      setSession({ ...IDLE_SESSION, phase: "catching", question, stages: freshStages() });
      playFrom("goal");
    },
    [clearTimers, freeze, pause, playFrom],
  );

  // 정지 모드는 URL 만으로 바로 그 화면이 보이도록 자동 진입한다.
  useEffect(() => {
    if (!pause) return;
    freeze(pause, DEMO_QUESTION);
  }, [pause, freeze]);

  /** 뒤로가기나 새로고침으로 결과 URL 에 들어온 경우 로딩 없이 그 화면을 세운다. */
  const restore = useCallback((next: ViewParam, question: string) => {
    clearTimers();
    setBursting(false);
    setFlatline(false);
    setTick(null);
    setSession({
      ...IDLE_SESSION,
      phase: next,
      question,
      stages: freshStages().map((stage) => ({ ...stage, status: "done" })),
      outcome: "completed",
      report: REPORT,
    });
  }, [clearTimers]);

  useEffect(() => {
    if (pause || !view) return;
    restore(view, DEMO_QUESTION);
  }, [pause, view, restore]);

  /*
   * 엣지케이스 플래그도 URL 만 열면 바로 그 상태가 보이게 한다.
   * `?pause=` 만 자동 진입하고 나머지는 질문을 직접 실행해야 하면 시연 중 헷갈린다.
   */
  const autoStarted = useRef(false);
  useEffect(() => {
    if (pause || view || !flags.size || autoStarted.current) return;
    autoStarted.current = true;
    start(DEMO_QUESTION);
  }, [pause, view, flags, start]);

  const answerClarification = useCallback(
    (answer: string) => {
      clearTimers();
      const next = resumeAt.current ?? "plan";
      resumeAt.current = null;
      setSession((prev) => ({
        ...prev,
        clarification: null,
        stages: prev.stages.map((stage) =>
          stage.key === "goal" ? { ...stage, detail: `조건을 좁혔어요 — ${answer}` } : stage,
        ),
      }));
      if (pause) return;
      playFrom(next);
    },
    [clearTimers, pause, playFrom],
  );

  const retry = useCallback(() => {
    setSession((prev) => {
      const question = prev.question;
      queueMicrotask(() => start(question, { ignoreFlags: true }));
      return prev;
    });
  }, [start]);

  const openAction = useCallback(() => {
    setSession((prev) => (prev.report ? { ...prev, phase: "action" } : prev));
  }, []);

  const closeAction = useCallback(() => {
    setSession((prev) => (prev.phase === "action" ? { ...prev, phase: "result" } : prev));
  }, []);

  const openTrace = useCallback(() => {
    setSession((prev) => (prev.report ? { ...prev, phase: "trace" } : prev));
  }, []);

  const closeTrace = useCallback(() => {
    setSession((prev) => (prev.phase === "trace" ? { ...prev, phase: "result" } : prev));
  }, []);

  const reset = useCallback(() => {
    clearTimers();
    setBursting(false);
    setFlatline(false);
    setTick(null);
    setLog([]);
    setSession(IDLE_SESSION);
  }, [clearTimers]);

  const loadEvidence = useCallback((_evidenceId: string) => {
    // Mock Evidence는 이미 메모리에 있으므로 별도 요청이 필요 없다.
  }, []);

  return useMemo(
    () => ({
      session,
      bursting,
      flatline,
      tick,
      log,
      start,
      retry,
      restore,
      answerClarification,
      openTrace,
      closeTrace,
      openAction,
      closeAction,
      evidence: EVIDENCE,
      evidenceLoadingId: null,
      evidenceErrorId: null,
      loadEvidence,
      sourceCount: SOURCE_OPTIONS.length,
      periodLabel: "최근 14일",
      conditionsLocked: false,
      periodLocked: false,
      sourceOptions: SOURCE_OPTIONS,
      periodStartAt: "2026-08-05",
      periodEndAt: "2026-08-19",
      reset,
    }),
    [
      session,
      bursting,
      flatline,
      tick,
      log,
      start,
      retry,
      restore,
      answerClarification,
      openTrace,
      closeTrace,
      openAction,
      closeAction,
      loadEvidence,
      reset,
    ],
  );
}

/**
 * URL 시연 옵션은 기존 결정론적 Mock을 유지하고, 일반 사용자 흐름은 실제 Run API를 쓴다.
 * 두 훅을 항상 같은 순서로 호출해 React의 Hook 규칙을 지킨다.
 */
export function useCatchSession(options: DemoOptions): CatchSessionController {
  const mock = useMockCatchSession(options);
  const live = useLiveCatchSession();
  const usesMock = Boolean(options.pause || options.view || options.flags.size);
  return usesMock ? mock : live;
}
