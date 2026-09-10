# 04. 디자인 시스템

토큰은 전부 `catcher.module.css` 의 `.app` 스코프에 있습니다. 컴포넌트 CSS 는 각
디렉터리의 `*.module.css` 에서 토큰만 참조합니다.

---

## 1. 색 — LG유플러스 2025 리브랜딩

공식 5색 밖의 색은 만들지 않습니다. 파생값도 `color-mix` 로만 뽑습니다.

| 토큰 | 값 | 역할 |
| --- | --- | --- |
| `--magenta` | `#ff2e98` | 강조 · 시그널 · 심박 · 검증 통과 |
| `--u-black` | `#22171c` | 페이지 바탕 |
| `--u-gray` | `#82817e` | 흐린 글자 |
| `--u-light` | `#f4f4ee` | 본문 글자 |
| `--u-white` | `#ffffff` | 마젠타 버튼 위 글자 |

**밝은 바탕을 쓰지 않습니다.** Light Gray 를 바탕에 깔면 마젠타가 막대·칩 정도로만
나타나 브랜드가 화면을 끌고 가지 못합니다. U+ Black 바탕 + Light Gray 글자면 여전히
공식 5색인데 마젠타가 발광합니다. 본문 대비 13:1, 흐린 글자 4.6:1.

### 파생 토큰

```css
--ground:     var(--u-black);                                    /* 페이지 바탕 */
--raise/card: color-mix(in srgb, var(--u-black) 94%, var(--u-white));
--card-2:     color-mix(in srgb, var(--u-black) 88%, var(--u-white));
--line:       color-mix(in srgb, var(--u-black) 79%, var(--u-white));
--line-soft:  color-mix(in srgb, var(--u-black) 87%, var(--u-white));
--chalk:      var(--u-light);                                    /* 본문 */
--fog:        color-mix(in srgb, var(--u-gray) 52%, var(--u-light));
--fog-dim:    var(--u-gray);
--signal:     var(--magenta);
--signal-soft/-wash/-glow                                        /* 강조 파생 */
--jade:       var(--magenta);   /* 검증 통과도 마젠타 계열 */
```

배경은 마젠타 radial-gradient 두 겹 + `--ground` 입니다.

### 예외 하나 — 경고

```css
--amber: #ffa62e;
--amber-wash: rgb(255 166 46 / 13%);
```

브랜드 팔레트는 아이덴티티 색이지 시스템 상태색까지 규정하지 않고, 오류를 브랜드색으로
칠하면 브랜드가 오염됩니다.

| 상태 | 색 |
| --- | --- |
| 검증 통과 | 마젠타 |
| 경고 · 부분 캐치 · 실패 · 빗나간 예측 · 위험 예측 | 앰버 |
| 근거 부족 · 제외 | 색 없이 **점선 테두리** |

### 화면당 마젠타는 하나의 역할만

**모두가 강조면 아무것도 강조가 아닙니다.**

| 화면 | 마젠타가 뜻하는 것 |
| --- | --- |
| 브리핑 | 시그널의 핵심 수치(`*…*` 강조) |
| 질문하기 | 실행(캐치 버튼)과 흐르는 시그널 |
| 캐치하는 중 | 진행된 구간 |
| 캐치 결과 | 찾은 수 |
| 검증 기록 | 통과한 주장 |
| 액션 | **바뀌는 것**(TO-BE 에 새로 생기는 항목)과 주 실행 버튼 |

색 단계는 셋을 넘기지 않습니다 — **무채색이 기본, 마젠타는 그 화면의 강조 하나,
앰버는 위험과 빗나감.**

### 카드는 면이 필요한 것에만

| 쓸 것 | 쓰지 말 것 |
| --- | --- |
| 시안·목업처럼 **면 자체가 의미**인 것 | 수치 비교 — **표**가 본업 |
| 근거 드로어처럼 겹쳐 뜨는 것 | 문단 — 그냥 문단으로 |
| 여정 보드처럼 프레이밍이 필요한 것 | 목록 — 구분선으로 충분 |

액션 화면은 이 원칙으로 카드 18개를 시안 2장 + 표 1개로 줄였습니다.

---

## 2. 타이포그래피

```css
--font-body:    "IBM Plex Sans KR", -apple-system, …;
--font-display: "Gasoek One", var(--font-body);
--font-mono:    "IBM Plex Mono", ui-monospace, …;
```

로드는 `SignalCatcherApp` 의 `FONT_HREF` 한 곳에서 합니다
(`Gasoek+One` · `IBM+Plex+Mono:400,500` · `IBM+Plex+Sans+KR:400,500,600,700`).

| 역할 | 서체 | 굵기 |
| --- | --- | --- |
| Display | Gasoek One | **400 고정** |
| Body | IBM Plex Sans KR | 400 · 500 · 600 |
| Data (ID·primitive·수치) | IBM Plex Mono | 400 · 500 |

- Display 는 워드마크, 화면 제목, 결과 헤드라인, 검증 기록 제목, "찾았다!" 에만.
- **Gasoek One 에 700 을 지정하면 가짜 굵기로 뭉개집니다. 반드시 400.**
- 본문 기본 400. 300 은 어두운 배경에서 획이 날아갑니다.
- `word-break: keep-all` 로 한국어 단어가 쪼개지지 않게 합니다.

---

## 3. 모션

| 대상 | 규칙 |
| --- | --- |
| 이징 | `--ease: cubic-bezier(0.32, 0.72, 0, 1)` 통일 |
| 심박 그리기 | `stroke-dashoffset`, 단계 소요시간과 동기 (`--dur`) |
| 여정 연결선 | 같은 `stroke-dashoffset` 언어 |
| 액션 스파크라인 | 같은 언어 — 선이 왼쪽에서 오른쪽으로 그려진다 |
| 화면 전환 | `.enter` 520ms |
| 완료 연출 | 하트 바운스 → 마젠타 플래시 → "찾았다!" (`BURST_MS = 1000`) |
| 타이핑 | placeholder `TYPE_MS 55` / `ERASE_MS 24` / `HOLD_MS 1900`, 심문 모달 `TYPE_MS 32` |
| 액션 매직 | `sweep` 900ms → 새 항목 `draw` 220ms 간격 (`INTRO_MS 1900`) |
| 타임랩스 | `FRAME_MS 420` |
| 스와이프 | `FLING_MS 170` |

`prefers-reduced-motion: reduce` 를 모든 애니메이션에서 처리합니다.
질문 전송의 흡입 연출도 이 값을 확인하고 즉시 전환합니다.

---

## 4. 서비스 마크

`brand/Brand.tsx` 의 `SignalMark` — 돋보기 + 파형 + 스파크 조합입니다.
**돋보기 = 찾는다, 파형 = 시그널.**

- 노출은 **상단 좌측 서비스명 자리 한 곳**과 브리핑 대화 아바타(12px)뿐입니다.
- 렌즈·손잡이는 놓인 자리의 글자색을 따르고 **스파크만 마젠타**로 빠집니다.
- 캐치 버튼은 평범한 돋보기, 로딩 질의 바와 결과 헤드라인은 아이콘 없이 텍스트만.

로고를 반복하면 브랜드가 강해지는 게 아니라 닳습니다.

| 컴포넌트 | 용도 |
| --- | --- |
| `SignalMark` | 서비스 마크 |
| `Sparkle` | **AI 산출물과 AI 실행 버튼에만.** 다른 곳에 쓰면 의미가 흐려진다 |
| `SignalProgress` | 단계 = 박동 하나인 심박 스테퍼 |
| `HeartBurst` | 완료 연출 (`mark="lens"` 로 돋보기 대안 비교 가능) |

---

## 5. 접근성

| 항목 | 규칙 |
| --- | --- |
| 포커스 | `.app :focus-visible` — 마젠타 2px outline, offset 3px |
| 모달 | `role="dialog"` + `aria-modal` + focus trap (심문 모달) |
| 진행 레일 | `aria-live="polite"` |
| 여정 캡션 | `aria-live="polite"` |
| 노드 버튼 | `aria-label` 에 레인·행동·본문·"원본 근거 열기"까지 |
| 장식 SVG | 전부 `aria-hidden` |
| 덱 | `role="group"` + 좌우 화살표 키 |
| placeholder | 오버레이라 `aria-hidden`. 입력에는 `<label class="srOnly">` |

---

## 6. 알려진 함정

### 6.1 legacy `globals.css` 가 전역에 로드된다

`layout.tsx` 가 앱 전체에 불러오므로 **밝은 테마 기준 전역 규칙이 새 화면으로 샙니다.**
실제로 겪은 사례:

- `table { min-width: 880px }` → 415px 드로어 안의 표가 밖으로 밀려남
- `th { background: #f2f6f5 }` → 다크 화면에 밝은 띠
- `th { text-transform: uppercase }` → `query` 가 `QUERY` 로
- `tbody tr:hover` 배경

`catcher.module.css` 가 `.app table` · `.app th` · `.app tbody tr:hover` 로 무효화해
두었습니다. **새 화면에 표나 폼을 추가할 때 같은 함정을 확인하세요.**

### 6.2 전역 `:focus-visible` 과 명시도 동점

`.app :focus-visible` 이 `(0,2,0)` 입니다. 입력 자체의 링을 지우고 감싼 튜브만 빛나게
하려면 **`(0,2,0)` 을 넘겨야** 합니다.

```css
/* ✗ 동점이라 순서에 밀림 */
.modalInput:focus-visible { outline: none; }
/* ✓ */
.modalForm .modalInput:focus-visible { outline: none; }
```

### 6.3 같은 규칙에 `color` 를 두 번 쓰지 않기

`.brand` 에 `color` 가 두 번 들어가 뒤의 값이 이겨 로고가 의도와 다른 색으로 렌더된
적이 있습니다. 토큰을 바꿀 때 죽은 선언이 남지 않았는지 확인하세요.

### 6.4 SVG 는 replaced element

`left` + `right` 를 함께 줘도 늘어나지 않고 **내재 비율 폭**을 씁니다.
여정 연결선 오버레이가 이 때문에 좁게 그려졌습니다.
`width: calc(100% - var(--label))` 처럼 명시 폭을 주세요.

### 6.5 `forEach` 안의 `return` 은 루프를 멈추지 않는다

`playFrom()` 에서 이 실수로 엣지케이스 분기 후에도 나머지 단계가 계속 예약됐습니다.
단계 루프를 고칠 때는 `for...of` + `break` 를 유지하세요.

### 6.6 화면 전환 시 스크롤

한 페이지에서 `phase` 만 갈아끼우기 때문에 **그대로 두면 아래쪽에서 누른 버튼의 스크롤
위치를 다음 화면이 물려받습니다.** `phase` 가 바뀌면 즉시 맨 위로 되돌립니다
(`behavior: "instant"`). 액션 화면 안에서 단계가 바뀔 때도 같습니다.
`scrollIntoView` 는 재렌더와 겹치면 화면 끝으로 튀므로 주의하세요.

### 6.7 `localStorage` 는 마운트 뒤에 읽는다

SSR/정적 export 와 첫 렌더를 맞추기 위해 `useExperiments` 는 `useEffect` 안에서 읽습니다.
렌더 중에 읽으면 hydration 불일치가 납니다.
