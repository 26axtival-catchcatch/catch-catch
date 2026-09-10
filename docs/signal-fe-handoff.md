# 시그널 등록·측정 FE 인계

## 연결 흐름

기존 중앙 어댑터의 Run 요청, SSE 이벤트, 상태 및 Artifact 응답은 그대로 사용합니다.
이번에 추가된 API만 호출하면 됩니다. FE 화면과 정기 실행은 이번 Backend 구현 범위에 포함하지 않습니다.

1. 기존 방식으로 분석하고 `status=completed`를 확인합니다.
2. `GET /api/signal-proposals?run_id={run_id}`의 `items`를 조회합니다. 기존 `GET /api/runs/{run_id}/signal-proposals`도 지원합니다.
3. 후보의 `title`, `description`, `limitations`, `definition`, `measurement.values`를 보여줍니다.
4. 사용자가 선택한 후보마다 `POST /api/signals`를 호출합니다.
5. `GET /api/signals`로 등록 목록을, 상세와 측정 이력 API로 추적 정보를 조회합니다.

```json
{"proposal_id": "후보 조회에서 받은 ID"}
```

한 조사 태스크에서 발견한 서로 다른 패턴을 여러 후보로 제안할 수 있습니다. 각 후보는 고유 `proposal_id`,
`candidate_id`, 자체 `definition`과 측정값을 갖습니다. `task_id`는 발견한 조사 태스크를 나타내는 출처이며
등록 단위가 아닙니다. 이전에 저장된 후보의 `task_id`는 null일 수 있습니다. 사용자가 선택한 후보마다 등록합니다.
후보를 제안하거나 독립 검증하는 것만으로 추적 시그널이 자동 등록되지는 않습니다.

분석 ID 없이 `GET /api/signal-proposals`로 완료된 분석의 후보를 모아 조회하고,
`GET /api/signal-proposals/{proposal_id}`로 하나를 가져올 수 있습니다.

등록 응답의 `signal_id`를 이후 모든 추적 조회에 사용합니다. 같은 후보를 반복 등록하면 같은 ID입니다.
정확히 같은 정의를 다른 분석에서 다시 선택해도 기존 시그널을 재사용하고 새 기간의 최초 측정값을 보존합니다.
이름만 비슷한 후보는 자동으로 합치지 않습니다. 등록 시 정의 버전은 1이며, 뒤의 분석이 덮어쓰지 않습니다.

## 정의를 직접 등록

분석 Run이나 후보 ID 없이도 `POST /api/signals`에 이름·정의·최초 측정 기간을 전달할 수 있습니다.
예를 들어 다음 요청은 반복 검색이라는 관측 패턴을 등록합니다. 이것만으로 고객이 헤맸다는 판정은 아닙니다.

```json
{
  "title": "부가서비스 반복 검색",
  "description": "부가서비스를 찾으며 반복 검색한 고객 비율",
  "start_at": "2026-09-04T00:00:00+09:00",
  "end_at": "2026-09-11T00:00:00+09:00",
  "definition": {
    "source_ids": ["hackathon_search_history"],
    "cohort_sql": "SELECT DISTINCT customer_id FROM hackathon_search_history WHERE topic = '부가서비스 조회/해지' AND dim_query_type = 'repeat'",
    "denominator_sql": "SELECT DISTINCT customer_id FROM hackathon_search_history WHERE topic = '부가서비스 조회/해지'",
    "population_description": "부가서비스 조회/해지 검색 고객",
    "normal_comparison": "반복하지 않은 검색 고객과 비교. 정상 탐색 여부를 별도로 판정하지 않음",
    "metrics": []
  }
}
```

서버가 해당 Source와 기간에서 SQL을 실행한 후 성공한 측정만 등록합니다. 클라이언트가 계산한 숫자는 받지 않습니다.
측정할 수 없는 정의는 HTTP 422이며 시그널을 생성하지 않습니다. 직접 등록은 사용자 요청에 의한 등록이며
독립 조사 에이전트의 의미 검증을 거쳤다는 뜻은 아닙니다. `origin=user_defined`, `proposal_id=null`로 구분합니다.
동일 정의가 이미 등록되어 있으면 기존 시그널과 출처를 유지하고 해당 기간 측정을 연결합니다.

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

## Langfuse에서 시그널 찾기

관측 이름은 `customer_signal.signal`, 유형은 `SPAN`입니다. 도구 이름을 일일이 찾아 열 필요 없이
Observations에서 해당 이름으로 필터링합니다. metadata의 `entity_type=signal`도 같은 용도로 사용할 수 있습니다.
관측/metadata 필터 기능은 [Langfuse 공식 안내](https://langfuse.com/docs/observability/features/metadata)를 참고합니다.
설치 버전에 따라 메뉴 이름은 다를 수 있으며, Trace 상세에서도 같은 이름의 span을 찾을 수 있습니다.

- `operation`: 후보 확정, 등록 또는 재측정 작업 구분
- `proposal_id`, `candidate_id`, `task_id`: 등록 전 발견 패턴과 조사 출처
- `signal_id`: 등록 이후 개별 시그널의 등록·재측정 연결
- `measurement_id`: 저장된 수치와 측정 이력 연결

span의 Input에서 정의·기간을, Output에서 식별자·측정 수치를 확인합니다.
기존 분석 trace에는 새 span을 소급 추가하지 않습니다. 적용 후 후보 확정·등록·재측정부터 생성됩니다.
이 span은 실행 관측이며 시계열 데이터의 원장은 시그널 DB와 측정 이력 API입니다.

## 후속 로드맵

등록·측정 경로를 정기 실행에 연결하고 정기 리포트를 작성한 다음, 이력 API를 이용해 변화 추이 화면을 구현합니다.
시그널 정의 편집과 버전 교체, 유사 시그널 병합, 지표별 알림 기준은 별도 설계 대상입니다.

등록·재측정의 성공 응답 헤더 `X-Langfuse-Trace-Id`는 **이번 API 호출**의 trace ID입니다.
CORS에서도 이 헤더를 읽을 수 있습니다. 중복 요청이 기존 측정을 재사용하면
본문의 `measurement.trace_id`는 최초 저장 당시 trace를 유지하므로 두 ID는 다를 수 있습니다.
Langfuse MCP로는 `fetch_observations(type="SPAN", name="customer_signal.signal", age=180)`으로
시그널 기록만 조회합니다. 특정 호출은 `trace_id`를 추가하고, 반환 metadata의 `signal_id`로 이력을 연결합니다.
현재 `langfuse_local` MCP의 기본 키는 Backend와 다른 프로젝트를 가리킵니다.
아래 명령은 MCP 설정 파일을 바꾸지 않고, 선택한 Backend 환경의 프로젝트 키를 해당 MCP 프로세스에 전달합니다.
키 원문은 출력하거나 문서에 기록하지 않습니다.

```sh
env -u LANGFUSE_SECRET_KEY -u LANGFUSE_PUBLIC_KEY -u LANGFUSE_BASE_URL \
  uv run --env-file .env --project backend python scripts/verify-signal-spans-mcp.py \
  --backend-credentials --trace-id <ID>
```
