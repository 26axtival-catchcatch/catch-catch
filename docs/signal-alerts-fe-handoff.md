# 시그널 알림 임계점 프론트 인계

작성일: 2026-09-10

시그널 등록 응답의 `alert_recommendations`를 보여주고, 사용자가 고른 조건을 저장한 뒤
`GET /api/signal-alert-events`를 폴링하면 됩니다. 이벤트는 백엔드의 일일 자동 측정과
수동 재측정이 생성합니다. 폴링 요청 자체는 측정이나 모델 호출을 실행하지 않습니다.

## 연결 순서

1. 기존 `POST /api/signals`로 후보 또는 직접 정의한 시그널 등록
2. 응답의 `alert_recommendations.items`를 선택지로 표시
3. `GET /api/signals/{signal_id}/alert-rules`로 현재 선택과 `revision` 조회
4. 사용자 선택을 `PUT /api/signals/{signal_id}/alert-rules`에 저장
5. 전체 앱에서 `GET /api/signal-alert-events` 폴링
6. 이벤트의 `signal_id`로 시그널 상세 연결

추천은 자동 활성화되지 않습니다. 별도 프론트 화면과 브라우저 알림 표시는 프론트에서 구현합니다.
선택 조건은 시그널당 하나의 공유 설정입니다. 현재 애플리케이션에는 사용자별 설정과 이벤트 분리가 없습니다.

## 등록 응답과 추천 조건

기존 등록 요청과 응답 필드는 유지하며 `Signal`에 다음 필드가 추가됩니다.

```json
{
  "alert_recommendations": {
    "status": "ready",
    "source": "model",
    "items": [
      {
        "recommendation_id": "example-recommendation",
        "metric_key": "affected_customer_rate",
        "metric_label": "대상 고객 비율",
        "metric_unit": "percent",
        "kind": "absolute_change",
        "operator": "gte",
        "threshold": 10,
        "comparison_unit": "percentage_points",
        "window_seconds": 86400,
        "rationale": "직전 비교 가능한 하루보다 대상 고객 비율이 10%p 늘면 확인하는 조건을 제안합니다."
      }
    ],
    "reason": null,
    "generated_at": "2026-09-10T11:00:00Z"
  }
}
```

예시 ID는 설명용입니다. 실제 요청에는 서버가 반환한 ID를 사용해야 합니다.
기본 지표와 사용자 정의 지표를 모두 추천할 수 있으므로 `metric_key` 목록을 고정하면 안 됩니다.
추천 개수는 1~20개이며 같은 지표의 다른 비교 방식이나 임계값을 함께 제안할 수 있습니다.

| 필드 | 의미 |
| --- | --- |
| `metric_key` | 실제 서버 측정값의 지표 키 |
| `metric_label`, `metric_unit` | 서버 측정값의 표시명과 단위 |
| `kind=value` | 현재 하루의 지표값 |
| `kind=absolute_change` | 비교 기준 대비 차이, 현재값에서 기준값을 뺀 값 |
| `kind=relative_change_percent` | `(현재값 - 기준값) / abs(기준값) * 100` |
| `operator` | `gt`: 초과, `gte`: 이상, `lt`: 미만, `lte`: 이하 |
| `threshold` | 사용자가 선택할 추천 임계값 |
| `comparison_unit` | 임계값과 이벤트의 `observed_value` 표시 단위 |
| `window_seconds` | `86400`, 하루 측정에 적용하는 조건 |
| `rationale` | 모델이 작성한 추천 이유 |

예를 들어 비율이 10%에서 15%로 변하면 `absolute_change=5 percentage_points`,
`relative_change_percent=50 percent`입니다. 기준값이 0이면 상대 변화율은 계산하지 않습니다.
비교 기준은 현재 측정 시작 이전에 끝난 가장 최근 성공 측정입니다.
같은 종료 시각에 주간 측정과 하루 측정이 함께 있으면 하루 측정을 우선합니다. 기간 길이, 정의,
Source 범위와 버전, 파이프라인 버전이 달라 비교할 수 없으면 변화 조건은 평가하지 않습니다.
사용자가 선택하지 않은 다른 지표의 결측값은 해당 조건 평가를 막지 않습니다.

추천은 등록 당시 집계값과 지표 의미로 작성한 제안입니다. 실측값, 확정된 업무 규칙,
통계적으로 검증된 경계로 표시하면 안 됩니다. 주간 관측값으로 등록해도 추천은 하루 기준입니다.

## 추천 조회와 재시도

| Method | 경로 | 동작 |
| --- | --- | --- |
| GET | `/api/signals/{signal_id}/alert-recommendations` | 저장된 추천 조회, 모델 호출 없음 |
| POST | `/api/signals/{signal_id}/alert-recommendations` | 추천 없는 기존 시그널의 생성 또는 실패 재시도 |

| 상태 | 프론트 처리 |
| --- | --- |
| `null` | 기존 시그널 또는 추천 저장 전 상태, 생성 버튼 표시 |
| `status=ready` | 선택지 표시 |
| `status=unavailable` | `reason` 표시와 재시도 버튼 제공, 시그널 등록은 유지 |
| `source=fixture` | 외부 모델을 호출하지 않은 합성 데모 추천 |
| `source=model` | 서버의 Gemini 또는 Bedrock 모델 추천 |

이미 `ready`인 추천에 POST하면 같은 내용을 반환합니다. 성공한 추천 ID는 고정하며,
이후 조회나 재측정으로 추천을 다시 생성하지 않습니다. 실패 시 고정 숫자 추천으로 대체하지 않습니다.
중복 등록도 저장된 추천을 유지합니다. 추천 실패의 재시도는 위 POST로 명시적으로 요청합니다.

등록과 추천 생성은 동기 HTTP 요청입니다. 모델 공급자 요청 제한은 40초이며 초기 측정과
서버 처리 시간이 추가됩니다. 프론트 요청 제한은 60초 이상으로 잡고 처리 중 상태를 표시합니다.
알림 추천은 서버 `AGENT_MODE` 설정을 사용하며, 원본 분석 Run의 `mode`를 상속하지 않습니다.

## 조건 조회와 저장

초기 조회 응답입니다.

```json
{"signal_id":"example-signal","revision":0,"items":[]}
```

추천을 선택하고 임계값을 바꾸는 요청입니다. `threshold`를 생략하거나 `null`로 보내면
원래 추천 임계값을 사용합니다.

```http
PUT /api/signals/example-signal/alert-rules
Content-Type: application/json
```

```json
{
  "revision": 0,
  "items": [
    {"recommendation_id": "example-recommendation", "threshold": 8}
  ]
}
```

응답은 `signal_id`, 갱신된 `revision`, 선택된 `items`입니다. 각 항목은 추천의 모든 필드와
`rule_id`를 포함하며 `threshold`에는 현재 사용자가 선택한 값이 들어갑니다.
`rationale`은 원래 모델 추천 이유를 유지합니다. 수정한 조건 문구는 `kind`, `operator`,
현재 `threshold`, `comparison_unit`으로 만들고, 추천 이유는 별도로 표시합니다.

- `items`는 전체 교체 목록, 최대 20개
- 여러 조건은 각각 독립 평가, 하나라도 진입하면 해당 조건의 이벤트 발생
- 같은 추천 ID 중복 선택 불가, 다른 시그널의 추천 ID 사용 불가
- 임계값은 유한한 JSON 숫자, 숫자 문자열과 Boolean 불가
- 비율 지표의 `value` 임계값은 `0~100`, 기본 고객 수의 `value` 임계값은 `0` 이상
- 변화량 조건은 음수 가능, 감소 알림은 예를 들어 `lte -10`으로 표현
- 비교 방식과 방향은 추천에 고정, 사용자는 해당 추천 선택 여부와 숫자만 변경

전체 해제 요청은 현재 `revision`과 빈 `items`입니다.

```json
{"revision":1,"items":[]}
```

동일한 선택과 임계값을 같은 최신 `revision`으로 다시 저장하면 버전과 상태를 유지합니다.
다른 요청이 먼저 저장했다면 `409`입니다. 다시 GET하여 화면을 갱신한 후 사용자 선택을 저장해야 합니다.
오래된 요청을 자동으로 최신 버전에 덮어쓰면 안 됩니다.

## 이벤트 폴링

```http
GET /api/signal-alert-events?after=0&limit=100
```

```json
{
  "items": [
    {
      "sequence": 1,
      "event_id": "example-event",
      "event_type": "threshold_crossed",
      "signal_id": "example-signal",
      "signal_title": "반복 검색 증가",
      "rule": {
        "rule_id": "example-rule",
        "recommendation_id": "example-recommendation",
        "metric_key": "affected_customer_rate",
        "metric_label": "대상 고객 비율",
        "metric_unit": "percent",
        "kind": "absolute_change",
        "operator": "gte",
        "threshold": 8,
        "comparison_unit": "percentage_points",
        "window_seconds": 86400,
        "rationale": "직전 비교 가능한 하루보다 대상 고객 비율이 10%p 늘면 확인하는 조건을 제안합니다."
      },
      "measurement_id": "example-current-measurement",
      "baseline_measurement_id": "example-baseline-measurement",
      "observed_value": 9,
      "metric_value": 24,
      "baseline_value": 15,
      "start_at": "2026-09-09T15:00:00Z",
      "end_at": "2026-09-10T15:00:00Z",
      "occurred_at": "2026-09-10T15:01:00Z"
    }
  ],
  "next_cursor": 1,
  "latest_cursor": 1,
  "has_more": false
}
```

`observed_value`가 실제 임계값과 비교한 수치입니다. `metric_value`는 현재 지표값이며,
`baseline_value`는 변화 비교의 기준값입니다. `kind=value`에서는 기준 ID와 값이 `null`입니다.
알림 조건은 `event.rule`에 발생 당시 스냅샷으로 보존합니다. 사용자가 나중에 설정을 바꿔도
기존 이벤트의 의미가 바뀌지 않습니다. 고객 ID, SQL, 원문 데이터는 이벤트에 포함하지 않습니다.

| 파라미터/필드 | 처리 |
| --- | --- |
| `after` 생략 | 항목 없이 현재 최신 커서 반환, 최초 접속에서 과거 알림 재생 방지 |
| `after=0` | 저장된 전체 이벤트부터 조회 |
| `after=N` | `sequence > N`인 이벤트를 오름차순 반환 |
| `limit` | 기본 100, 범위 1~500 |
| `next_cursor` | 이번 페이지 처리 후 저장할 커서, 빈 페이지에서는 요청 커서 유지 |
| `latest_cursor` | 서버 전체 최신 순번, 상태 표시 용도 |
| `has_more=true` | `next_cursor`로 다음 페이지를 즉시 조회 |

페이지가 남아 있을 때 `latest_cursor`로 건너뛰면 이벤트가 누락됩니다.
커서는 화면에 이벤트를 반영한 뒤 저장하며, 이벤트는 `event_id` 또는 `sequence`로 중복 제거합니다.
폴링은 서버 이벤트를 소비하지 않으므로 여러 탭에서 같은 이벤트를 볼 수 있습니다.
브라우저 알림을 띄우는 탭 조정은 프론트에서 수행합니다.

다음은 폴링 제어 예시입니다. `AlertEvents`는 위 응답에 맞춰 OpenAPI에서 생성한 타입을 사용합니다.
`getPage`는 오류 응답을 throw하는 GET 래퍼, `apply`는 중복 제거 후 화면에 반영하는 함수입니다.

```typescript
export async function pollSignalAlerts(
  getPage: (query: string, signal: AbortSignal) => Promise<AlertEvents>,
  apply: (items: AlertEvents["items"]) => Promise<void>,
  storageKey: string,
  signal: AbortSignal,
): Promise<void> {
  const saved = localStorage.getItem(storageKey);
  let cursor = saved !== null && /^\d+$/.test(saved) ? Number(saved) : null;
  if (cursor !== null && !Number.isSafeInteger(cursor)) cursor = null;
  let failures = 0;
  while (!signal.aborted) {
    let delay = 5000;
    try {
      const query = cursor === null ? "" : `?after=${cursor}&limit=100`;
      const page = await getPage(query, signal);
      if (signal.aborted) return;
      await apply(page.items);
      localStorage.setItem(storageKey, String(page.next_cursor));
      cursor = page.next_cursor;
      failures = 0;
      if (page.has_more) continue;
    } catch {
      if (signal.aborted) return;
      delay = Math.min(30000, 5000 * 2 ** Math.min(++failures, 3));
    }
    await new Promise<void>((resolve) => {
      const done = () => {
        clearTimeout(timer);
        signal.removeEventListener("abort", done);
        resolve();
      };
      const timer = setTimeout(done, delay);
      signal.addEventListener("abort", done, { once: true });
      if (signal.aborted) done();
    });
  }
}
```

저장 키는 연결한 백엔드 환경별로 구분해야 합니다. 저장된 커서가 없을 때 앱 초기화에서
한 번 부트스트랩하고, 그 뒤 조건 선택 화면과 무관하게 폴링을 유지합니다.
알림 권한이 없어도 인앱 반영과 커서 갱신은 계속해야 합니다.
백엔드 저장소를 의도적으로 초기화했다면 프론트 커서도 초기화해야 합니다.

## 이벤트 발생 규칙

- 선택 직후의 기존 측정 이력은 재생하지 않음
- 선택 이후 처리한 하루 측정에서 조건을 처음 충족할 때 이벤트 1개
- 조건을 계속 충족하면 추가 이벤트 없음
- 정상 범위의 유효한 값 관측 후 다시 충족하면 새 이벤트
- 측정 불가, 선택한 지표의 결측, 비교 불가이면 평가 생략, 기존 진입 상태 유지
- `paused` 또는 `archived`인 시그널은 평가 생략
- 중복 측정과 이미 평가한 기간의 수정은 추가 알림 없음
- 성공 평가 전 실패했던 기간은 성공한 재측정으로 복구 가능
- 규칙 숫자 변경이나 재선택은 새 `rule_id`, 이후 측정부터 새 상태로 평가
- 빈 규칙 목록은 평가 해제, 기존 이벤트는 유지

조건을 고를 때 기존 측정의 최대 종료 시각을 기준점으로 저장합니다. 각 조건은 자신이 마지막으로
평가한 종료 시각보다 뒤의 측정만 처리합니다. 과거 이력 수정과 역순 측정으로 상태가 되돌아가지 않습니다.
일일 자동 측정은 기존 한국 시각 자정 스케줄을 사용합니다. 24시간이 아닌 수동 측정은 이력에만 남습니다.
복구 이벤트, 읽음 API, 서버의 Web Push 전송은 이번 계약에 포함되지 않습니다.

## 오류 처리와 검증

| 상태 코드 | 조건 |
| --- | --- |
| `404` | 없는 시그널 |
| `409` | 규칙 `revision` 충돌 또는 추천에 사용할 성공 측정 없음 |
| `422` | 잘못된 추천 ID, 중복 선택, 임계값 타입/범위, 커서/페이지 크기 |
| `200` + `status=unavailable` | 모델 추천 실패, 등록 자체는 유지 |

Swagger의 `signals` 태그에서 요청과 응답 전체 스키마를 확인할 수 있습니다.
실측 검증 절차와 결과는 [알림 검증 기록](verification/signal-alerts.md)에 정리했습니다.
