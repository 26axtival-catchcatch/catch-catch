# 05. 데이터와 백엔드 연결

지금 화면을 채우는 Mock 데이터의 계약, 그리고 백엔드를 실제로 붙일 때의 매핑과
확인된 갭을 담습니다.

---

## 1. 데이터 출처 (현재)

| 파일 | 내용 |
| --- | --- |
| `state/mock.ts` | 로밍 시나리오 전부 — 질문·소스·단계·진행 문장·여정 14건·근거 14건·리포트 |
| `state/action-mock.ts` | 액션 시나리오 — AS-IS/TO-BE·예측 6개·타임랩스 8프레임·채점 |
| `briefing/briefing-mock.ts` | 브리핑 시그널 2건 |

전부 정적 상수입니다. 네트워크 호출은 **한 건도 없습니다.**

---

## 2. 시연 시나리오 (고정)

대표 질문 하나에 집중합니다.

```
"최근 로밍을 알아보는 고객들이 가장 많이 궁금해하는 게 뭐야?"
```

| 항목 | 값 |
| --- | --- |
| 결과 | 단기 일본 여행 로밍을 고르지 못한 고객 **328명** |
| 지표 | 시그널 고객 328명 · 평균 반복 검색 3.4회 · 상세 조회 후 미가입 71% · 재검색까지 4.2일 |
| 여정 | 대표 고객 `C-04**` 의 6일치 14개 이벤트 (8/12 09:10 → 8/18 14:41) |
| 주장 | 14개 중 12개 통과, 2개 탈락 |
| 근거 커버리지 | 100% · 분석 스텝 6 · 소스 5 · 계획 수정 1회 · 18.4초 |
| 기간 | 2026.08.05 – 2026.08.19 · `synthetic-20260819` |

**평균값으로 뭉개지 않고 가장 복잡했던 고객 한 명을 통째로 싣습니다.** 평균으로 뭉개면
"앱을 헤매다 → 검색에서 실패하고 → 결국 전화로 해결했다"는 실패의 형태가 사라집니다.

### 탈락한 주장 2건 (반드시 유지)

| 주장 | 사유 |
| --- | --- |
| 여행 목적지의 82%가 일본 | 검색어 텍스트에서 추정한 값이라 원본 필드로 검증할 수 없음 |
| 로밍 가입 전환율 전월 대비 12% 하락 | 비교 대상 전월 데이터가 분석 기간 밖 |

### 엣지케이스 데이터

| 상수 | 쓰임 |
| --- | --- |
| `CLARIFICATION` | 심문 모달 질문·힌트 |
| `DEGRADED_LIMITATIONS` | 부분 캐치 시 앞에 붙는 한계 2건 |
| `UNSUPPORTED_SUGGESTIONS` | 범위 밖 질문일 때 대안 질문 3개 |

`degradedReport()` 는 `research_gap_days` 의 값을 `NaN` 으로 만들어 **"근거 부족"
표시를 실제로 발생시킵니다.** 상담 소스가 빠지면 계산할 수 없는 지표이기 때문입니다.

---

## 3. 소스 다섯 개

Mock 의 `SOURCE_OPTIONS` 는 백엔드의 `source_id` 와 **이미 일치**합니다.

| `source_id` | Mock 라벨 | 백엔드 라벨 |
| --- | --- | --- |
| `search_history` | AI검색 이력 (필수) | Search history |
| `search_feedback` | 검색 피드백 | Search feedback |
| `digital_behavior` | GA 행동로그 | Digital behavior |
| `subscription` | 가입 정보 | Subscription |
| `voc` | 상담 이력 | Voice of customer |

라벨과 보유 기간은 프론트가 들고 있는 값입니다. 실연결 시 `GET /api/sources` 의
`PublicSourceManifest`(`label` · `description` · `data_interval` · `supported_topics`)로
갈아끼울 수 있습니다. 단 백엔드 라벨이 영문이므로 **한국어 매핑을 프론트에 남길지**를
정해야 합니다([§6](#6-확인된-갭)).

---

## 4. 백엔드 연결 (남은 마지막 작업)

### 4.1 바뀌는 곳은 한 파일

**`state/use-catch-session.ts` 하나입니다.** 화면 컴포넌트는 손대지 않습니다.

```
지금:  setTimeout 체인       ──▶ CatchSession
나중:  SSE 구독 + fetch      ──▶ CatchSession   ← 같은 모양을 채우기만
```

`state/types.ts` 가 백엔드 계약(`customer-intelligence/contracts.ts`)의 타입을 그대로
재사용하므로 변환 코드가 거의 필요 없습니다.

기존 `/legacy` 구현에 **재사용 가능한 부품**이 이미 있습니다.

| 파일 | 쓸 것 |
| --- | --- |
| `customer-intelligence/parse-sse.ts` | SSE 프레임 파서 |
| `customer-intelligence/run-client.ts` | Run 생성·조회·재접속 클라이언트 |
| `customer-intelligence/run-reducer.ts` | 이벤트 → 스냅샷 접기 |
| `customer-intelligence/run-contract-decoders.ts` | 계약 디코더 |

**복사해 쓰지 말고 import 해서 쓰세요.** `/legacy` 는 그대로 동작해야 합니다.

### 4.2 API 매핑

기본 주소는 `NEXT_PUBLIC_API_BASE_URL` (기본값 `http://127.0.0.1:8000`).

| API | 화면 |
| --- | --- |
| `POST /api/runs` | 질문 실행. 요청 4필드(`question` · `start_at` · `end_at` · `enabled_sources`)를 이미 수집 중 |
| `GET /api/runs/{id}/events` | SSE → 심박 스테퍼 + 진행 레일 |
| `POST /api/runs/{id}/clarification` | 심문 모달 답변 |
| `GET /api/runs/{id}` | 스냅샷 (재접속·복원) |
| `GET /api/sources` | 데이터셋 2depth 메뉴 |
| `GET /api/runs/{id}/evidence/{evidence_id}` | 근거 드로어 |
| `GET /api/runs/{id}/customers/{customer_id}/journey` | 고객 여정 맵 |
| `GET /api/run-artifacts/{id}` | 새로고침 복원 · 검증 기록 |
| `GET /api/run-artifacts/{id}/download.json\|.md` | 리포트 내려받기(미구현) |

`POST /api/runs` 요청 예:

```json
{
  "question": "최근 로밍을 알아보는 고객들이 가장 많이 궁금해하는 게 뭐야?",
  "start_at": "2026-08-05T00:00:00+09:00",
  "end_at": "2026-08-19T00:00:00+09:00",
  "enabled_sources": ["search_history", "search_feedback", "digital_behavior", "subscription", "voc"]
}
```

`end_at` 은 **미포함(exclusive)** 입니다. `?mode=fixture|gemini` 쿼리로 에이전트 모드를
강제할 수 있습니다. SSE 재접속은 `Last-Event-ID` 헤더를 씁니다.

### 4.3 이벤트 → 단계 매핑

| SSE `type` | 단계 / 처리 |
| --- | --- |
| `goal_created` | 목표 → `Stage.detail` 에 goal objective |
| `plan_created` · `plan_revised` | 계획. `plan_revised` 는 `planRevisions` 증가 |
| `step_started` | 분석 — `kind: "tool"`, `primitive` = `payload.primitive` |
| `fact_created` | 분석 — `kind: "fact"`, `short` = 대표 metric |
| `analysis_note_created` | 인사이트 — `kind: "think"` 또는 `fact` |
| `step_completed` | 분석 단계 진행 (`duration_ms`, `result_ids`) |
| `report_validating` | 검증 |
| `result` | 완료 → `HeartBurst` → `report` 구성 |
| `clarification_required` | `session.clarification` 세팅 |
| `unsupported_analysis` | `ask` 로 되돌리고 `suggestedQuestions` 채움 |
| `error` | `outcome: "failed"` + `failureReason` |

`no_data_scope` 코드는 `degraded` 로 처리하고 `limitations` 를 채웁니다.

### 4.4 진행 문장(`StageTick`)은 서버가 주지 않는다

지금 화면이 흘리는 한국어 문장은 **프론트가 쓴 것**입니다. 백엔드 이벤트에는
`goal.objective`, `step.selection_reason`, `note.claims[].statement` 같은 필드가 있으므로
셋 중 하나를 골라야 합니다.

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| A. 서버 문장 그대로 노출 | 정직함. 구현 최소 | 문장 톤이 화면과 다르고 영어가 섞임 |
| B. 프론트에서 템플릿 조립 | 톤 유지 | 문장이 데이터와 어긋날 위험 |
| C. 서버가 표시용 문장을 함께 내려줌 | 최선 | 백엔드 변경 필요 |

**권장은 A → C.** 데모 안정성이 우선이면 A 로 붙이고, 여유가 있으면 백엔드가
`activity.changed` payload 에 표시 문장을 담게 합니다.

### 4.5 붙이는 순서

1. `POST /api/runs` + SSE 구독으로 `catching` 화면만 실데이터화 (Mock 리포트는 유지)
2. `result` — `report` 를 `CustomerSignalReport` 에서 매핑
3. 근거 드로어를 `GET .../evidence/{id}` 로 교체
4. 여정 맵을 `representative_journeys` 또는 `GET .../journey` 로 교체
5. 검증 기록을 `findings` + `provenance` 로 교체
6. 시연 스캐폴딩 제거 ([03 §7](03-screen-specs.md))
7. `?view=` 를 `?run={run_id}` 로 승격

**액션 화면은 마지막입니다.** 예측·타임랩스·채점은 백엔드에 대응 개념이 아직 없습니다
([§6](#6-확인된-갭)).

---

## 5. 백엔드 리포트 → `CatchReport` 매핑

백엔드 `CustomerSignalReport` (`report_kind: "customer_signal"`) 기준입니다.

| `CatchReport` | 백엔드 출처 | 비고 |
| --- | --- | --- |
| `headline` | `report.headline` | 백엔드가 영어일 수 있음 |
| `headlineCount` | 대표 metric 값 | 프론트가 고를 규칙 필요 |
| `summary` | `report.executive_summary` | |
| `metrics` | `report.metrics` | 타입 동일 (`AnalysisMetricFact`) |
| `findings` | `report.findings` | `AnalysisFinding.claim`(=`VerifiedClaim`) → `chain` 조립 |
| `actions` | `report.recommendations` | `keywords` 는 프론트 소유 (Mock) |
| `limitations` | `report.limitations` | |
| `journey` / `lanes` | `report.representative_journeys` | `lane`·`column`·`intensity`·`tone`·`insight` 는 **프론트가 파생** |
| `planSteps` | `RunSnapshot.plan.steps` + `notes[].duration_ms` | `revisedFrom` 은 `plan_history` 비교 |
| `score` | `findings` 집계 + `notes` + `plan_history` | 아래 참고 |
| `runId` | `RunAccepted.run_id` | |
| `datasetVersion` · `adapterVersions` | `report.provenance` | 그대로 있음 |
| `periodLabel` · `analyzedAt` | `goal.time_range` + 완료 시각 | 포맷은 프론트 |

`TraceScore` 계산:

| 필드 | 계산 |
| --- | --- |
| `claimsTotal` / `claimsPassed` | **탈락 주장이 내려오는지 확인 필요** (§6) |
| `evidenceCoverage` | `evidence_ids` 를 가진 finding 비율 |
| `steps` | `plan.steps.length` |
| `sources` | `provenance.source_ids.length` |
| `planRevisions` | `plan.revision` 또는 `plan_history.length - 1` |
| `durationMs` | `notes[].duration_ms` 합 |

`JourneyNode` 파생 규칙(프론트가 정해야 함):

- `lane` = `source_id`
- `column` = 시간순 인덱스
- `intensity` = 정규화 규칙 필요 (지어내면 안 되므로 **없으면 곡선을 감추는 편이 낫다**)
- `tone` = `outcome` 매핑 (`negative`/`이탈`→`negative`, 반복→`repeat`, 완료→`resolved`)
- `insight` = 서버 문장이 없으면 **표시하지 않는다**

---

## 6. 확인된 갭

### 6.1 화면이 쓰는데 백엔드에 없는 것

| 항목 | 상태 |
| --- | --- |
| **액션 예측 / 타임랩스 / 채점** | 백엔드에 대응 개념 없음. 전부 Mock. 실물로 만들려면 예측 생성 주체(LLM/규칙)와 근거 연결을 먼저 정해야 함 |
| **와쳐 / 브리핑** | API 없음. 브리핑은 `briefing-mock.ts` 고정 2건 |
| `CatchAction.keywords` | 추천검색어 후보. 백엔드에 없음 |
| `JourneyNode.insight` · `intensity` · `tone` | 파생 규칙 미정 |
| 진행 문장(`StageTick.text`) | §4.4 참고 |

### 6.2 Mock 이 실제 백엔드와 어긋나는 것

| Mock | 실제 |
| --- | --- |
| primitive `build_segment` | `segment_customers` |
| primitive `profile_customers` | `profile_events` |
| primitive `validate_claims` | **없음.** Claim 검증은 서버 내부 단계이지 primitive 가 아님 |

**실연결 시 `STAGE_TICKS` 와 `tick-marks.ts` 의 primitive 이름을 실제 카탈로그로
맞춰야 합니다.** 백엔드 카탈로그 10개는 다음과 같습니다.

```
catalog_sources · profile_events · aggregate_events · segment_customers
detect_repetition · match_sequence · compare_segments · rank_customers
get_customer_journey · get_evidence
```

### 6.3 이전에 실제 Run 을 열어 확인한 데이터 갭 (2026-08-31 기준, 재확인 필요)

| 필드 | 당시 백엔드 | 영향 |
| --- | --- | --- |
| `metrics` | 4개 | 정상 |
| `findings` | 3개 | 정상 |
| `recommendations` | 1개 | 정상 |
| `representative_journeys` | **0개** | **여정 맵이 통째로 빈다 — 최우선** |
| `ranked_customers` | 0개 | 현재 화면은 쓰지 않음 |
| `signals` | 0개 | 현재 화면은 쓰지 않음 |

- 저장된 Run 6건 중 5건이 `generic_run_failed`
- `headline` 이 영어 (`"Negative Feedback Customer Count: 6 customers"`)
- 데이터 기간이 Mock 과 다름 (백엔드 2026-07-20~08-17 / Mock 2026-08-05~08-19)

### 6.4 백엔드에 물어야 할 것

- [ ] **`representative_journeys` 가 왜 비는지** (최우선 — 핵심 화면)
- [ ] **검증에 탈락한 Claim 도 내려오는지** — 통과한 것만 오면 스코어카드가 항상 100%
- [ ] `headline` 을 한국어 문장으로 만들 수 있는지
- [ ] Run 실패 5/6 의 원인
- [ ] `plan_history` 로 계획 수정 이력을 복원할 수 있는지
- [ ] 소스 `label` 을 한국어로 줄지, 프론트에서 매핑할지
- [ ] 대표 질문 하나의 fixture 응답 전체 JSON (프론트 매핑 테스트용)
- [ ] 검색 이벤트에 **실제 검색어 텍스트**가 있는지 — 없으면 추천검색어 액션의 근거를 만들 수 없음

---

## 7. Mock 을 고칠 때 지킬 것

1. **탈락 주장 2건과 빗나간 예측 2건을 지우지 않는다.** 이 서비스의 주장 자체입니다.
2. **`degradedReport()` 의 `NaN` 지표를 지우지 않는다.** "근거 부족" 표시를 실제로
   보여 주는 유일한 경로입니다.
3. 여정 이벤트는 **레인을 넘나들어야** 합니다. 한 레인에 몰리면 cross-channel 주장이
   시각적으로 증명되지 않습니다.
4. 근거(`EVIDENCE`)는 여정 노드의 `evidence_id` 와 **1:1로 존재해야** 합니다. 없으면
   드로어가 "불러올 수 없어요"를 띄웁니다.
5. `STAGE_TICKS` 의 `ms` 합을 바꿀 때는 검증 마지막 문장이 1.5초 아래로 내려가지
   않게 합니다.
