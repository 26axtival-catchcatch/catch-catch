# 02. 아키텍처와 상태 계약

이 문서의 타입 정의는 **코드의 정본**입니다. 화면 컴포넌트는 이 계약만 보고 그리며,
데이터를 Mock 이 채우든 백엔드가 채우든 화면은 달라지지 않습니다.

---

## 1. 스택

| 항목 | 값 |
| --- | --- |
| Next.js | `16.3.1` · App Router · **`output: "export"` (정적 export)** |
| React | `19.2.8` |
| TypeScript | `5.9.3` |
| 스타일 | CSS Modules 전용. Tailwind·UI 라이브러리 **없음** |
| 테스트 | Vitest 3.2.7 + Testing Library, Playwright 1.62.1 |
| 외부 런타임 의존성 | **없음** (차트·애니메이션 라이브러리 전부 미사용. SVG 를 직접 그린다) |

`output: "export"` 인 이유: 화면 전환을 phase 로만 하고, 백엔드는 브라우저가
`NEXT_PUBLIC_API_BASE_URL` 로 직접 부르므로 Node 서버가 필요 없습니다.
**서버 컴포넌트·서버 액션·라우트 핸들러를 쓰면 빌드가 깨집니다.**

폰트는 `SignalCatcherApp` 안에서 Google Fonts 를 `<link>` 로 직접 로드합니다
(`next/font` 미사용).

---

## 2. 라우트

라우트는 **두 개뿐**입니다.

| 경로 | 렌더 | 비고 |
| --- | --- | --- |
| `/` | `SignalCatcherApp` | 새 화면 전부 |
| `/legacy` | `CustomerIntelligencePage` | 기존 Working Demo. **손대지 않는다** |

`src/features/customer-intelligence/` 는 `/legacy` 가 계속 쓰므로 삭제·수정하지
않습니다. 단 **타입(`contracts.ts`)은 재사용**합니다 — `SourceId`,
`AnalysisMetricFact`, `JourneyEvent`, `EvidenceRecord`.

---

## 3. 파일 구조

```
src/features/signal-catcher/
├ SignalCatcherApp.tsx        244  셸. phase 스위치 + URL 동기화 + 상단 바
├ Overlay.tsx                  28  드로어·모달 portal 목적지
├ catcher.module.css               ★ 디자인 토큰 전부 (.app 스코프)
│
├ state/
│  ├ types.ts                 254  ★ 뷰모델 계약 (이 문서 §5)
│  ├ mock.ts                  713  ★ 로밍 시나리오 데이터 전부
│  ├ action-mock.ts           186  액션 시나리오 (AS-IS/TO-BE·예측·타임랩스·채점)
│  ├ use-catch-session.ts     492  ★ 상태 엔진
│  ├ use-experiments.ts       132  실험 상태 + localStorage
│  └ tick-marks.ts             28  진행 문장 기호 매핑
│
├ brand/       Brand.tsx (SignalMark · Sparkle · SignalProgress · HeartBurst)
├ briefing/    BriefingScreen · use-swipe-deck · briefing-mock · types · index
├ ask/         AskScreen · ComposerMenu · TypewriterPlaceholder
├ catching/    CatchingScreen · ClarificationModal
├ result/      ResultScreen · JourneyFlow · ProcessTrace · EvidencePanel
├ trace/       TraceScreen
└ action/      ActionScreen · ExperimentMenu
```

**핵심은 별표 네 파일입니다.** 나머지는 표현 계층입니다.
CSS 는 각 디렉터리의 `*.module.css` 에 두고, 토큰만 `catcher.module.css` 에 모읍니다.

---

## 4. 데이터 흐름

```
app/page.tsx
     │
     ▼
SignalCatcherApp ──── useDemoOptions()      URL 쿼리 파싱 (시연 전용)
     │           └─── useCatchSession()     상태 엔진
     │                     │
     │                     ▼
     │                CatchSession  ◀── 화면이 소비하는 유일한 계약
     │
     ├─ ask       BriefingScreen (options.main === "briefing") 또는 AskScreen
     ├─ catching  CatchingScreen
     ├─ result    ResultScreen
     ├─ action    ActionScreen
     └─ trace     TraceScreen

useExperiments()  ← CatchSession 밖. localStorage 에 보관
```

셸이 직접 들고 있는 상태는 넷뿐입니다.

| 상태 | 용도 |
| --- | --- |
| `question` | 입력창의 현재 값. 화면을 오가도 보존 |
| `watchRequests` | 브리핑에서 이번 세션에 건 와쳐 요청. 배지 수에만 반영 |
| `actionId` | 어떤 액션 상세를 열지. 기본 `"search_keyword"` |
| `highlightActionId` | 액션 리포트에서 "이어지는 액션"으로 넘어왔을 때 안내할 카드 |

---

## 5. 상태 계약 (`state/types.ts`)

### 5.1 phase 전이

```
              start()             settle()           openTrace()
 ask ─────────────▶ catching ─────────────▶ result ─────────────▶ trace
  ▲                    │                    │  ▲                    │
  │                    │ retry()            │  │ closeAction()      │ closeTrace()
  │                    │                    ▼  │                    │
  │              (실패 시 그 자리에 멈춤)   action ◀── openAction() │
  └──────────────── reset() ───────────────────┴────────────────────┘
```

- **`catching` 은 되돌아갈 지점이 아닙니다.** History 에 남기지 않습니다.
- 실패해도 화면을 자동으로 바꾸지 않습니다. `catching` 에서 멈춰 세웁니다.
- `restore(view, question)` 는 로딩을 건너뛰고 `result` / `trace` / `action` 을 바로 세웁니다.

### 5.2 화면이 소비하는 단일 계약

```ts
export type CatchPhase = "ask" | "catching" | "result" | "trace" | "action";
export type StageKey = "goal" | "plan" | "analyze" | "insight" | "verify";
export type StageStatus = "pending" | "active" | "done";
export type RunOutcome = "completed" | "degraded" | "failed";

export interface CatchSession {
  phase: CatchPhase;
  question: string;
  stages: Stage[];
  activeStage: StageKey | null;
  clarification: ClarificationPrompt | null;
  outcome: RunOutcome | null;
  report: CatchReport | null;
  failureReason: string | null;
  suggestedQuestions: string[];
}
```

### 5.3 진행 표현

```ts
/** 로딩 화면 레일이 이 값에 따라 다르게 그린다. Canonical Run Event 와 1:1. */
export type TickKind = "think" | "tool" | "fact" | "reject";

export interface StageTick {
  kind: TickKind;
  primitive: string | null;  // tool 일 때만 primitive 이름
  text: string;              // 화면에 흐르는 문장
  meta: string;              // 대응하는 이벤트 payload 자리 (tool 일 때 우측 결과로 노출)
  short: string | null;      // fact 일 때 배지에 얹는 짧은 라벨
  ms: number;                // 화면에 머무는 시간
}

export interface Stage {
  key: StageKey;
  label: string;   // "분석 목표를 세우고 있어요"
  short: string;   // "목표"
  event: string;   // 대응 Canonical Run Event 이름. 화면에 노출(과정 보기)
  detail: string | null;
  status: StageStatus;
}
```

`kind` 별 의미와 기호는 [03 §3](03-screen-specs.md) 과 `state/tick-marks.ts` 를 보세요.

### 5.4 리포트

```ts
export interface CatchReport {
  headline: string;
  headlineCount: number;
  headlineTrailer: string | null;   // "다만 2개 소스는 확인하지 못했어요"
  summary: string;
  segmentLabel: string;
  metrics: AnalysisMetricFact[];    // value 가 NaN 이면 "근거 부족"
  journey: JourneyNode[];
  lanes: JourneyLane[];
  findings: LedgerClaim[];          // passed 와 rejected 를 함께 담는다
  actions: CatchAction[];
  limitations: string[];
  planSteps: PlanStep[];
  score: TraceScore;
  runId: string;                    // 과정 보기의 외부 트레이스 링크에 쓴다
  periodLabel: string;              // "2026.08.05 – 2026.08.19"
  analyzedAt: string;               // "2026.08.19"
  datasetVersion: string;
  adapterVersions: Record<SourceId, string>;
}

export interface LedgerClaim {
  claimId: string;
  statement: string;
  verdict: "passed" | "rejected";
  rejectedReason: string | null;
  chain: { claim: string; fact: string; source: string; evidence: string };
  evidenceIds: string[];
}

export interface TraceScore {
  claimsPassed: number; claimsTotal: number; evidenceCoverage: number;
  steps: number; sources: number; planRevisions: number; durationMs: number;
}

export interface PlanStep {
  stepId: string; primitive: string; objective: string;
  durationMs: number; revisedFrom: string | null;
}

export interface CatchAction {
  actionId: string; title: string; reason: string; evidenceIds: string[];
  /** 실행 화면을 갖는 액션만 채운다. null 이면 "다음 단계" 라벨만 붙는다. */
  keywords: KeywordSuggestion[] | null;
}

/** JourneyEvent(백엔드 계약)에 레인 좌표와 강도를 얹은 표현용 값. */
export interface JourneyNode extends JourneyEvent {
  lane: SourceId;
  column: number;                                        // 시간순 위치 (한 열에 하나)
  intensity: number;                                     // 0~1
  tone: "signal" | "negative" | "repeat" | "resolved";
  insight: string;
}
```

> **`signals` 필드는 없습니다.** v1 문서에 있던 "시그널 기여도 바"는 현재 구현에
> 존재하지 않습니다. 강도 표현은 `JourneyNode.intensity` 곡선 하나뿐입니다.

### 5.5 액션과 실험

```ts
export interface Prediction {
  predictionId: string;
  direction: "gain" | "risk";      // 좋아질 것과 나빠질 것을 같은 모양으로 싣는다
  label: string; from: string; to: string; delta: string;
  reason: string; evidenceIds: string[];
}

export interface PredictionOutcome {
  predictionId: string; actual: string;
  verdict: "hit" | "miss"; note: string;
}

export interface ActionPlan {
  actionId: string; title: string;
  segmentLabel: string;             // 실험 겹침 판정 키
  segmentSize: number; applyLabel: string;
  asIs: ActionMockup; toBe: ActionMockup;
  predictions: Prediction[];
  observeDays: number;
  timelapse: TimelapsePoint[];
  outcomes: PredictionOutcome[];
  nextActionId: string | null;      // 채점 결과가 정당화하는 다음 액션
  nextActionReason: string | null;
}

export type ActionStage = "preview" | "watching" | "report";

/** Run 하나보다 오래 산다. localStorage 키: "catchers.experiments.v1" */
export interface Experiment {
  actionId: string; title: string; segmentLabel: string;
  observeDays: number; elapsedDays: number;
  status: "watching" | "done";
  startedAt: string; hits: number; total: number;
}
```

### 5.6 브리핑 (`briefing/types.ts`)

브리핑 계약은 **전부 직렬화되는 값**입니다. `ReactNode` 를 담지 않아야 나중에
백엔드 브리핑 API 가 그대로 실어 보낼 수 있습니다.

```ts
export interface BriefingSignal {
  id: string;
  name: string;         // "로밍 상품 결정 지연"
  headline: string;     // `*로 감싼 구간*` 이 마젠타로 칠해진다 (마크업이 아니라 문자열 규칙)
  body: string;
  metrics: BriefingMetric[];        // { label, value, delta, direction: "up" | "down" }
  trend: number[];                  // 0~1 로 정규화한 스파크라인 값
  evidenceNote: string;             // "근거 3개 소스 · 로밍 / 상담 / VOC"
  fromRequest: boolean;             // 내 요청으로 잡힌 시그널이면 배지
  chipLabel: string;
}

export interface Briefing {
  dateLabel: string; lede: string; signals: BriefingSignal[];
  requestCount: number; watchingCount: number;
  pastDates: string[]; backlogCount: number;
  askPlaceholder: string; suggestions: string[];
}
```

---

## 6. 컨트롤러 API

### 6.1 `useCatchSession(options): CatchSessionController`

| 항목 | 용도 |
| --- | --- |
| `session` | §5.2 계약 |
| `bursting` | 완료 직전 하트가 터지는 구간 (`BURST_MS = 1000`) |
| `flatline` | 진행이 멎은 구간. 심박이 평선으로 |
| `tick` | 현재 진행 문장 |
| `log` | 지나간 문장 누적. 화면은 뒤 9줄만 (`RAIL_WINDOW`) |
| `start(question, { ignoreFlags })` | 분석 시작 |
| `retry()` | 실패 화면에서 같은 질문 재실행 (시연 플래그 1회 무시) |
| `answerClarification(answer)` | 심문 모달 답변 → 남은 단계 재개 |
| `restore(view, question)` | 새로고침·뒤로가기 복원 |
| `openTrace()` / `closeTrace()` | 검증 기록 전환 |
| `openAction()` / `closeAction()` | 액션 전환 |
| `reset()` | 첫 화면으로 |

내부 구조 (백엔드로 갈아끼울 때 그대로 대체될 부분):

- `playFrom(startKey)` — 남은 단계를 `setTimeout` 으로 순서대로 재생.
  **`for...of` + `break` 를 씁니다. `forEach` 안의 `return` 은 루프를 멈추지 않습니다.**
- `freeze(at, question)` — 타이머 없이 특정 시점의 화면을 만들어 둠 (시연용 `?pause=`)
- `settle(outcome)` — 하트 버스트 후 `result` 로 전환
- `STAGE_DURATIONS` — `STAGE_TICKS[key]` 의 `ms` 합. 심박이 그려지는 시간

### 6.2 `useExperiments(): ExperimentStore`

| 항목 | 동작 |
| --- | --- |
| `experiments` / `watching` | 전체 / 관찰 중 |
| `find(actionId)` | 하나 찾기 |
| `conflictOf(segmentLabel, actionId)` | **같은 세그먼트를 관찰 중인 다른 실험**. 있으면 적용 전에 경고 |
| `begin(item)` | 관찰 시작 (`status: "watching"`, `elapsedDays: 0`) |
| `advance(actionId, days)` | 타임랩스 진행 |
| `complete(actionId, hits, total)` | 채점 확정 (`status: "done"`) |
| `clear()` | 전체 삭제 |

SSR 과 첫 렌더를 맞추기 위해 **마운트 뒤에** `localStorage` 를 읽습니다.
읽기·쓰기 실패는 조용히 넘깁니다.

### 6.3 `useDemoOptions(): DemoOptions`

URL 쿼리를 파싱해 시연 스위치를 만듭니다. 파라미터 목록은 [03 §7](03-screen-specs.md).

```ts
interface DemoOptions {
  flags: Set<"clarify" | "degraded" | "failed" | "unsupported">;
  pause: StageKey | "complete" | "clarify" | null;
  speed: number;                 // 0.25 ~ 3
  burst: "heart" | "lens";
  view: "result" | "trace" | "action" | null;
  main: "ask" | "briefing";      // 기본값은 DEFAULT_MAIN = "ask"
}
```

---

## 7. URL 동기화

라우트를 쪼개지 않고 History API 로 상태만 반영합니다 (`syncUrl()`).

| URL | 화면 |
| --- | --- |
| `/` | 첫 화면 (질문하기 또는 브리핑) |
| `/?view=result` | 캐치 결과 |
| `/?view=trace` | 검증 기록 |
| `/?view=action` | 액션 |

- `catching` 은 기록하지 않습니다.
- `popstate` 를 듣고 `restore()` 또는 `reset()` 합니다.
- `phase` 가 바뀌면 스크롤을 즉시 맨 위로 되돌립니다
  (`window.scrollTo({ top: 0, behavior: "instant" })`).

> 백엔드 연결 후에는 `?view=result` 대신 **`/runs/{run_id}`** 같은 실제 run id 기반
> URL 로 올려야 합니다. 지금은 Mock 이 하나뿐이라 파라미터로 둔 것입니다.
> 단 `output: "export"` 이므로 동적 세그먼트는 쓸 수 없고, 쿼리(`/?run=<id>`)로 두는
> 편이 정적 export 와 맞습니다.

---

## 8. 오버레이 규칙 (반드시 지킬 것)

근거 드로어 · 심문 모달 · 실험 충돌 모달은 전부 `Overlay.tsx` 를 거칩니다.

화면 전환 래퍼(`.enter`)는 `animation-fill-mode: both` 로 끝난 뒤에도 `transform` 이
남고, **transform 이 있는 조상은 `position: fixed` 의 기준점이 됩니다.** 그대로 두면
스크롤을 내린 상태에서 오버레이가 화면 밖에 그려집니다.

디자인 토큰이 `.app` 안에만 정의돼 있으므로 `document.body` 가 아니라 `.app` 안쪽의
`#catcher-overlay-root` 로 보냅니다.

> **새 모달·드로어·툴팁을 추가할 때 반드시 `Overlay` 로 감싸세요.**
