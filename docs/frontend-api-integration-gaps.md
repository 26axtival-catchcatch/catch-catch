# Signal Catcher API 연동 범위와 계약 갭

갱신일: 2026-09-10

이 문서는 `docs/multi-agent-handoff.md`의 Backend 계약을 Signal Catcher 화면에 연결하면서
확인한 구현 범위와, 현재 공개 API만으로는 정확하게 표현할 수 없는 화면 데이터를 분리해 기록합니다.

## 이번에 연결한 실행 순서

1. 첫 화면 진입 시 `GET /api/sources`로 연결 상태와 현재 Source 목록을 미리 확인합니다.
2. 사용자가 분석을 시작할 때 Source 목록을 다시 조회합니다. 외부 등록 담당자가 Source를
   추가했다면 Backend 재시작 없이 이 시점에 반영됩니다.
3. 한국 시간 기준 고정 구간
   `2026-09-04T00:00:00+09:00` 이상,
   `2026-09-18T00:00:00+09:00` 미만과 현재 등록된 모든 Source로
   `POST /api/runs?mode=bedrock`을 호출합니다.
4. 202 응답의 Run ID로 상태를 조회하고 SSE를 즉시 구독합니다. 중앙 `RunClient`가
   `Last-Event-ID`를 유지하며 끊긴 스트림을 재연결합니다.
5. `goal_created`, `plan_created`, `step_*`, `fact_created`,
   `analysis_note_created`, `report_validating`, `result`, `done`을 화면의 다섯 진행 단계로
   투영합니다. SSE payload에 없는 수치나 역할 진행 상태는 만들지 않습니다.
6. 완료 뒤 `GET /api/runs/{run_id}`로 최종 상태와 보고서를 확인합니다.
7. `get_customer_journey` Fact에 공개된 대표 고객 ID가 있으면
   `GET /api/runs/{run_id}/customers/{customer_id}/journey`로 대표 여정을 조회합니다.
8. 사용자가 근거를 누를 때만
   `GET /api/runs/{run_id}/evidence/{evidence_id}`를 호출하고 결과를 Run 단위로 캐시합니다.

새 분석을 누르면 2번부터 다시 수행하므로 외부 데이터가 추가된 뒤 같은 질문을 다시 실행하는
흐름을 지원합니다. 브라우저에서 Source 파일을 업로드하거나 승인하는 기능은 포함하지 않습니다.

## 현재 공개 계약과 화면이 맞지 않는 부분

| 화면 요구 | 현재 계약 | 필요한 Backend 계약 또는 제품 결정 |
| --- | --- | --- |
| 오늘의 브리핑 카드 | 시그널별 `daily-results`, `comparison` API 제공. 통합 브리핑 API는 없음 | [시그널 인계](./signal-fe-handoff.md)의 일별 결과와 증감 지표를 조합하거나 통합 브리핑 계약 결정 |
| `지켜볼 것 요청하기` | 시그널 등록, 목록, 상태 변경과 일별 `schedule` API 제공 | [트리거 인계](./signal-trigger-fe-handoff.md)에 따라 화면에서 등록, 즉시 실행, 자동 측정 설정 연결 |
| Catching의 역할별 노드와 병렬 상태 | `agent_activity` SSE 제공. 현재 그래프는 단계와 로그 건수로 구성 | [액티비티 인계](./agent-activity-handoff.md)의 `node_id`, `parent_node_id`, `depends_on`으로 실제 역할 그래프 연결 필요 |
| 역할별 실제 소요 시간 | `agent_activity`의 `occurred_at`, `duration_ms` 제공 | 실제 역할 시간에는 액티비티 사용. `step_started/completed`는 공개 Fact 변환 단계 시간 |
| AI검색/행동로그/상담 노드별 처리 건수 | `step_started`에 Source별 처리량이 없고 Investigation Fact의 `processing`은 변환 통계 | 역할 또는 Source별 `scanned_events`, `matched_customers`를 의미와 함께 공개해야 함 |
| 미확정 후보의 주장별 계보 | 액티비티의 `candidates`, `decisions`에 후보 ID와 질의 참조, 사유 제공 | 최신 서버 판정을 후보 ID별로 갱신. 최종 확정 결과는 `result.report` 기준 |
| 대표 여정의 고객별 묶음 | 보고서는 여러 고객 이벤트를 평평한 배열로 제공하고 고객 ID는 별도 Fact에 있음 | `representative_customers[{customer_id, events}]` 또는 보고서의 고객별 journey ref 필요 |
| 새로고침 뒤 대표 고객 상세 복원 | Run 상태 응답에는 Facts가 없고 Artifact API에만 있음 | 상태 응답에 대표 고객 ref를 추가하거나 화면이 Artifact 조회를 표준 복원 경로로 사용하도록 결정 필요 |
| Evidence 원본 필드 | Investigation 공개 Evidence는 마스킹 ID, 요약 중심이며 원본 필드가 비어 있을 수 있음 | 공개 가능한 `raw_fields` 허용 목록을 Source별로 정의하거나 UI에서 원본 필드 표를 제거해야 함 |
| 개선안 실행 화면 | Backend action ID는 `improve_pattern_*`처럼 동적이고 기존 UI Mock action ID와 다름 | 추천 액션 유형/실행 payload 계약과 실제 적용 API가 필요. 현재 라이브 추천은 읽기 전용으로 표시 |
| 외부 데이터 추가 | HTTP 업로드 엔드포인트가 없고 승인 파일을 서버 디렉터리에 준비해야 함 | 현 운영 방식을 유지할지, 승인, 업로드, 검증 API를 만들지 결정 필요 |

## 의도적으로 하지 않은 표시

- `ranked_customers`가 비어 있으므로 위험도, 위험 점수, 고객 순위를 계산하거나 표시하지 않습니다.
- 미확정 후보 수를 확정 고객 수에 더하지 않습니다.
- 대표 여정의 순서를 서로 다른 Source의 분 단위 실제 행동 순서라고 단정하지 않습니다.
- 전체 확정 수 증가를 확장 Run의 성공 조건으로 표시하지 않습니다.
- Catching 역할 그래프의 고정 Mock 건수를 라이브 실행 수치로 표시하지 않습니다.
