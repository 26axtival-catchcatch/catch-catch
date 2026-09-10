# B1 시그널 목록 API FE 인계

작성일: 2026-09-10
대상: `docs/main-screen-ideas.html`의 B형, B1 대화형 마무리 화면 연결 담당자

**B1 카드 목록은 `GET /api/signals/briefing` 한 번으로 조회합니다.**
카드 이름과 설명, 최신 지표, 두 기간의 증감, 최근 7개 기간의 추이를 반환합니다.
Backend 구현과 테스트를 추가했으며 FE의 실제 API 연결과 B1 마지막 카드 구현은 인계 범위입니다.

## 호출 계약

```http
GET /api/signals/briefing?status=active&limit=20&offset=0
```

- 로컬 기본 주소: `http://127.0.0.1:8000`
- FE 환경 설정: `NEXT_PUBLIC_API_BASE_URL`
- [Swagger signals](http://127.0.0.1:8000/docs#/signals)
- OpenAPI 응답 모델: `SignalBriefingList`
- 기존 원본 목록: `GET /api/signals`, 모든 상태의 `Signal` 정의 반환

새 Backend 코드가 로드되어야 새 경로가 노출됩니다. 실행 중인 서버가 `--reload`를 사용하지 않으면
저장소 Launcher로 Backend를 재시작합니다. 이 작업에서는 실행 중인 서버를 교체하지 않았습니다.

| 쿼리 | 기본값 | 허용 범위 |
| --- | --- | --- |
| `status` | `active` | `active`, `paused`, `archived`, `all` |
| `limit` | `20` | 정수 1~100 |
| `offset` | `0` | 0 이상의 정수 |

정렬은 최신 등록순입니다. 최신 측정 시각이나 영향도 순위가 아닙니다.
카드 넘기기는 서버에 읽음이나 보류 상태를 저장하지 않습니다.
등록, 상태 변경, 재측정 후에는 첫 페이지부터 다시 조회합니다.
페이지 사이에 등록이나 상태 변경이 발생하면 위치가 달라질 수 있으므로 `signal_id`로 중복을 제거합니다.

빈 목록의 전체 응답 예시는 다음과 같습니다. `generated_at`은 매 요청의 실제 UTC 시각입니다.

```json
{
  "generated_at": "2026-09-10T01:00:00Z",
  "items": [],
  "total": 0,
  "limit": 20,
  "offset": 0,
  "next_offset": null
}
```

| 응답 필드 | 의미 |
| --- | --- |
| `generated_at` | 조회 시각, 브리핑 발행이나 분석 완료 시각과 별개 |
| `items` | 현재 페이지의 `BriefingSignal` 목록 |
| `total` | 상태 필터를 적용한 전체 시그널 수, 마무리 카드 제외 |
| `limit`, `offset` | 요청 페이지 크기와 시작 위치 |
| `next_offset` | 다음 요청의 `offset`, 더 없으면 `null` |

`next_offset !== null`로 다음 페이지를 판단합니다. 현재 페이지가 비었다는 사실만으로
등록 시그널이 없다고 판단하지 않고 `total === 0`을 확인합니다.
잘못된 쿼리는 `422`이며 서버나 네트워크 오류는 빈 브리핑과 구분해 재시도 버튼을 표시합니다.

## 카드 필드와 기존 화면 매핑

| API 필드 | FE 표시 또는 사용처 |
| --- | --- |
| `signal_id` | `BriefingSignal.id`, React key, 상세 조회 ID |
| `title` | `name`, `chipLabel`, 기본 `headline` |
| `description` | 등록 당시 설명인 `body` |
| `status` | 추적 상태 `active`, `paused`, `archived` |
| `origin` | 등록 경로 `analysis`, `user_defined` |
| `created_at` | 시그널 등록 시각 |
| `source_ids` | 소스 개수와 이름 표시, `GET /api/sources`의 `items[].source_id`, `label`과 매핑 |
| `population_description` | 대상 고객군 설명 |
| `latest_measurement` | 최신 관측 기간과 지표, 이력이 없으면 `null` |
| `comparison` | 최근 두 관측 기간의 증감과 비교 불가 사유 |
| `trend` | 최근 기간의 측정 요약, 전체 추이 비교 가능 여부 |

`description`에는 최초 분석 당시 숫자가 포함될 수 있습니다. 이를 매일 갱신된 설명으로 표시하지 않고
등록 당시 설명으로 구분합니다. 최신 수치는 `latest_measurement.values`에서 표시합니다.
API가 제목의 숫자 강조나 자연어 요약을 새로 생성하지 않으므로 기존 목업의 문장을 재사용하지 않습니다.

`origin`은 등록 경로만 나타내며 사용자 ID나 특정 요청과의 연결을 보장하지 않습니다.
이를 근거로 “내 요청으로 잡음” 배지를 표시하면 안 됩니다.
소스 개수도 시그널 정의에 사용한 소스 수이며 개별 근거 문서 수가 아닙니다.
목록에는 `definition`의 SQL, `cohort_customer_ids`, `query_results`, `queries`가 없습니다.

### 최신 측정값

`latest_measurement`와 `trend.points[]`는 같은 요약 모델입니다.

| 필드 | 의미 |
| --- | --- |
| `measurement_id` | 측정 ID, 지정 기간 비교와 상세 이력 연결 |
| `start_at`, `end_at` | 시작 포함, 종료 제외인 관측 기간 |
| `measured_at` | 이 값을 측정한 시각 |
| `status` | `success`, `unavailable` |
| `reason` | 공개 가능한 측정 불가 사유, 없으면 `null` |
| `values` | `MetricValue` 목록, `key`로 식별 |

`MetricValue`에는 `key`, `label`, `value`, `unit`, `numerator`, `denominator`가 있습니다.
`value`는 숫자 또는 `null`이고, 지표 목록 자체가 비어 있을 수도 있습니다.
`percent`와 `%`는 이미 0~100 단위이므로 100을 다시 곱하지 않습니다.
나머지 단위는 응답의 `unit`을 기준으로 표시합니다.

최초 등록, 수동 측정, 자동 측정의 이력을 모두 사용합니다.
같은 기간에는 최신 성공을 우선하며 성공이 없을 때 최신 측정 불가를 선택합니다.
최신 관측 기간이 측정 불가이면 과거 성공을 최신값으로 대신 표시하지 않습니다.
이력이 없으면 “측정 이력 없음”, `unavailable`이면 `reason`, 값이 `null`이면 “측정 불가”로 표시합니다.
숫자 0은 유효한 측정값이므로 `value == null`로 검사해야 합니다.

### 지표 증감

`comparison`의 필드는 `baseline_measurement_id`, `target_measurement_id`, `comparable`,
`comparison_limitations`, `metrics`입니다. 두 측정 ID는 비교할 기간이 없으면 각각 `null`일 수 있습니다.
`comparable=true`인 경우에만 같은 `key`의 현재 지표와 `metrics`를 연결합니다.

한 지표의 응답 예시입니다.

```json
{
  "key": "affected_customer_rate",
  "label": "대상 고객 비율",
  "unit": "percent",
  "baseline_value": 10,
  "target_value": 15,
  "absolute_change": 5,
  "change_unit": "percentage_points",
  "relative_change_percent": 50
}
```

위 예시의 표시는 현재값 `15%`, 변화량 `▲ 5%p`입니다.
`absolute_change`가 양수면 `up`, 음수면 `down`, 0이면 화살표 없이 “변화 없음”으로 표시합니다.
기준값이 0이면 `relative_change_percent=null`이지만 절대 변화량은 표시할 수 있습니다.
비교 불가이면 `metrics=[]`와 사유를 반환하며 0% 변화로 대체하지 않습니다.

비교 기준은 최근 두 관측 기간입니다. “전일 대비”나 “지난달 대비”를 고정 문구로 사용하지 않습니다.
실제 기간을 표시하고, 상세 비교에서 같은 결과를 보려면 두 측정 ID를 함께 전달합니다.

```text
GET /api/signals/{id}/comparison?baseline_measurement_id={기준ID}&target_measurement_id={비교ID}
```

파라미터 없는 `/comparison`은 자동 실행 두 기간만 비교하므로 목록 카드와 결과가 다를 수 있습니다.

### 추이 그래프

`trend.points`는 관측 종료 시각, 시작 시각을 기준으로 오래된 순서이며 최대 7개 기간입니다.
각 점에서 같은 지표 `key`의 값을 선택합니다. 대상 고객 수가 필요하면
`affected_customer_count`, 비율이면 `affected_customer_rate`를 사용합니다.

`trend.comparable=false`이면 그래프를 숨기고 `comparison_limitations`를 표시합니다.
기간 길이나 버전, 지표 구성 등이 다를 때 서로 다른 측정을 이어 그리지 않도록 하는 계약입니다.
최근 두 기간의 `comparison.comparable=true`와 전체 `trend.comparable=false`가 함께 올 수 있습니다.

기존 `trend: number[]` 화면에 맞출 때는 실제 최솟값과 최댓값으로 0~1 정규화를 적용합니다.
모든 값이 같으면 모든 점을 `0.5`로 두어 수평선으로 표시합니다.
`null`과 측정 불가 값을 0으로 대체하지 않습니다.
기간 사이에 날짜가 비면 같은 간격의 일별 그래프로 보이지 않도록 실제 시각 축이나 기간 라벨을 사용합니다.
관측 날짜는 `Asia/Seoul`로 표시하고 `generated_at`을 데이터의 관측일로 사용하지 않습니다.

## B1 카드와 대화 연결 순서

1. 첫 페이지를 읽고 `items`를 시그널 카드로 변환합니다.
2. 마지막으로 불러온 카드를 넘길 때 `next_offset`이 있으면 같은 필터로 다음 페이지를 읽습니다.
3. `next_offset=null`일 때 FE가 “오늘 브리핑 끝, 더 찾아볼까요?” 카드를 한 장 추가합니다.
4. 전체 시그널 수가 N이면 B1 페이지 수는 N+1이며 마지막 칩은 `⊕ 더 찾기`입니다.
5. “비슷한 걸 더 찾기”와 마지막 카드의 입력 진입은 화면 아래 대화 영역을 엽니다.
6. `total=0`이면 첫 화면부터 빈 상태 설명과 대화 입력을 표시합니다.

`1 / 3`, `2 / 3`, `3 / 3`은 시그널 두 개일 때의 예시입니다.
“더 찾기” 카드는 API의 시그널 객체나 등록 대상으로 만들지 않습니다.
새로고침 시 현재 시그널 ID가 여전히 있으면 카드 위치를 유지하고, 없어졌으면 첫 카드로 이동합니다.

| 버튼 | 연결 |
| --- | --- |
| 이 시그널 확인하기 | `GET /api/signals/{signal_id}`, 측정 이력과 일정 상세 |
| 넘기기, 칩, 스와이프 | FE 카드 이동, 서버 상태 변경 없음 |
| 비슷한 걸 더 찾기 | 현재 카드 제목을 입력 초안으로 사용하고 사용자 편집 후 새 분석 요청 |
| 마지막 카드의 추적 시작 | 기존 `POST /api/runs`와 Run 진행 흐름으로 분석 시작 |
| 분석 완료 후 후보 등록 | 후보 목록에서 선택 후 `POST /api/signals`에 `proposal_id` 전달 |
| 등록 완료 | 브리핑 첫 페이지를 다시 조회 |

목록 조회는 새 시그널을 발견하거나 자동 등록하지 않습니다.
분석 결과가 있어도 등록 전 후보는 이 목록에 포함되지 않습니다.
대화 입력은 SQL 직접 등록 API에 그대로 보내지 않고 기존 분석과 후보 선택 흐름을 사용합니다.
일정과 수동 재측정 버튼은 [시그널 실행 트리거 FE 인계](signal-trigger-fe-handoff.md)를 참고합니다.

## 실제 FE 수정 위치

| 파일 | 필요한 변경 |
| --- | --- |
| `frontend/src/features/signal-catcher/SignalCatcherApp.tsx` | `DEMO_BRIEFING` 공급 부분을 API 조회 상태로 교체, 등록 완료 후 새로고침 |
| `frontend/src/features/signal-catcher/briefing/types.ts` | 비교 없음과 변화 없음 표현을 위해 `delta`, `direction`의 선택적 또는 `null` 상태 추가 |
| `frontend/src/features/signal-catcher/briefing/BriefingScreen.tsx` | 측정 기간, 불가 사유, 로딩과 실패 상태, B1 마지막 카드와 아래 대화 영역 연결 |
| `frontend/src/features/signal-catcher/briefing/use-swipe-deck.ts` | B1의 N+1 카드 이동과 페이지 추가 시 현재 카드 유지 확인 |
| `frontend/src/features/customer-intelligence/run-client.ts` | 기존 API 기본 주소, 오류 처리와 응답 디코더 방식 참고 |

현재 `BriefingScreen`은 상단 요청 버튼과 시그널 N장 덱을 사용합니다.
HTML의 B1처럼 마지막 카드를 추가하려면 화면 상태도 수정해야 합니다.
현재 `onOpenSignal`은 새 분석을 시작하므로 시그널 상세를 여는 동작으로 교체해야 합니다.
현재 `onRequestWatch`는 로컬 요청 배열만 갱신하므로 등록 완료로 해석하면 안 됩니다.

기존 `watchingCount`, `backlogCount`, `requestCount`, `pastDates`에 해당하는
실험 수, 사용자별 읽음과 보류 이력, 브리핑 발행 이력은 이번 API에 없습니다.
목업 값을 실제 집계로 표시하지 않고 해당 영역을 숨기거나 별도 기능과 연결합니다.
`askPlaceholder`와 `suggestions`는 FE 문구입니다.
상단 문구는 `total`로 “추적 중인 시그널 N개”처럼 구성하며 오늘 새로 발견한 개수로 표현하지 않습니다.

## Backend 구현과 검증

- 라우트: `backend/src/customer_signal/signals/api.py`
- 공개 카드 모델과 기간 선택: `backend/src/customer_signal/signals/briefing.py`
- 단일 SQLite 읽기 스냅샷과 페이지 조회: `backend/src/customer_signal/signals/store.py`
- 회귀 테스트: `backend/tests/test_signal_briefing_api.py`
- 전체 API 계약: [API 엔드포인트](api-endpoints.md)

목록 개수, 페이지, 해당 페이지의 측정 이력을 한 DB 스냅샷에서 읽습니다.
이력을 일괄 조회하므로 카드마다 DB 연결을 추가하지 않습니다.
현재는 선택된 페이지의 전체 측정 이력을 메모리에서 기간별로 정리하므로 장기간 이력이 크게 늘면
DB에서 기간별 최신값을 제한하는 조회로 개선할 수 있습니다.

```sh
uv run --project backend pytest backend/tests/test_signal_briefing_api.py -q
uv run --project backend pytest backend/tests -q
uv run --project backend ruff check backend
```

검증은 임시 SQLite와 합성 측정값을 사용합니다. 실제 모델 호출과 운영 데이터 변경은 없습니다.
브리핑 경로가 없는 상태에서 테스트 실패를 확인한 뒤 구현했습니다.
빈 목록, 필터, 페이지 경계, 측정 불가, 과거 재측정, 성공 우선 선택, 비교와 추이 제한,
응답의 원본 데이터 제외, Swagger 응답 스키마를 검증합니다.

2026-09-10 검증 결과입니다.

- Backend 전체 테스트 947개 통과
- 신규 브리핑 테스트 16개와 기존 등록, 상세, 자동 측정 API 테스트를 합친 44개 통과
- `ruff check backend` 통과
- 임시 데이터로 실제 앱의 새 경로와 `/docs`, `/openapi.json` 응답 확인
- 합성 이벤트를 계산한 등록, 재측정, 브리핑 조회 흐름에서 대상 고객 1명, 모집단 2명, 비율 50% 확인
- 같은 흐름에서 두 기간 비교 가능과 추이 2개 점 확인

테스트 도구에서 기존 Starlette의 `httpx` 사용 중단 예정 경고가 발생했습니다.
FE 렌더링과 실행 중 서버의 HTTP 접속 검증은 이번 범위에 포함되지 않습니다.
