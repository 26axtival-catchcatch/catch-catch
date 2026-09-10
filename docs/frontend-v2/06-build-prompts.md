# 06. 실행 프롬프트

다른 LLM 세션에 그대로 붙여 넣어 작업을 시작할 수 있는 지시문 모음입니다.
**필요한 것만 복사해서 쓰세요.** 각 프롬프트는 이 문서 묶음을 읽는 것에서 시작합니다.

---

## A. 처음부터 만들기 (빈 저장소 → 화면 전부)

> 저장소가 없거나, 프론트엔드를 새로 짓는 경우입니다.

### A-0. 붙여 넣을 지시문

```
당신은 "캐치캐치(Customer Signal Catcher)" 프론트엔드를 처음부터 구현합니다.

읽을 문서 (이 순서대로, 전부):
  docs/frontend-v2/01-product-and-ux-brief.md      왜 이런 화면인지
  docs/frontend-v2/02-architecture-and-contracts.md  타입 계약과 구조 (정본)
  docs/frontend-v2/03-screen-specs.md               화면 6개 명세
  docs/frontend-v2/04-design-system.md              토큰·모션·함정
  docs/frontend-v2/05-data-and-backend.md           Mock 데이터 계약

전제:
- Next.js 16 App Router + React 19 + TypeScript. `output: "export"` (정적 export).
  서버 컴포넌트/서버 액션/라우트 핸들러를 쓰지 않습니다.
- 스타일은 CSS Modules 만 씁니다. Tailwind·UI 라이브러리·차트 라이브러리를
  추가하지 마세요. 그래프와 아이콘은 SVG 를 직접 그립니다.
- 데이터는 전부 Mock 상수입니다. 네트워크 호출을 만들지 마세요.
- 한국어 UI. 코드 주석도 한국어로, "왜 이렇게 했는지"만 씁니다.

작업 순서는 아래 STEP 0~7 을 따르고, 각 STEP 끝에서
`npm --prefix frontend run typecheck` 와 `npm --prefix frontend run build` 를
통과시킨 뒤 다음으로 넘어갑니다.

절대 하지 말 것:
- 탈락한 주장, 빗나간 예측, "근거 부족" 지표, 타임랩스가 데모 데이터라는 안내를
  지우거나 숨기는 것
- 근거 없는 숫자를 화면에 만드는 것
- 화면을 라우트로 쪼개는 것 (phase 상태로만 전환)
```

### A-1. STEP 표

| STEP | 산출물 | 완료 기준 |
| --- | --- | --- |
| **0** | 프로젝트 골격, `catcher.module.css` 토큰, `brand/Brand.tsx`, `Overlay.tsx` | 상단 바에 마크와 워드마크가 보이고 다크 배경이 깔린다 |
| **1** | `state/types.ts` 전체, `state/mock.ts` 뼈대, `use-catch-session.ts`, `SignalCatcherApp.tsx` | `?view=result` 로 빈 결과 화면이 뜨고 phase 전환이 동작 |
| **2** | `ask/` — AskScreen · ComposerMenu · TypewriterPlaceholder | 질문 입력 → `catching` 전환. 좌우 시그널 파형 동작 |
| **3** | `catching/` — CatchingScreen · ClarificationModal, `SignalProgress`, `tick-marks.ts` | 11.5초 동안 5단계 심박과 레일이 흐르고 `HeartBurst` 로 끝난다. `?clarify` `?failed` 재현 |
| **4** | `result/` — ResultScreen · JourneyFlow · EvidencePanel | 헤드라인 → 여정 맵 → 발견/액션. 노드 클릭 시 근거 드로어 |
| **5** | `result/ProcessTrace.tsx`, `trace/TraceScreen.tsx` | 과정 보기가 펼쳐지고, 검증 기록에 탈락 주장이 사유와 함께 보인다 |
| **6** | `action/` — ActionScreen · ExperimentMenu, `use-experiments.ts`, `action-mock.ts` | 미리보기 → 적용 → 타임랩스 → 채점. 새로고침해도 실험 상태 유지 |
| **7** | `briefing/` — BriefingScreen · use-swipe-deck · briefing-mock | `?main=briefing` 으로 카드 덱이 뜨고 드래그로 넘어간다 |

각 STEP 의 상세 요구는 [03 화면 명세](03-screen-specs.md) 의 같은 번호 절을 봅니다.

### A-2. STEP 단위 지시문 예 (STEP 3)

```
STEP 3: "캐치하는 중" 화면을 구현합니다.

읽을 것: docs/frontend-v2/03-screen-specs.md §3, 04-design-system.md §3

만들 파일:
  src/features/signal-catcher/catching/CatchingScreen.tsx
  src/features/signal-catcher/catching/ClarificationModal.tsx
  src/features/signal-catcher/catching/catching.module.css
  src/features/signal-catcher/state/tick-marks.ts
  (brand/Brand.tsx 에 SignalProgress, HeartBurst 추가)

요구사항:
- 심박 라인이 곧 스테퍼입니다. 별도 스텝 인디케이터를 만들지 마세요.
  단계 하나 = 박동 하나이고, 진행 중 구간은 STAGE_DURATIONS[key] 시간에 맞춰
  stroke-dashoffset 으로 그려집니다.
- 진행 레일은 최근 9줄만 보여 주고 위쪽은 마스크로 흐려집니다.
  각 줄의 기호는 tick-marks.ts 의 markOf() 가 붙입니다.
  (think ✎ / tool 은 primitive별 기호 / fact ◈ / reject ✕)
- 상단에 "도구 N · 포착 N" 카운터를 둡니다.
- 심문 모달은 브라우저 기본 dialog 를 쓰지 않고 focus trap 을 직접 겁니다.
  닫기 버튼을 두지 않습니다 (백엔드가 답을 기다리는 중이므로).
- 실패 시 화면을 자동으로 바꾸지 마세요. 평선이 된 심박을 그대로 두고
  사유와 [다시 캐치하기] [질문 바꾸기] 를 붙입니다.
- prefers-reduced-motion 을 모든 애니메이션에서 처리합니다.

검증: `?pause=analyze`, `?clarify`, `?failed`, `?speed=0.5` 로 각 상태를 확인.
```

---

## B. 이어서 만들기 (현재 저장소에서 계속)

> 이미 `catch-catch/frontend` 가 있는 상태에서 다음 작업을 하는 경우입니다.

### B-0. 붙여 넣을 지시문

```
당신은 "캐치캐치" 프론트엔드를 이어서 개발합니다.

현재 상태:
- `/` 는 SignalCatcherApp 이고 화면 6개가 전부 Mock 으로 동작합니다.
- `/legacy` 는 동료의 기존 Working Demo 입니다. 삭제·수정하지 마세요.
  단 타입(customer-intelligence/contracts.ts)과 SSE 부품은 import 해서 재사용합니다.
- signal-catcher 에는 자동 테스트가 없습니다. 기존 vitest 95개와 e2e 는
  전부 /legacy 대상이므로 깨뜨리지 마세요.

읽을 문서:
  docs/frontend-v2/README.md                        현재 상태 요약
  docs/frontend-v2/02-architecture-and-contracts.md  타입 계약 (정본)
  docs/frontend-v2/03-screen-specs.md §<해당 화면>
  docs/frontend-v2/05-data-and-backend.md            데이터·연결·갭

작업 규칙:
- 화면 컴포넌트는 CatchSession/CatchReport 계약만 보고 그립니다.
  데이터 출처를 화면이 알게 만들지 마세요.
- 새 모달·드로어·툴팁은 반드시 Overlay 로 감쌉니다.
- 새 색을 만들지 마세요. catcher.module.css 의 토큰만 씁니다.
  (팔레트 5색 + 경고용 --amber 하나가 전부입니다)
- 설계 원칙(01 §5)과 충돌하는 변경을 하려면 화면이 아니라 문서를 먼저 고칩니다.

끝나면: `npm --prefix frontend run typecheck`,
        `npm --prefix frontend test -- --run`,
        `npm --prefix frontend run build` 를 통과시키고
        docs/frontend-v2 의 해당 문서를 같은 변경에서 갱신합니다.
```

### B-1. 백엔드 실연결 (가장 큰 남은 작업)

```
목표: state/use-catch-session.ts 의 setTimeout 체인을 실제 Run API 로 교체합니다.
화면 컴포넌트는 한 줄도 고치지 않는 것이 성공 기준입니다.

읽을 것: docs/frontend-v2/05-data-and-backend.md §4, §5, §6

순서:
 1) POST /api/runs + GET /api/runs/{id}/events(SSE) 로 catching 화면만 실데이터화.
    리포트는 당분간 Mock 을 유지합니다.
    - 재사용: customer-intelligence/parse-sse.ts, run-client.ts, run-reducer.ts
    - 이벤트 → StageKey 매핑은 05 §4.3 표를 그대로 따릅니다.
    - 진행 문장은 05 §4.4 의 선택지 A(서버 문장 그대로)로 시작합니다.
 2) result 화면의 report 를 CustomerSignalReport 에서 매핑 (05 §5 표)
 3) 근거 드로어 → GET /api/runs/{id}/evidence/{id}
 4) 여정 맵 → representative_journeys (비어 있으면 그 사실을 화면에 표시)
 5) 검증 기록 → findings + provenance
 6) 시연 스캐폴딩 제거 (03 §7 의 삭제 목록. useDemoOptions 부터 지우면
    나머지가 타입 에러로 드러납니다)
 7) ?view= 를 ?run={run_id} 로 승격

주의:
- 값이 없으면 지어내지 말고 "근거 부족"으로 표시하거나 블록을 감춥니다.
- 탈락 Claim 이 내려오지 않으면 스코어카드가 항상 100% 가 됩니다.
  그 경우 화면에 100% 를 그리지 말고 백엔드 이슈로 보고하세요.
- 액션 화면은 이 작업 범위가 아닙니다. Mock 을 유지합니다.
```

### B-2. 브리핑을 메인으로 승격

```
목표: 첫 화면을 브리핑으로 바꿉니다.

 1) use-catch-session.ts 의 DEFAULT_MAIN 을 "briefing" 으로 변경
 2) briefing-mock.ts 를 실제 시그널로 교체하거나, 목업임을 화면에 명시
 3) 상단 "지켜볼 것 요청하기"가 실제로 저장되게 (와쳐 API 필요 — 없으면
    localStorage 로 두고 "다음 브리핑부터 반영됩니다" 문구를 유지)
 4) 브리핑 → 시그널 확인하기 → catching 흐름에서 질문 문자열이
    "{시그널 이름} 시그널을 확인해줘" 로 만들어지는 현재 방식이
    실제 백엔드 질의로도 성립하는지 확인

판단 기준: 시그널이 목업 2건 고정인 채로 메인에 올리면 "매일 도는 서비스"라는
주장이 데모에서 무너집니다. 데이터 확보가 먼저입니다.
```

### B-3. 테스트 추가

```
목표: signal-catcher 에 최소 안전망을 만듭니다. (현재 테스트 0개)

우선순위 (vitest + Testing Library, jsdom):
 1) use-catch-session — start() 후 단계가 순서대로 done 이 되는지,
    clarify 분기에서 멈추고 answerClarification 으로 재개되는지,
    failed 분기에서 phase 가 catching 에 머무는지
 2) use-experiments — conflictOf 가 같은 segmentLabel 만 잡는지,
    localStorage 실패 시 조용히 빈 목록이 되는지
 3) ResultScreen — verdict rejected 인 finding 이 결과 화면에 나오지 않고,
    NaN 지표가 "근거 부족"으로 렌더되는지
 4) TraceScreen — rejected 주장과 사유가 렌더되는지
 5) use-swipe-deck — SLOP 이하 움직임이 클릭으로 남는지

타이머는 vi.useFakeTimers() 로 제어합니다.
기존 legacy 테스트를 건드리지 마세요.
```

### B-4. 액션 예측을 실물로

```
목표: action-mock.ts 의 예측·채점을 데이터로 만듭니다. (지금은 전부 손으로 쓴 값)

먼저 정할 것 (코드보다 결정이 먼저입니다):
 - 예측을 누가 만드나 — LLM 인가, 규칙 기반 계산인가
 - 예측에 붙는 evidenceIds 를 어디서 가져오나
 - risk(나빠질 것)를 무엇으로 계산하나. gain 만 있으면 이 화면의 의미가 사라집니다
 - 관찰 기간의 실측을 어디서 읽나 (백엔드에 와쳐/실험 개념이 아직 없습니다)

결정 전까지는 Mock 을 유지하고, 화면에 "데모 데이터"임을 명시한 현재 문구를
지우지 마세요.
```

---

## C. 작업 백로그

### C-1. 기획 확정 필요

- [ ] 첫 화면을 질문하기로 갈지 브리핑으로 갈지 (03 §1)
- [ ] 전환 마크 — 하트 vs 돋보기 (`?burst=lens` 로 비교 가능)
- [ ] 로딩 11.5초가 발표 호흡에 맞는지
- [ ] 시연 질문을 로밍 하나로 고정할지
- [ ] 액션 예측을 LLM 이 생성할지 규칙으로 계산할지 (B-4)
- [ ] 와쳐 요청이 실제로 무엇을 하는지 (지금은 배지 숫자만 증가)

### C-2. 구현 남은 것

- [ ] **백엔드 실연결** (B-1)
- [ ] signal-catcher 테스트 (B-3)
- [ ] 리포트 내려받기 버튼 (`download.json` / `download.md` 는 백엔드에 이미 있음)
- [ ] `?view=` → `?run={run_id}` 승격
- [ ] 시연 스캐폴딩 제거

### C-3. 백엔드에 요청할 것

[05 §6.4](05-data-and-backend.md) 목록 참고. 최우선 두 개:

- [ ] `representative_journeys` 가 비는 원인 (여정 맵이 통째로 빈다)
- [ ] 탈락한 Claim 도 내려오는지 (스코어카드가 항상 100% 가 되면 화면의 주장이 무너진다)

---

## D. 문서를 갱신하는 규칙

이 문서 묶음은 **코드와 같은 변경에서** 갱신합니다.

| 무엇을 바꿨나 | 갱신할 문서 |
| --- | --- |
| 타입·상태·라우트 | `02-architecture-and-contracts.md` |
| 화면 구조·문구·연출 | `03-screen-specs.md` |
| 색·서체·모션·새로 밟은 함정 | `04-design-system.md` |
| Mock 데이터·백엔드 계약·갭 | `05-data-and-backend.md` |
| 설계 원칙이 바뀌는 결정 | `01-product-and-ux-brief.md` (먼저 고치고 코드를 바꾼다) |
| 진행 상태 | `README.md` 의 기준 커밋과 요약, `06 §C` 백로그 |

구조가 크게 바뀌면 이 묶음을 고치지 말고 **`docs/frontend-v3/` 를 새로 만드세요.**
v1(`docs/화면 설계서.md`) → v2 가 그렇게 갈렸습니다. 버전 문서는 그 시점의 기록으로
남을 때 가치가 있습니다.
