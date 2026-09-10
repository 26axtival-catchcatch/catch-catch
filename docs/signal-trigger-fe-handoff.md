# 시그널 실행 트리거 FE 인계

작성일: 2026-09-10
대상: 등록된 시그널의 실행 버튼, 자동 측정 설정, 누적 이력과 비교 화면을 연결하는 FE 개발자

FE에서 실행을 요청할 API는 준비되어 있습니다. **“지금 분석”은 `POST /measurements`,
“매일 자동 분석”과 “과거 일별 결과 보충”은 `PUT /schedule`로 연결합니다.**
이 문서는 연결 계약이며 FE 구현 파일은 변경하지 않았습니다.

등록과 지표 정의는 [기존 시그널 인계](signal-fe-handoff.md), 전체 계약은
[API 엔드포인트](api-endpoints.md), 실행 증거는 [라이브 검증 기록](verification/live-signal-daily.md)에 있습니다.

## 접속과 FE 작업 위치

- API 기본 주소: `http://127.0.0.1:8000`
- FE 환경 설정: `NEXT_PUBLIC_API_BASE_URL`
- [시그널 Swagger](http://127.0.0.1:8000/docs#/signals)
- [OpenAPI 스키마](http://127.0.0.1:8000/openapi.json)
- 기존 통신 구현 참고: `frontend/src/features/customer-intelligence/run-client.ts`
- 신규 통신 모듈 제안: 같은 디렉터리의 `signal-client.ts`

기존 FE `contracts.ts`의 `Signal`은 보고서 내부 타입입니다. 영속 등록 객체는
`RegistrySignal`처럼 별도 이름으로 정의하고 `signal_id`를 키로 사용해야 합니다.
OpenAPI의 `Signal`, `Measurement`, `DailySchedule`, `DailyResults`, `MeasurementComparison`을
확인하고 기존 디코더 방식에 맞춰 응답을 검증합니다.

브라우저의 Origin과 Backend `FRONTEND_ORIGIN`은 일치해야 합니다.
`http://127.0.0.1:3000`의 POST preflight를 확인했습니다.
`localhost`와 `127.0.0.1`, 서로 다른 포트는 다른 Origin입니다.
FE에는 Gemini, Bedrock, LangSmith, Langfuse 키가 필요하지 않습니다.

## 버튼과 API 매핑

아래 표에서 `{id}`는 등록 응답의 `signal_id`입니다. 후보의 `proposal_id`나 분석 `run_id`를 넣지 않습니다.

| FE 동작 | HTTP 요청 | 요청 내용 | 완료 후 조회 |
| --- | --- | --- | --- |
| 후보 등록 | `POST /api/signals` | `{"proposal_id":"후보 ID"}` | 시그널 목록, 상세, 일정 |
| 지금 분석, 선택 기간 재측정 | `POST /api/signals/{id}/measurements` | `start_at`, `end_at` | 전체 이력, 일별 결과, 비교 |
| 매일 자동 분석 켜기 | `PUT /api/signals/{id}/schedule` | `{"enabled":true}` | 일정, 상세, 일별 결과 |
| 매일 자동 분석 끄기 | `PUT /api/signals/{id}/schedule` | `{"enabled":false}` | 일정 |
| 과거 일별 결과 보충 | `PUT /api/signals/{id}/schedule` | `enabled=true`, 과거 `next_run_at` | 일정, 일별 결과, 비교를 주기적으로 조회 |
| 시그널 추적 재개 | `PATCH /api/signals/{id}` | `{"status":"active"}` | 상세, 일정 |
| 시그널 추적 중지 | `PATCH /api/signals/{id}` | `{"status":"paused"}` | 상세, 일정 |

신규 등록 시 기본 일정을 함께 저장합니다. 같은 정의를 재등록하면 기존 시그널과 일정을 유지하므로
등록 이후 `GET /schedule`로 실제 설정을 확인합니다.

자동 실행 조건은 **일정의 `enabled=true`와 시그널의 `status=active`가 모두 충족되는 경우**입니다.
중지된 시그널에서 자동 분석을 켜려면 사용자 의도에 따라 `PATCH`로 추적을 재개한 뒤 `PUT`으로
일정을 활성화합니다. 두 요청은 하나의 트랜잭션이 아니므로 실패하면 상세와 일정을 다시 조회합니다.
수동 재측정은 `paused`, `archived` 상태에서도 가능합니다.

## 지금 분석 버튼

시그널 정의와 Source는 서버에 저장된 값을 사용합니다. FE에서는 측정할 기간만 전달합니다.
직전 하루 분석 버튼은 한국시간으로 완료된 하루를 선택하고 날짜를 명시해야 합니다.

```http
POST /api/signals/{id}/measurements
Content-Type: application/json

{
  "start_at": "2026-09-08T00:00:00+09:00",
  "end_at": "2026-09-09T00:00:00+09:00"
}
```

1. 같은 시그널의 실행 버튼을 비활성화하고 측정 중 상태를 표시합니다.
2. 요청 응답을 기다립니다. 정상 HTTP 상태는 `200`이며 본문은 `Measurement`입니다.
3. `status=success`이면 `values`를 표시하고 이력과 비교 조회를 갱신합니다.
4. `status=unavailable`이면 `reason`을 표시합니다. 측정 불가도 HTTP `200`일 수 있습니다.
5. 네트워크 오류나 브라우저 요청 취소는 서버 작업 취소를 보장하지 않습니다.
   재시도 전 같은 기간의 이력을 확인하고, 필요하면 같은 요청을 다시 보냅니다.

이 API는 응답 시점에 측정값을 반환합니다. 별도의 `RunAccepted`, 실행 상태 URL,
시그널 전용 SSE, 취소 API는 없습니다. 기존 Run SSE 컨트롤러에 연결하지 않습니다.
같은 정의, 기간, 데이터 스냅샷은 기존 `measurement_id`를 반환하며 데이터가 바뀌면 새 측정이 추가됩니다.

**수동 요청은 전체 측정 이력에 저장되며 새 `daily-results` 실행 행을 생성하지 않습니다.**
이미 자동 실행한 날짜라면 그 행의 `measurement`에 최신 성공 값이 반영됩니다.
자동 이력이 없는 기간을 즉시 비교하려면 전체 이력에서 두 `measurement_id`를 선택해 비교 API에 전달합니다.

## 자동 실행과 과거 일별 결과 보충

기본 주기는 `daily`, 시간대는 `Asia/Seoul`입니다. 한국시간 00:00을 경계로 직전 하루를 측정합니다.
Backend는 기본 60초 간격으로 실행 대상을 확인하므로 일정 저장 응답은 분석 완료를 뜻하지 않습니다.
주기나 시간대 변경은 현재 API 계약에 없으며 `interval`, `timezone`을 PUT 본문에 보내면 `422`입니다.

다음은 9월 8일의 결과부터 닫힌 일자를 순차 보충하는 요청입니다.

```http
PUT /api/signals/{id}/schedule
Content-Type: application/json

{
  "enabled": true,
  "next_run_at": "2026-09-09T00:00:00+09:00"
}
```

`next_run_at`은 **첫 측정 기간의 종료 경계**입니다. 위 요청은 9월 8일 00:00 이상,
9월 9일 00:00 미만부터 시작합니다. 한국시간 자정인 시간대 포함 문자열이어야 합니다.
진행 중인 오늘은 아직 닫히지 않았으므로 자동 실행하지 않습니다.

응답 형식 예시는 다음과 같습니다. 실제 ID와 시각은 서버가 반환한 값을 사용합니다.

```json
{
  "signal_id": "signal-example",
  "enabled": true,
  "interval": "daily",
  "timezone": "Asia/Seoul",
  "next_run_at": "2026-09-08T15:00:00Z",
  "updated_at": "2026-09-10T09:00:00Z",
  "signal_status": "active"
}
```

한 번의 확인 주기마다 시그널당 한 기간씩 처리합니다. 5일이 밀려 있으면 여러 확인 주기가 필요합니다.
FE에서는 상세 화면이 열려 있는 동안 약 5초 간격으로 일정과 `daily-results`를 조회하는 방식을 제안합니다.
화면 이탈 시 조회를 중단하고, 복귀 시 다시 읽습니다. 숨긴 탭에서는 조회를 줄일 수 있습니다.
이 간격은 FE 구현 제안이며 Backend 실행 주기를 바꾸지 않습니다.

`pending_days=0`과 `running` 행이 없는 상태를 누락 보충 완료로 표시합니다.
`pending_days`는 중지된 시그널에도 누락 기간 수를 표시하므로 자동 실행 조건을 함께 확인해야 합니다.
일별 `unavailable`도 처리된 기간이며 실패 사유와 재측정 버튼을 제공합니다.

자동 분석 재개는 저장된 커서부터 누락을 보충합니다. 누락 보충 없이 앞으로만 분석하려면
`enabled=true`와 다음 미래 한국시간 자정을 함께 보냅니다.
이 API에는 보충 종료일이나 정확히 N일만 실행하는 옵션이 없습니다.
특정 기간 하나만 실행하려면 수동 재측정 API를 사용합니다.
이미 시작한 측정은 중지 요청 이후에도 완료될 수 있습니다.

## 이력과 비교 조회

| 용도 | API | FE 해석 |
| --- | --- | --- |
| 등록 목록 | `GET /api/signals` | `items`를 `signal_id`로 식별 |
| 상세 정의 | `GET /api/signals/{id}` | 고정 정의와 시그널 상태 |
| 일정 | `GET /api/signals/{id}/schedule` | 실행 조건과 다음 실행 경계 |
| 전체 측정 이력 | `GET /api/signals/{id}/measurements` | 수동 측정과 최초 측정을 포함한 `items`, 기간별 `latest_by_window` |
| 일별 실행 이력 | `GET /api/signals/{id}/daily-results?limit=30` | 자동 실행만 최신순으로 반환 |
| 최근 두 일별 기간 비교 | `GET /api/signals/{id}/comparison` | 최신 일별 실행 두 개의 측정 비교 |
| 사용자가 선택한 두 측정 비교 | 아래 쿼리 예시 | 같은 시그널의 두 `measurement_id` 필수 |

```text
GET /api/signals/{id}/comparison?baseline_measurement_id={기준ID}&target_measurement_id={비교ID}
```

ID와 시각 쿼리는 `URLSearchParams`로 인코딩합니다. 두 ID 중 하나만 보내면 `422`,
다른 시그널의 측정이거나 없는 ID이면 `404`입니다. 기준 기간은 비교 기간보다 앞서야 합니다.
최신 두 일별 기간 사이에 날짜가 비어 있을 수 있으므로 카드에 실제 두 날짜를 표시합니다.

`daily-results.items`의 각 행에서 읽을 필드는 다음과 같습니다.

| 필드 | 의미 |
| --- | --- |
| `execution_id` | 일별 실행 행의 키 |
| `start_at`, `end_at` | 시작 포함, 종료 제외인 측정 기간 |
| `status` | 자동 실행 결과 `running`, `success`, `unavailable` |
| `measurement` | 해당 기간의 최신 성공 우선 측정, 실행 완료 전에는 `null` 가능 |
| `measurement.status` | 표시할 측정값의 가용 여부 |
| `measurement.values` | `key`로 식별할 지표 목록 |
| `next_before` | 응답 최상위의 다음 페이지 커서, 마지막 페이지에서는 `null` |
| `pending_days` | 응답 최상위의 아직 커서가 처리하지 않은 완료 기간 수 |

자동 실패 이후 수동 재측정이 성공하면 행의 `status=unavailable`과
`measurement.status=success`가 함께 올 수 있습니다. 자동 실행 상태와 현재 표시할 수치를 구분합니다.
이력의 다음 페이지는 응답의 `next_before`를 `before`로 보내며 경계는 포함하지 않습니다.
`limit`은 기본 30, 최대 100입니다. 그래프를 오래된 날짜부터 그리려면 반환 행을 역순으로 정렬합니다.
UTC 응답 날짜를 브라우저 현지 시간대로 잘라 쓰지 않고 `Asia/Seoul` 기준의 관측 시작일로 표시합니다.

비교 응답의 표시용 필드 발췌입니다. 실제 응답에는 `baseline`, `target` 측정 객체도 포함됩니다.

```json
{
  "comparable": true,
  "comparison_limitations": [],
  "metrics": [{
    "key": "affected_customer_rate",
    "label": "대상 고객 비율",
    "unit": "percent",
    "baseline_value": 65.38461538461539,
    "target_value": 68,
    "absolute_change": 2.615384615384613,
    "change_unit": "percentage_points",
    "relative_change_percent": 3.9999999999999964
  }]
}
```

- `comparable=false`: `comparison_limitations` 표시, 증감 수치 표시 생략
- `measurement.status=unavailable` 또는 값 `null`: 측정 불가 표시, 0으로 변환 금지
- `unit=percent` 또는 `%`: 이미 백분율인 값, 다시 100을 곱하지 않음
- `change_unit=percentage_points`: `%p`로 표시
- `relative_change_percent=null`: 기준값 0으로 상대 변화 계산 불가
- `absolute_change`의 부호: 증가 또는 감소, 개선 또는 악화 판정은 지표의 의미에 따라 별도 결정

자동 일별 데이터와 여러 날짜에 걸친 등록 최초 측정은 별도 표시합니다.
전체 이력의 `comparable`과 선택한 두 측정의 `comparable`은 대상이 달라 결과가 다를 수 있습니다.

## HTTP 오류와 갱신 규칙

| 상황 | FE 처리 |
| --- | --- |
| `200`, `Measurement.status=success` | 결과 표시, 관련 조회 갱신 |
| `200`, `Measurement.status=unavailable` | 실패 사유 표시, 이력 갱신, 재측정 제공 |
| 일정 변경 `409` | 실행 중 안내, 일정 재조회 후 사용자 재시도 |
| 후보 등록 `409` | 완료된 분석의 후보인지 재확인 |
| `404` | 목록 갱신, 존재하지 않는 상세 선택 해제 |
| `422` | 요청 필드와 기간 검증, `detail`의 문자열 또는 검증 오류 배열 처리 |
| 네트워크 오류 또는 `5xx` | 성공 표시 금지, 상태와 이력 재조회 후 재시도 제공 |

시그널별 중복 클릭을 막고 요청이 끝나면 버튼을 복원합니다.
예를 들어 조회 키를 `['signals', id, 'schedule']`, `['signals', id, 'measurements']`,
`['signals', id, 'daily-results', filters]`, `['signals', id, 'comparison', selection]`으로 분리할 수 있습니다.
수동 측정 이후 페이지와 비교 선택별 캐시까지 갱신합니다. 키 구조는 FE 구현 제안입니다.

등록과 수동 측정의 `X-Langfuse-Trace-Id` 응답 헤더는 디버깅에 사용할 수 있습니다.
일정 PUT에는 이 헤더가 없습니다. 일별 실행 trace는 `execution_id`에서 하이픈을 제거한 ID이며,
측정의 `trace_id`는 중복 제거로 최초 저장 trace를 유지할 수 있습니다.

## 연결 완료 확인

- 후보 등록 후 `signal_id`로 상세와 일정 조회
- 날짜가 지정된 “지금 분석” 요청과 로딩 상태, 성공 또는 측정 불가 표시
- 수동 측정 후 전체 이력 갱신, 자동 실행 행이 없어도 측정값 확인
- 자동 분석 토글과 시그널 `active` 상태의 조합 확인
- 과거 `next_run_at` 설정 후 일별 실행 행과 누락 기간 수의 변화 확인
- 자동 분석 중지 후 기존 이력 보존 확인
- 두 날짜의 비교와 `%p` 표시, 비교 불가 사유 표시
- 일별 결과 페이지네이션과 한국시간 날짜 라벨 확인
- `404`, `409`, `422`, 네트워크 오류 처리 확인

2026-09-10 검증에 사용한 기존 활성 시그널은
`signal-67575879e224408abbe4bc9d2287d6b6`과 `signal-a0a29924499e490685af65c5e7dd5d5f`입니다.
로컬 DB의 예시이므로 FE 코드에 고정하지 않고 목록 API에서 선택합니다.
Backend가 실행 중이어야 자동 측정이 동작하며 중단 중 누락은 재시작 후 보충합니다.
