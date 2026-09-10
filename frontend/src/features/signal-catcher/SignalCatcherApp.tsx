"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ActionScreen } from "./action/ActionScreen";
import { ExperimentMenu } from "./action/ExperimentMenu";
import { SignalAlertInbox } from "./alerts/SignalAlertInbox";
import { useSignalAlerts } from "./alerts/use-signal-alerts";
import { AskScreen } from "./ask/AskScreen";
import { BriefingScreen } from "./briefing/BriefingScreen";
import { DEMO_BRIEFING } from "./briefing/briefing-mock";
import { useSignalBriefing } from "./briefing/use-signal-briefing";
import { SignalMark } from "./brand/Brand";
import { CatchingScreen } from "./catching/CatchingScreen";
import { ResultScreen } from "./result/ResultScreen";
import { SignalDetailModal } from "./signals/SignalDetailModal";
import {
  type ViewParam,
  useCatchSession,
  useDemoOptions,
} from "./state/use-catch-session";
import { ACTION_PLANS } from "./state/action-mock";
import { DEMO_QUESTION } from "./state/mock";
import { useExperiments } from "./state/use-experiments";
import { OVERLAY_ID } from "./Overlay";
import { TraceScreen } from "./trace/TraceScreen";

import styles from "./catcher.module.css";

const FONT_HREF =
  "https://fonts.googleapis.com/css2?family=Gasoek+One&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap";

/**
 * 화면 상태를 URL 에 반영한다. 라우트를 쪼개면 전환 연출이 끊기기 때문에
 * 한 페이지를 유지한 채 history 만 동기화한다.
 * 새로고침, 뒤로가기, 링크 공유가 모두 살아난다.
 */
function syncDemoUrl(phase: string, push: boolean) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (phase === "result" || phase === "trace" || phase === "action") {
    url.searchParams.set("view", phase);
  }
  else url.searchParams.delete("view");
  const next = `${url.pathname}${url.search}`;
  if (next === `${window.location.pathname}${window.location.search}`) return;
  if (push) window.history.pushState({ phase }, "", next);
  else window.history.replaceState({ phase }, "", next);
}

function runPath(runId: string, view: ViewParam = "result"): string {
  const path = `/runs/${encodeURIComponent(runId)}`;
  return view === "result" ? path : `${path}?view=${view}`;
}

function runIdFromPath(pathname: string): string | null {
  const matched = /^\/runs\/([^/]+)\/?$/.exec(pathname);
  if (!matched) return null;
  try {
    return decodeURIComponent(matched[1]);
  } catch {
    return null;
  }
}

function viewFromUrl(url: URL): ViewParam {
  const view = url.searchParams.get("view");
  return view === "trace" || view === "action" ? view : "result";
}

function syncRunUrl(phase: string, runId: string | null, push: boolean) {
  if (typeof window === "undefined") return;
  const next = phase === "result" || phase === "trace" || phase === "action"
    ? runId
      ? runPath(runId, phase)
      : "/"
    : "/";
  if (next === `${window.location.pathname}${window.location.search}`) return;
  if (push) window.history.pushState({ phase, runId }, "", next);
  else window.history.replaceState({ phase, runId }, "", next);
}

interface SignalCatcherAppProps {
  initialRunId?: string;
  initialView?: ViewParam;
}

export function SignalCatcherApp({
  initialRunId,
  initialView = "result",
}: SignalCatcherAppProps = {}) {
  const options = useDemoOptions();
  const controller = useCatchSession(options, initialRunId);
  const { session, reset, restore, restoreRun } = controller;
  const usesDemo = Boolean(
    options.pause || options.flags.size || (options.view && !initialRunId),
  );

  const experiments = useExperiments();
  const liveBriefing = useSignalBriefing();
  const signalAlerts = useSignalAlerts();
  const [question, setQuestion] = useState("");
  const [selectedSignalId, setSelectedSignalId] = useState<string | null>(null);
  const sourceLabels = useMemo(
    () => Object.fromEntries(controller.sourceOptions.map((source) => [source.id, source.label])),
    [controller.sourceOptions],
  );
  const closeSignal = useCallback(() => setSelectedSignalId(null), []);
  const [actionId, setActionId] = useState<string>("search_keyword");
  /** 리포트에서 "이어지는 액션"으로 넘어왔을 때 결과 화면이 안내할 카드. */
  const [highlightActionId, setHighlightActionId] = useState<string | null>(null);
  const lastPhase = useRef(session.phase);

  useEffect(() => {
    if (!initialRunId || usesDemo) return;
    restoreRun(initialRunId, initialView);
  }, [initialRunId, initialView, restoreRun, usesDemo]);

  // 로딩(catching)은 되돌아갈 지점이 아니라서 기록에 남기지 않는다.
  useEffect(() => {
    if (options.pause) return;
    if (lastPhase.current === session.phase) return;
    lastPhase.current = session.phase;
    if (session.phase === "catching") return;
    if (usesDemo) syncDemoUrl(session.phase, true);
    else syncRunUrl(session.phase, session.report?.runId ?? null, true);
  }, [session.phase, session.report?.runId, options.pause, usesDemo]);

  /*
   * 화면이 바뀌면 스크롤을 처음으로 되돌린다.
   * 한 페이지에서 phase 만 갈아끼우기 때문에 그대로 두면
   * 아래쪽에서 누른 버튼의 스크롤 위치를 다음 화면이 물려받는다.
   */
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
  }, [session.phase]);

  useEffect(() => {
    if (options.pause) return;
    function onPop() {
      const url = new URL(window.location.href);
      if (usesDemo) {
        const view = url.searchParams.get("view");
        if (view === "result" || view === "trace" || view === "action") {
          restore(view, session.question || DEMO_QUESTION);
          return;
        }
        reset();
        return;
      }

      const runId = runIdFromPath(url.pathname);
      if (!runId) {
        reset();
        return;
      }
      const view = viewFromUrl(url);
      if (session.report?.runId === runId) restore(view, session.question);
      else restoreRun(runId, view);
    }
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [restore, restoreRun, reset, session.question, session.report?.runId, options.pause, usesDemo]);

  // 자동 진입이나 새로고침 복원으로 들어와도 입력창에 질문이 남아 있어야 한다.
  useEffect(() => {
    if (session.question && !question) setQuestion(session.question);
  }, [session.question, question]);

  function openAction() {
    if (!session.report) controller.restore("action", session.question || DEMO_QUESTION);
    else controller.openAction();
  }

  function restart() {
    controller.reset();
    setQuestion("");
  }

  return (
    <div className={styles.app}>
      <link rel="preconnect" href="https://fonts.googleapis.com" />
      <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
      <link rel="stylesheet" href={FONT_HREF} />

      <header className={styles.bar}>
        <button type="button" className={styles.brand} onClick={restart}>
          <SignalMark size={26} title="고객 시그널 캐처 홈" />
          <span className={styles.brandText}>
            <strong>캐치캐치</strong>
            <small>Customer Signal Catcher</small>
          </span>
        </button>
        <span className={styles.barSpacer} />
        <SignalAlertInbox
          events={signalAlerts.events}
          error={signalAlerts.error}
          onOpenSignal={setSelectedSignalId}
          onClear={signalAlerts.clear}
        />
        <ExperimentMenu
          experiments={experiments.experiments}
          onOpen={(id) => {
            setActionId(id);
            openAction();
          }}
        />
      </header>

      <main className={styles.stage}>
        {session.phase === "ask" ? (
          <div key="ask" className={styles.enter}>
            {options.main === "briefing" ? (
              <BriefingScreen
                briefing={options.briefingEmpty
                  ? liveBriefing.briefing ?? { ...DEMO_BRIEFING, signals: [], total: 0, requestCount: 0 }
                  : DEMO_BRIEFING}
                loading={options.briefingEmpty && liveBriefing.loading}
                loadingMore={options.briefingEmpty && liveBriefing.loadingMore}
                loadMoreError={options.briefingEmpty ? liveBriefing.loadMoreError : null}
                error={options.briefingEmpty ? liveBriefing.error : null}
                onRetry={liveBriefing.refresh}
                onLoadMore={liveBriefing.loadMore}
                question={question}
                onQuestionChange={setQuestion}
                notice={session.failureReason}
                suggestedQuestions={session.suggestedQuestions}
                sourceCount={controller.sourceCount}
                fixedPeriodLabel={controller.periodLabel}
                conditionsLocked={controller.conditionsLocked}
                periodLocked={controller.periodLocked}
                sourceOptions={controller.sourceOptions}
                initialStartAt={controller.periodStartAt}
                initialEndAt={controller.periodEndAt}
                sourceLabels={sourceLabels}
                onOpenSignal={(signal) => setSelectedSignalId(signal.id)}
                onAsk={(asked, conditions) => {
                  setQuestion(asked);
                  controller.start(asked, {
                    enabledSources: conditions.enabledSources,
                    startAt: conditions.startAt,
                    endAt: conditions.endAt,
                  });
                }}
              />
            ) : (
              <AskScreen
                question={question}
                onQuestionChange={setQuestion}
                onSubmit={(conditions) => controller.start(question, {
                  enabledSources: conditions.enabledSources,
                  startAt: conditions.startAt,
                  endAt: conditions.endAt,
                })}
                notice={session.failureReason}
                suggestedQuestions={session.suggestedQuestions}
                sourceCount={controller.sourceCount}
                fixedPeriodLabel={controller.periodLabel}
                conditionsLocked={controller.conditionsLocked}
                periodLocked={controller.periodLocked}
                sourceOptions={controller.sourceOptions}
                initialStartAt={controller.periodStartAt}
                initialEndAt={controller.periodEndAt}
              />
            )}
          </div>
        ) : null}

        {session.phase === "catching" ? (
          <div key="catching" className={styles.enter}>
            <CatchingScreen
              session={session}
              bursting={controller.bursting}
              flatline={controller.flatline}
              burstMark={options.burst}
              speed={options.speed}
              log={controller.log}
              activities={controller.activities}
              topologyEvents={controller.topologyEvents}
              onAnswerClarification={controller.answerClarification}
              onRetry={controller.retry}
              onGiveUp={restart}
            />
          </div>
        ) : null}

        {session.phase === "result" && session.report ? (
          <div key="result" className={styles.enter}>
            <ResultScreen
              report={session.report}
              outcome={session.outcome ?? "completed"}
              onOpenTrace={controller.openTrace}
              onRestart={restart}
              onOpenAction={(id) => {
                setActionId(id);
                controller.openAction();
              }}
              experimentOf={experiments.find}
              highlightActionId={highlightActionId}
              onHighlightSeen={() => setHighlightActionId(null)}
              applied={experiments.experiments}
              evidence={controller.evidence}
              evidenceLoadingId={controller.evidenceLoadingId}
              evidenceErrorId={controller.evidenceErrorId}
              onLoadEvidence={controller.loadEvidence}
              onGoHome={() => {
                liveBriefing.refresh();
                restart();
              }}
            />
          </div>
        ) : null}

        {session.phase === "action" && ACTION_PLANS[actionId] ? (
          <div key="action" className={styles.enter}>
            <ActionScreen
              plan={ACTION_PLANS[actionId]}
              experiment={experiments.find(actionId)}
              conflict={experiments.conflictOf(
                ACTION_PLANS[actionId].segmentLabel,
                actionId,
              )}
              onApply={() =>
                experiments.begin({
                  actionId,
                  title: ACTION_PLANS[actionId].title,
                  segmentLabel: ACTION_PLANS[actionId].segmentLabel,
                  observeDays: ACTION_PLANS[actionId].observeDays,
                })
              }
              onAdvance={(days) => experiments.advance(actionId, days)}
              onComplete={(hits, total) => experiments.complete(actionId, hits, total)}
              onOpenNext={() => {
                setHighlightActionId(ACTION_PLANS[actionId].nextActionId);
                controller.closeAction();
              }}
              onBack={controller.closeAction}
            />
          </div>
        ) : null}

        {session.phase === "trace" && session.report ? (
          <div key="trace" className={styles.enter}>
            <TraceScreen
              report={session.report}
              question={session.question}
              onBack={controller.closeTrace}
            />
          </div>
        ) : null}
      </main>

      <footer className={styles.signature}>by 네박자</footer>

      {/* 드로어와 모달이 붙는 자리. 전환 래퍼의 transform 밖이어야 한다. */}
      <div id={OVERLAY_ID} />
      {selectedSignalId ? (
        <SignalDetailModal
          signalId={selectedSignalId}
          sourceLabels={sourceLabels}
          onClose={closeSignal}
          onChanged={liveBriefing.refresh}
        />
      ) : null}
    </div>
  );
}
