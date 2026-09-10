# Backend API 엔드포인트 정리

Backend(FastAPI)가 노출하는 HTTP 엔드포인트 목록입니다. 이 문서는 사람이 읽는
요약이고, 기계가 읽는 원본 계약은 실행 중인 서버의 Swagger 문서입니다.

## Swagger 문서 위치

Backend 를 실행하면 FastAPI 가 다음 경로를 자동으로 제공합니다.

| 경로 | 내용 |
| --- | --- |
| `/docs` | Swagger UI |
| `/redoc` | ReDoc UI |
| `/openapi.json` | OpenAPI 3.1 스키마 원본 |

기본 로컬 주소는 `http://127.0.0.1:8000/docs` 입니다. 실제 포트는
`Settings.api_port` 설정을 따릅니다.

## system

| Method | 경로 | 설명 | 응답 |
| --- | --- | --- | --- |
| GET | `/health` | 서비스 상태 확인 | `{"status": "ok"}` |

## sources

| Method | 경로 | 설명 | 응답 |
| --- | --- | --- | --- |
| GET | `/api/sources` | 분석에 사용할 수 있는 공개 Source 목록 조회 | `PublicSourceList` |

목록 조회와 새 Run 생성 시 등록 디렉터리를 다시 읽습니다. 외부에서 승인된 데이터 Source를
추가한 뒤 목록을 새로 조회하면 재시작 없이 다음 분석에 사용할 수 있습니다.

## runs

| Method | 경로 | 설명 | 응답 |
| --- | --- | --- | --- |
| POST | `/api/runs` | 분석 Run 생성. `mode` 쿼리로 agent 모드 지정 가능 | `202` + `RunAccepted` |
| POST | `/api/runs/{run_id}/clarification` | Clarification 대기 중인 Run 에 답변 제출 | `202` + `RunAccepted` |
| GET | `/api/runs/{run_id}` | Run 상태 스냅샷 조회 | `RunSnapshot` |
| GET | `/api/runs/{run_id}/events` | 역할 토폴로지와 모델/도구 진행을 포함한 SSE. `Last-Event-ID` 헤더로 재접속 커서 지정 | SSE `RunEventEnvelope` |
| GET | `/api/runs/{run_id}/presentation` | Canonical Run Event 에서 재계산한 Presentation Intent 목록 조회 | `PresentationReplay` |
| GET | `/api/runs/{run_id}/customers/{customer_id}/journey` | 완료된 Run 의 고객 Journey 조회 | `CustomerJourneyResult` |
| GET | `/api/runs/{run_id}/evidence/{evidence_id}` | 완료된 Run 의 마스킹 Evidence 조회 | `EvidenceResult` |

`mode`는 `auto`, `fixture`, `gemini`, `bedrock`을 지원합니다.
`mode` 생략 시 서버의 `AGENT_MODE`를 사용하며 기본값은 `bedrock`입니다.
`auto`는 유효한 Bedrock 토큰 → Gemini 키 → fixture 순서로 선택합니다.
`mode=bedrock`은 `AWS_BEARER_TOKEN_BEDROCK`, `AWS_REGION`(기본 `us-east-1`),
`BEDROCK_MODEL`(기본 `us.anthropic.claude-opus-4-6-v1`)로 Converse API를 호출합니다.
서버에 `AGENT_MODE=bedrock`을 명시하면 토큰 없이도 AWS SDK 자격증명 체인을 사용합니다.
EC2에서는 인스턴스 역할에 해당 inference profile과 기반 모델의 `bedrock:InvokeModel`,
`bedrock:InvokeModelWithResponseStream` 권한이 필요합니다. 호출별 출력 상한은 8,192 토큰입니다.
investigator는 `BEDROCK_INVESTIGATOR_MODEL`(기본 `us.anthropic.claude-sonnet-4-6`)을
사용하며, coordinator, reporter는 `BEDROCK_MODEL`을 사용합니다.
verifier는 `BEDROCK_VERIFIER_MODEL`을 지정하면 해당 모델을 사용하고, 생략하면
`BEDROCK_MODEL`을 사용합니다. 후보마다 독립 검증 작업을 실행하며 최대 동시 실행 수는 6개입니다.
`mode=gemini`와 `mode=bedrock`은 총괄, 가설별 조사, 독립 검증과 보고 역할을 실행합니다.
Bedrock 호출 실패 시 다른 모델이나 fixture로 자동 전환하지 않습니다.
상태 응답과 SSE의 `agent_mode`에 `bedrock`이 표시되며, 저장 Artifact의
`versions.model_version`에 기본 Bedrock 모델 ID, `versions.agent_mode`에 실행 provider를 기록합니다.
역할별 호출 모델은 관측 metadata의 `model`에 기록합니다.
기존 Artifact는 새 필드 없이도 읽을 수 있습니다. 요청 필드와
기존 SSE payload와 `customer_signal` 보고서 스키마는 유지합니다. 진행 중 실행은 선택한 공간의
스냅샷을 사용하며, 추가된 데이터는 같은 질문과 기간으로 새 Run을 생성해 분석합니다.
사용자 결정으로 전체 실행 시간, 역할별 호출 횟수와 재조사 라운드 제한을 해제했습니다.
완료 시각을 15분 이내로 보장하지 않으며, 확인하지 못한 후보와 중단 사유는 `limitations`에 남깁니다.
위험 점수는 산정하지 않으므로 `ranked_customers`는 비어 있습니다. 대표 고객 식별자는
상태 응답의 `facts` 중 `payload.kind=get_customer_journey`의 `payload.customer_id`를 사용합니다.
기존 고객 Journey와 Evidence 조회 URL은 그대로 사용할 수 있습니다.
새 분석의 상세 조회는 완료된 Run의 Fact에 보관한 여정과 근거를 반환하므로,
추가 데이터의 마스킹 고객 ID도 조회할 수 있고 실행 이후 데이터 변경의 영향을 받지 않습니다.

## 에이전트 액티비티 SSE

기존 이벤트에 `agent_activity`를 추가했습니다. `gemini`와 `bedrock` 실행에서
역할별 토폴로지, 실제 모델과 도구 호출의 시작/완료/실패/취소를 전달합니다.
`node_id`, `parent_node_id`, `depends_on`, `role`, `task_id`, `round_index`로 진행 관계를 표시합니다.
`display_text`, `duration_ms`, 타입이 지정된 `details`에는 공개 요약과 실제 실행 값을 담습니다.
`message_kind=commentary`는 모델의 일반 `text`에서 추출한 짧은 진행 설명이며,
`message_kind=summary`는 에이전트의 결과 요약입니다. 실제 문장은 단톡방 전용 `message_text`에
저장합니다. 기존 `display_text`와 실행 상태를 유지하며, 대화 화면만 새 필드를 읽습니다.
`message_kind=null`인 모델과 도구 호출 상태는 토폴로지에서 확인합니다.
진행 설명은 모델 응답을 받은 뒤 도구 실행 전에 저장합니다. 추론 전용 블록과 도구 인자는
포함하지 않으며, 연락처와 고객 식별자는 가리고 최대 1,000자로 제한합니다.
기존 실행에서 이 필드가 없으면 완료된 에이전트의 공개 요약만 대화에 표시합니다.
과거에 저장하지 않은 모델 텍스트는 자동 복원하지 않습니다.
서버 검사를 반영한 후보 판정은 `kind=assessment`에서 확인합니다.
개별 활동의 실패는 Run 종료가 아니며 최종 종료는 기존 `done`으로 판단합니다.
전체 필드, SSE 예시와 재접속 처리는 [에이전트 액티비티 FE 인계](agent-activity-handoff.md)에 정리했습니다.

## run-artifacts

| Method | 경로 | 설명 | 응답 |
| --- | --- | --- | --- |
| GET | `/api/run-artifacts` | 저장된 Run Artifact 목록 조회 | `ArtifactListResponse` |
| GET | `/api/run-artifacts/{run_id}` | Run Artifact 단건 조회 | Artifact JSON |
| GET | `/api/run-artifacts/{run_id}/document` | Run 보고서 문서 렌더링 조회 | 문서 JSON |
| GET | `/api/run-artifacts/{run_id}/download.json` | Run Artifact JSON 파일 다운로드 | `application/json` |
| GET | `/api/run-artifacts/{run_id}/download.md` | Run 보고서 Markdown 파일 다운로드 | `text/markdown` |

## 공통 오류 응답

| 상태 코드 | 발생 조건 |
| --- | --- |
| `400` | `Last-Event-ID` 헤더가 정수가 아니거나 발행된 이벤트 범위를 벗어난 경우 |
| `404` | 존재하지 않는 Run, Run 리소스, Run Artifact 를 조회한 경우 |
| `409` | 완료되지 않은 Run 의 후속 리소스를 조회하거나, Clarification 대기 상태가 아닌 Run 에 답변한 경우 |
| `422` | `enabled_sources` 에 알 수 없는 Source 가 포함된 경우 |

## Swagger 밖의 경로

`/mcp` 에는 FastMCP 서버가 별도 ASGI 앱으로 mount 되어 있습니다. mount 된 앱은
FastAPI OpenAPI 스키마에 포함되지 않으므로 Swagger UI 에 나타나지 않습니다.

## signals

시그널은 사용자가 선택해 등록한 고정 패턴 정의입니다. 기존 보고서의 일회성 `AnalysisSignal`과 구분합니다.
에이전트의 지표 계산, 후보 제안은 등록 행위가 아닙니다. 완료된 분석의 독립 검증 후보를 선택하거나,
사용자가 정의와 기간을 직접 보내 서버 측정 후 등록합니다. 하나의 조사 태스크는 여러 패턴 후보를 가질 수 있습니다.

| Method | 경로 | 설명 | 응답 |
| --- | --- | --- | --- |
| GET | `/api/signal-proposals` | 완료 분석의 후보 모아보기, 선택적 `run_id` 필터 | `ProposalList` |
| GET | `/api/signal-proposals/{proposal_id}` | 분석 경로 없이 후보 상세 조회 | `Proposal` |
| GET | `/api/runs/{run_id}/signal-proposals` | 완료된 분석의 등록 가능 후보 | `ProposalList` |
| GET | `/api/runs/{run_id}/signal-proposals/{proposal_id}` | 후보 정의, 최초 측정, 근거 | `Proposal` |
| POST | `/api/signals` | `proposal_id` 선택 등록 또는 `title`, `description`, `definition`, `start_at`, `end_at` 직접 등록 | `Signal` |
| GET | `/api/signals` | 등록된 시그널 목록 | `SignalList` |
| GET | `/api/signals/briefing` | B1 브리핑 카드, 최신 측정과 증감, 최근 7개 기간 추이, 상태 필터와 페이지 조회 | `SignalBriefingList` |
| POST | `/api/signals/fast-forward` | 마지막 성공 분석 이후 1~7일 실제 재측정, 데이터 부족 시 중단 | `FastForwardResult` |
| POST | `/api/signals/fast-forward/reset` | 기존 이력을 보관하고 다음 분석 시작일 재설정 | `FastForwardResetResult` |
| GET | `/api/signals/{signal_id}` | 고정 정의와 상태 조회 | `Signal` |
| PATCH | `/api/signals/{signal_id}` | `status`: active/paused/archived | `Signal` |
| POST | `/api/signals/{signal_id}/measurements` | `start_at`, `end_at` 지정 재측정 | `Measurement` |
| GET | `/api/signals/{signal_id}/measurements` | 전체 이력, 기간별 최신 성공 값, 비교 가능 여부 | `MeasurementHistory` |
| GET | `/api/signals/{signal_id}/alert-recommendations` | 저장된 측정 지표별 알림 기준, 기존 데이터는 null 가능 | `RecommendationSet \| null` |
| POST | `/api/signals/{signal_id}/alert-recommendations` | 기존 측정 지표로 알림 기준 준비, 과거 추천 전환 | `RecommendationSet` |
| GET | `/api/signals/{signal_id}/alert-rules` | 사용자 선택 조건과 편집 버전 조회 | `AlertRules` |
| PUT | `/api/signals/{signal_id}/alert-rules` | 지표별 기준 선택과 임계값 변경, 빈 목록으로 전체 해제 | `AlertRules` |
| GET | `/api/signal-alert-events` | `after` 커서 이후 알림 이벤트 폴링, `limit` 페이지 크기 | `AlertEvents` |

알림 기준은 시그널 상세와 Langfuse `customer_signal.signal` span의 측정 지표를 재사용합니다.
`alert_recommendations.source=measurement`이며, 지표마다 `kind=value`, `operator=gte`인 기준 하나를 제공합니다.
초기 `threshold`는 분석 당시 값입니다. 사용자가 하루 기준의 임계값을 조정하고 저장합니다.
기준 준비에는 외부 모델 호출이 없습니다. 기존 `model`과 `fixture` 추천은 POST 또는 재등록 시 전환하고,
이미 선택한 알림 규칙은 사용자가 새 기준을 저장할 때까지 유지합니다.

등록과 재측정은 HTTP 200을 반환합니다. 없는 시그널/후보는 404, 완료되지 않은 Run의 후보 조회, 등록은 409,
잘못된 요청은 422입니다. 직접 등록 시 최초 측정이 불가능해도 422이며 등록을 저장하지 않습니다.
직접 등록의 출처는 `origin=user_defined`, `proposal_id=null`입니다. 기존 등록은 `origin=analysis`입니다.
같은 정의를 재등록하면 기존 ID와 출처를 유지합니다. 수동 재측정 데이터가 부족하거나 SQL이 실패하면 HTTP 200의 `status=unavailable`로 이력을
남깁니다. `values[].value=null`을 0으로 표시하면 안 됩니다. `reason`에는 공개 가능한 실패 사유만 포함합니다.
같은 정의/관측 기간/데이터 스냅샷의 재측정은 기존 측정 ID를 반환합니다. 데이터가 변경되면 새 측정으로 보존합니다.
`latest_by_window`는 기간별 최신 성공 값을 우선하며, 실패 이력은 `items`에 남습니다.
관측 기간 길이, 정의, Source 범위/버전이 다르거나 기간이 겹치면 비교 불가 사유를 반환합니다.
자세한 연결 순서와 수치 해석은 [시그널 FE 인계](signal-fe-handoff.md)를 참고합니다.

빨리감기는 `request_id` UUID와 기본 1인 `days`를 받습니다. `signal_ids`를 생략하면 등록 목록을
고정해 처리하며, 지정하면 중복 없는 1~100개 ID를 받습니다. 한국 시각 기준으로 마지막 성공 분석의
종료 이후 완전한 하루씩 실제 Source를 조회하고 기존 정의의 SQL을 실행합니다.
주간 분석 뒤에는 직전 하루도 알림 평가 없이 측정해 변화량 비교 기준을 준비합니다.
같은 종료 시각에 여러 길이의 성공 측정이 있으면 알림 비교는 하루 측정을 우선합니다.
시그널의 `paused`, `archived` 상태나 비활성 일정은 사유와 함께 건너뜁니다.
빨리감기 대상 날짜에 데이터가 없거나 SQL 측정이 불가능하면 해당 항목은 `status=blocked`와
`reason`을 반환합니다. 실패한 날짜의 측정과 일별 실행을 저장하지 않으며 다음 클릭에서도 같은 날짜를
시도합니다. 여러 날 요청은 성공한 날짜까지 `daily_results`에 담고 첫 실패에서 멈춥니다.
예전 버전의 `unavailable` 이력은 다음 분석일 계산에서 제외합니다.

같은 `request_id`와 입력을 재전송하면 날짜를 더 전진시키지 않고 저장한 결과를 반환합니다.
같은 ID에 다른 입력을 보내거나 측정 잠금이 사용 중이면 `409`입니다. 잠금 충돌은 같은 ID로
재시도합니다. 수동 재측정과 추적 상태 변경도 자동 측정 또는 빨리감기 실행 중이면 `409`입니다.
응답의 `items[].daily_results`는 실행 결과, `baseline_measurement`는 직전 하루 기준,
`alert_events`는 해당 실행의 측정에 연결된 실제 알림입니다. 기존 이벤트 폴링 커서는 유지합니다.
시작일 재설정은 `request_id`, 한국 시각 자정인 `start_at`, 선택 사항인 `signal_ids`를 받습니다.
생략하면 활성 시그널 중 일별 측정이 켜진 대상만 처리합니다. 모든 대상의 시작일 데이터와 전날
기준 측정을 검증한 후 한 트랜잭션으로 기존 측정, 일별 실행, 일정, 알림 평가 상태를
`signal_tracking_archives`에 보관하고 활성 이력을 전날 기준 측정으로 교체합니다.
시그널 정의, 선택한 알림 조건, 기존 발송 이벤트는 유지합니다. 활성 이력은 기존 조회 API에서,
이전 이력은 SQLite 보관 테이블에서 확인합니다. 날짜 재설정은 새 알림 평가를 시작하므로 같은 조건이
다시 충족되면 새 이벤트가 발생할 수 있습니다. 같은 요청의 재전송은 결과만 재생합니다.
재설정 전에 중단된 빨리감기 예약은 재설정된 대상에 한해 `skipped`로 종료합니다.
관측 데이터가 없거나 자정이 아닌 입력은 `422`, 비활성 대상을 명시하면 `409`입니다.

호출 예시, 데이터 준비 범위, 실패 복구는 [빨리감기 FE 인계](signal-fast-forward-fe-handoff.md)에 정리했습니다.

등록 응답의 `Signal.alert_recommendations`에 모델이 지표별로 제안한 하루 기준 조건을 제공합니다.
사용자가 `alert-rules`에 선택하기 전에는 이벤트를 만들지 않습니다. 추천 실패는 등록을 취소하지 않고
`status=unavailable`로 표시합니다. 성공한 추천은 고정하며 재등록과 조회에서 다시 생성하지 않습니다.
추천 모델은 서버의 `AGENT_MODE`를 사용합니다. Bedrock은 `BEDROCK_INVESTIGATOR_MODEL`,
Gemini는 `GEMINI_MODEL`을 사용하며 provider 실패를 fixture로 대체하지 않습니다.

규칙 PUT에는 조회한 `revision`과 전체 `items`를 보냅니다. 버전 충돌은 409, 잘못된 추천 ID,
중복 선택과 임계값은 422입니다. 빈 목록은 전체 해제입니다. 숫자를 바꾸지 않은 동일 선택은 상태를 유지합니다.
성공한 하루 측정이 조건에 진입할 때만 이벤트를 저장하며 정상 범위 관측 후 재진입하면 다시 생성합니다.
측정과 규칙 상태, 이벤트 저장은 하나의 트랜잭션입니다. 결측과 비교 불가는 진입 상태를 초기화하지 않습니다.

이벤트 GET의 `after`를 생략하면 항목 없이 현재 최신 커서를 반환합니다. `after=0`은 전체 이력,
`after=N`은 `sequence > N`의 오름차순 페이지입니다. `limit`은 기본 100, 최대 500입니다.
응답의 `next_cursor`를 처리 후 저장하며 `has_more=true`이면 바로 다음 페이지를 조회합니다.
`latest_cursor`는 전체 최신 순번이므로 페이지를 건너뛰는 용도로 사용하면 안 됩니다.
현재 설정과 이벤트는 앱 전체에서 공유합니다. 전체 응답 예시와 프론트 연결 순서는
[시그널 알림 FE 인계](signal-alerts-fe-handoff.md)에 정리했습니다.

등록, 재측정 성공 응답 헤더 `X-Langfuse-Trace-Id`는 해당 작업을 기록한 trace ID입니다.
후보 선택 등록은 **원래 분석 trace**, 직접 등록, 수동 재측정은 **이번 API 작업 trace**를 반환합니다.
새 `Proposal.trace_id`, `Proposal.observation_id`로 분석 trace와 개별 패턴 span을 연결합니다.
후보 선택 등록 span은 해당 패턴 span의 자식이며 별도의 발화 trace를 생성하지 않습니다.
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

## 메인 B1 브리핑 목록

`GET /api/signals/briefing`은 등록된 시그널을 최신 등록순으로 조회합니다.
기본 `status=active`이며 `paused`, `archived`, `all`도 지정할 수 있습니다.
`limit`은 기본 20, 범위 1~100이고 `offset`은 기본 0인 음이 아닌 정수입니다.
잘못된 쿼리는 `422`, 빈 목록과 범위를 넘은 페이지는 `200`입니다.
기존 `GET /api/signals`의 전체 목록 계약은 유지합니다.

응답에는 `generated_at`, `items`, 필터 적용 후 전체 개수인 `total`, `limit`, `offset`,
다음 페이지의 `next_offset`이 있습니다. 마지막 페이지의 `next_offset`은 `null`입니다.
`generated_at`은 조회 시각이며 일별 분석 완료나 브리핑 발행 시각이 아닙니다.

각 카드에는 `signal_id`, `title`, `description`, `status`, `origin`, `created_at`,
`source_ids`, `population_description`, `latest_measurement`, `comparison`, `trend`가 있습니다.
`description`은 등록 당시 설명입니다. 최신 수치에 맞춘 설명을 새로 생성하지 않습니다.
조회는 저장된 정의와 측정 이력만 읽으며 LLM, 원본 Source 조회나 재측정을 실행하지 않습니다.
SQL, 고객 식별자, 원본 쿼리 결과는 이 응답에서 제외합니다.

최초 등록, 수동 측정, 자동 측정을 모두 포함해 같은 시작과 종료 기간의 최신 성공 값을 우선합니다.
성공이 없는 기간은 최신 측정 불가 값을 사용합니다. 관측 종료 시각, 시작 시각 순으로 정렬한 뒤
최근 7개 기간을 남깁니다. 과거 기간을 나중에 재측정해도 최신 관측 기간을 대체하지 않습니다.
`latest_measurement`는 마지막 기간의 값이며 이력이 없으면 `null`입니다.

`comparison`은 최근 두 기간의 측정 ID, `comparable`, `comparison_limitations`, `metrics`입니다.
기간 길이, 겹침, 지표 구성, 단위, Source나 파이프라인 버전이 맞지 않거나 값이 없으면
`comparable=false`, `metrics=[]`입니다. 증감 단위 `percentage_points`는 `%p`로 표시합니다.
기본 `/comparison`이 자동 실행 두 기간만 비교하는 것과 달리 이 목록은 모든 측정 경로를 포함합니다.

`trend.points`는 오래된 기간부터 최대 7개 측정 요약을 제공합니다.
`trend.comparable=false`이면 그래프를 그리지 않고 `comparison_limitations`를 표시합니다.
마지막 두 기간의 비교가 가능해도 전체 추이는 비교 불가일 수 있습니다.
측정 불가와 `null` 값을 0으로 바꾸면 안 됩니다.

B1의 마지막 대화 카드는 FE에서 추가하며 `total`에 포함되지 않습니다.
목록을 모두 불러온 뒤 `next_offset=null`일 때 마무리 카드로 이동합니다.
상세한 필드 매핑, 기존 FE 수정 위치와 버튼 연결은
[B1 시그널 목록 FE 인계](signal-briefing-fe-handoff.md)를 참고합니다.

## 시그널 일별 자동 측정과 비교

새 시그널을 등록하면 기본 일정을 함께 저장합니다. 기존 시그널도 새 Backend가 시작될 때
일정이 없는 경우 다음 한국시간 자정부터 일정을 추가합니다. 일별 실행은 기존
`SignalService.measure → InvestigationData.load → measure_definition` 경로를 사용합니다.
등록된 SQL, Source 범위, 모집단과 지표를 그대로 유지하며 실행마다 해당 기간의 최신 데이터를 읽습니다.
LLM을 다시 호출해 정의를 만들지 않습니다.

| Method | 경로 | 설명 | 응답 |
| --- | --- | --- | --- |
| GET | `/api/signals/{signal_id}/schedule` | 일별 일정, 다음 실행 시각, 시그널 상태 조회 | `DailySchedule` |
| PUT | `/api/signals/{signal_id}/schedule` | `enabled` 설정, 선택적으로 `next_run_at` 변경 | `DailySchedule` |
| GET | `/api/signals/{signal_id}/daily-results` | 일별 실행과 기간별 최신 측정, 누락 기간 수 조회 | `DailyResults` |
| GET | `/api/signals/{signal_id}/comparison` | 기본 최신 일별 두 기간 또는 지정한 두 측정 비교 | `MeasurementComparison` |

일정은 `interval=daily`, `timezone=Asia/Seoul`로 고정합니다. 매일 00:00에 직전 하루의
`[start_at, end_at)`를 측정하며 API 응답의 시각은 UTC입니다. 예를 들어 한국시간
9월 11일 00:00 실행은 9월 10일 00:00 이상, 9월 11일 00:00 미만의 데이터입니다.
실행 확인은 기본 60초 간격이므로 자정 이후 다음 poll에 실행합니다.

```json
{"enabled": true, "next_run_at": "2026-09-06T00:00:00+09:00"}
```

`next_run_at`은 timezone이 있는 한국시간 자정이어야 합니다. 과거 자정으로 설정하면
해당 자정을 끝으로 하는 하루부터 순차 보충하며, 아직 끝나지 않은 기간은 실행하지 않습니다.
누락 기간은 poll마다 시그널당 한 기간씩 처리합니다. `enabled=false` 또는 시그널의
`status=paused/archived`이면 자동 실행을 중지하며, 재개 시 기존 커서부터 누락을 보충합니다.
누락 보충을 원하지 않으면 다음 미래 자정으로 `next_run_at`을 지정하세요.
이미 시작한 측정은 중지 이후에도 완료될 수 있습니다. 실행 중 일정 변경은 409입니다.

`daily-results`는 최신순이며 `limit`은 기본 30, 최대 100입니다. 다음 페이지는 응답의
`next_before`를 `before`에 그대로 전달합니다. `before`는 해당 경계를 포함하지 않습니다.
`pending_days`는 다음 실행 시각부터 현재까지 닫힌 기간 수이며 일시 중지 여부와 무관합니다.
`items[].status`는 자동 실행의 결과(`running/success/unavailable`), `measurement`는 해당 기간의
최신 성공 측정을 우선한 값입니다. 수동으로 같은 기간을 재측정하면 실행 결과는 보존하면서
`measurement`에 복구된 값이 반영됩니다. `running`은 재시작 후 재처리 중인 실행일 수도 있습니다.
실패 기간은 null 값과 공개 사유로 저장하고 다음 날의 실행을 계속합니다. 실패/지연 적재를
복구하려면 기존 `POST /measurements`로 그 기간을 재측정합니다.

`comparison`에 `baseline_measurement_id`, `target_measurement_id`를 함께 지정하면
해당 시그널의 두 측정을 비교합니다. 미지정 시 최신 일별 두 기간을 사용하므로 등록 당시의
다일 최초 측정은 섞이지 않습니다. 정의 지문, `pipeline_version`, Source 범위/버전,
기간 길이, 중첩 여부, 측정 상태와 지표 단위를 검사합니다. 비교 불가 시 `metrics=[]`와
`comparison_limitations`를 반환합니다. 정상 비교 시 각 지표의 기준값, 현재값, 절대 변화와 상대 변화율을 제공합니다.
`unit=percent` 또는 `%`인 비율 지표의 `absolute_change` 단위는 `percentage_points`, `relative_change_percent`는
`(현재-기준)/abs(기준)*100`입니다. 기준값 0이면 상대 변화율은 null입니다.
시그널/측정 ID가 없으면 404, 한쪽 측정 ID만 지정하거나 일정을 잘못 지정하면 422입니다.
모든 정상 응답은 HTTP 200입니다.

운영 설정은 `SIGNAL_SCHEDULER_ENABLED=true`, `SIGNAL_SCHEDULER_POLL_SECONDS=60`입니다.
Backend 프로세스가 실행 중이어야 주기 측정이 동작합니다. 종료 중 누락은 재시작 시 보충합니다.
일정과 실행 결과는 기존 `signals.sqlite3`에 저장하며 시그널별 파일 잠금으로 같은 로컬 DB를
공유하는 여러 worker의 중복 실행을 막습니다. 로컬 POSIX 파일 시스템(macOS/Linux) 기준이며
여러 호스트나 네트워크 파일 시스템 운영에는 외부 작업 큐/잠금 구성이 별도로 필요합니다.
