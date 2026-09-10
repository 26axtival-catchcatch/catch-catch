# 시그널 등록·측정 FE 인계

## 연결 흐름

기존 중앙 어댑터의 Run 요청, SSE 이벤트, 상태 및 Artifact 응답은 그대로 사용합니다.
이번에 추가된 API만 호출하면 됩니다. FE 화면과 정기 실행은 이번 Backend 구현 범위에 포함하지 않습니다.

1. 기존 방식으로 분석하고 `status=completed`를 확인합니다.
2. `GET /api/runs/{run_id}/signal-proposals`의 `items`를 조회합니다.
3. 후보의 `title`, `description`, `limitations`, `definition`, `measurement.values`를 보여줍니다.
4. 사용자가 선택한 후보마다 `POST /api/signals`를 호출합니다.
5. `GET /api/signals`로 등록 목록을, 상세와 측정 이력 API로 추적 정보를 조회합니다.

```json
{"proposal_id": "후보 조회에서 받은 ID"}
```

등록 응답의 `signal_id`를 이후 모든 추적 조회에 사용합니다. 같은 후보를 반복 등록하면 같은 ID입니다.
정확히 같은 정의를 다른 분석에서 다시 선택해도 기존 시그널을 재사용하고 새 기간의 최초 측정값을 보존합니다.
이름만 비슷한 후보는 자동으로 합치지 않습니다. 등록 시 정의 버전은 1이며, 뒤의 분석이 덮어쓰지 않습니다.

## 지표와 측정값

`definition.source_ids`는 추적에 필요한 고정 Source 집합입니다. `cohort_sql`은 대상 고객을,
선택적 `denominator_sql`은 전체 시도 고객을 반환합니다. 대상 고객이 분모 집합에 포함되는지 서버가 검증합니다.
관측 기간은 SQL 문자열에 넣지 않고 API 입력으로 지정합니다. 서버가 해당 기간·Source로 제한된 공간에서 실행합니다.

| 지표 키 | 의미 | 단위 |
| --- | --- | --- |
| `affected_customer_count` | 중복 제거 대상 고객 수 | customers |
| `denominator_customer_count` | 근거를 갖춰 정의한 모집단 고객 수 | customers |
| `affected_customer_rate` | 대상 고객 수 ÷ 모집단 고객 수 × 100 | percent |
| 에이전트가 정의한 추가 키 | 정의에 기록된 SQL의 실제 단일 수치 | 지표별 unit |

비율이 이미 백분율이므로 FE에서 다시 100을 곱하지 않습니다. 비율에는 `numerator`, `denominator`도 포함됩니다.
분모를 정할 근거가 없으면 대상 수만 제안할 수 있습니다. 모델이 입력한 임의 숫자를 확정값으로 저장하는 도구는 없습니다.
`queries`는 재현 SQL과 제한된 근거 미리보기이며 전체 고객 집합과 질의 결과는 Backend DB 내부에 보존합니다.
`measurement.trace_id`는 최초 조사 또는 수동 재측정의 Langfuse trace ID입니다.
등록된 패턴은 관찰된 행동 정의이며, 개선안의 효과나 UI 결함의 인과관계를 입증했다는 뜻은 아닙니다.

## 재측정과 이력

`POST /api/signals/{signal_id}/measurements`:

```json
{
  "start_at": "2026-09-04T00:00:00+09:00",
  "end_at": "2026-09-11T00:00:00+09:00"
}
```

기간은 시작 포함/종료 제외이며 시간대가 필요합니다. 수동 재측정은 LLM 재조사 없이 등록 SQL을 실행합니다.
재측정은 현재 제공된 데이터에서 등록 당시 Source만 선택합니다. 무관한 테이블을 추가해도 분모가 자동으로 넓어지지 않습니다.
필요한 Source가 없거나 조회가 실패하면 `status=unavailable`, 수치는 null이며 사유를 표시합니다.
분모 0도 비율 0%가 아닙니다. 해커톤 데이터의 특정 주간 밖에 기록이 없다면 실제 개선 추세로 설명하지 마세요.

`GET /api/signals/{signal_id}/measurements`:

- `items`: 실패와 데이터 보정 이전 값을 포함한 전체 측정 이력
- `latest_by_window`: 각 기간의 최신 성공 측정, 성공 이력이 없으면 마지막 실패 측정
- `comparable`, `comparison_limitations`: 현재 기간들을 같은 추이로 해석할 수 있는지와 제한 사유

같은 입력과 같은 데이터는 기존 측정 ID를 반환합니다. 데이터가 보정되면 새 ID를 추가합니다.
실패 뒤 성공한 재시도는 실패에 막히지 않습니다. 데이터가 변한 동일 기간은 새 기간의 변화와 구분해서 표시합니다.

## 상태와 보존

`PATCH /api/signals/{signal_id}`에 `{"status":"paused"}`와 같이 요청합니다.
`active`, `paused`, `archived`를 지원하고 이력을 삭제하지 않습니다. 수동 재측정은 모든 상태에서 가능합니다.
후속 스케줄러는 active만 대상으로 삼을 예정입니다. 현재 정기 실행과 알림은 연결하지 않았습니다.

DB는 기본 `data/run-artifacts/signals.sqlite3`이며 서버 재시작 후에도 등록 ID·정의·측정 이력을 읽습니다.
기존 완료 Run에는 새 후보를 소급 생성하지 않습니다. 새 코드로 수행한 실제 조사에서 지표 제안·검증을 통과해야 후보가 생깁니다.
Fixture 모드는 기존 보고서 동작을 유지하며 자동 시그널 제안은 실제 Bedrock/Gemini 조사 모드에서 수행합니다.

## 후속 로드맵

등록·측정 경로를 정기 실행에 연결하고 정기 리포트를 작성한 다음, 이력 API를 이용해 변화 추이 화면을 구현합니다.
시그널 정의 편집과 버전 교체, 유사 시그널 병합, 지표별 알림 기준은 별도 설계 대상입니다.
