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
| GET | `/api/runs/{run_id}/events` | Run 이벤트 SSE 스트림. `Last-Event-ID` 헤더로 재접속 커서 지정 | SSE |
| GET | `/api/runs/{run_id}/presentation` | Canonical Run Event 에서 재계산한 Presentation Intent 목록 조회 | `PresentationReplay` |
| GET | `/api/runs/{run_id}/customers/{customer_id}/journey` | 완료된 Run 의 고객 Journey 조회 | `CustomerJourneyResult` |
| GET | `/api/runs/{run_id}/evidence/{evidence_id}` | 완료된 Run 의 마스킹 Evidence 조회 | `EvidenceResult` |

`mode`는 `auto`, `fixture`, `gemini`, `bedrock`을 지원합니다.
`mode` 생략 시 서버의 `AGENT_MODE`를 사용하며 기본값은 `bedrock`입니다.
`auto`는 유효한 Bedrock 토큰 → Gemini 키 → fixture 순서로 선택합니다.
`mode=bedrock`은 `AWS_BEARER_TOKEN_BEDROCK`, `AWS_REGION`(기본 `us-east-1`),
`BEDROCK_MODEL`(기본 `us.anthropic.claude-opus-4-6-v1`)로 Converse API를 호출합니다.
investigator는 `BEDROCK_INVESTIGATOR_MODEL`(기본 `us.anthropic.claude-sonnet-4-6`)을
사용하며, coordinator, verifier, reporter는 `BEDROCK_MODEL`을 사용합니다.
`mode=gemini`와 `mode=bedrock`은 총괄, 가설별 조사, 독립 검증과 보고 역할을 실행합니다.
Bedrock 호출 실패 시 다른 모델이나 fixture로 자동 전환하지 않습니다.
상태 응답과 SSE의 `agent_mode`에 `bedrock`이 표시되며, 저장 Artifact의
`versions.model_version`에 기본 Bedrock 모델 ID, `versions.agent_mode`에 실행 provider를 기록합니다.
역할별 호출 모델은 관측 metadata의 `model`에 기록합니다.
기존 Artifact는 새 필드 없이도 읽을 수 있습니다. 요청 필드와
SSE, `customer_signal` 보고서 스키마는 유지합니다. 진행 중 실행은 선택한 공간의
스냅샷을 사용하며, 추가된 데이터는 같은 질문과 기간으로 새 Run을 생성해 분석합니다.
사용자 결정으로 전체 실행 시간, 역할별 호출 횟수와 재조사 라운드 제한을 해제했습니다.
완료 시각을 15분 이내로 보장하지 않으며, 확인하지 못한 후보와 중단 사유는 `limitations`에 남깁니다.
위험 점수는 산정하지 않으므로 `ranked_customers`는 비어 있습니다. 대표 고객 식별자는
상태 응답의 `facts` 중 `payload.kind=get_customer_journey`의 `payload.customer_id`를 사용합니다.
기존 고객 Journey와 Evidence 조회 URL은 그대로 사용할 수 있습니다.
새 분석의 상세 조회는 완료된 Run의 Fact에 보관한 여정과 근거를 반환하므로,
추가 데이터의 마스킹 고객 ID도 조회할 수 있고 실행 이후 데이터 변경의 영향을 받지 않습니다.

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
에이전트의 지표 계산·후보 제안은 등록 행위가 아닙니다. 완료된 분석의 독립 검증 후보를 선택하거나,
사용자가 정의와 기간을 직접 보내 서버 측정 후 등록합니다. 하나의 조사 태스크는 여러 패턴 후보를 가질 수 있습니다.

| Method | 경로 | 설명 | 응답 |
| --- | --- | --- | --- |
| GET | `/api/signal-proposals` | 완료 분석의 후보 모아보기, 선택적 `run_id` 필터 | `ProposalList` |
| GET | `/api/signal-proposals/{proposal_id}` | 분석 경로 없이 후보 상세 조회 | `Proposal` |
| GET | `/api/runs/{run_id}/signal-proposals` | 완료된 분석의 등록 가능 후보 | `ProposalList` |
| GET | `/api/runs/{run_id}/signal-proposals/{proposal_id}` | 후보 정의·최초 측정·근거 | `Proposal` |
| POST | `/api/signals` | `proposal_id` 선택 등록 또는 `title`, `description`, `definition`, `start_at`, `end_at` 직접 등록 | `Signal` |
| GET | `/api/signals` | 등록된 시그널 목록 | `SignalList` |
| GET | `/api/signals/{signal_id}` | 고정 정의와 상태 조회 | `Signal` |
| PATCH | `/api/signals/{signal_id}` | `status`: active/paused/archived | `Signal` |
| POST | `/api/signals/{signal_id}/measurements` | `start_at`, `end_at` 지정 재측정 | `Measurement` |
| GET | `/api/signals/{signal_id}/measurements` | 전체 이력·기간별 최신 성공 값·비교 가능 여부 | `MeasurementHistory` |

등록과 재측정은 HTTP 200을 반환합니다. 없는 시그널/후보는 404, 완료되지 않은 Run의 후보 조회·등록은 409,
잘못된 요청은 422입니다. 직접 등록 시 최초 측정이 불가능해도 422이며 등록을 저장하지 않습니다.
직접 등록의 출처는 `origin=user_defined`, `proposal_id=null`입니다. 기존 등록은 `origin=analysis`입니다.
같은 정의를 재등록하면 기존 ID와 출처를 유지합니다. 수동 재측정 데이터가 부족하거나 SQL이 실패하면 HTTP 200의 `status=unavailable`로 이력을
남깁니다. `values[].value=null`을 0으로 표시하면 안 됩니다. `reason`에는 공개 가능한 실패 사유만 포함합니다.
같은 정의/관측 기간/데이터 스냅샷의 재측정은 기존 측정 ID를 반환합니다. 데이터가 변경되면 새 측정으로 보존합니다.
`latest_by_window`는 기간별 최신 성공 값을 우선하며, 실패 이력은 `items`에 남습니다.
관측 기간 길이·정의·Source 범위/버전이 다르거나 기간이 겹치면 비교 불가 사유를 반환합니다.
자세한 연결 순서와 수치 해석은 [시그널 FE 인계](signal-fe-handoff.md)를 참고합니다.

등록·재측정 성공 응답 헤더 `X-Langfuse-Trace-Id`는 해당 작업을 기록한 trace ID입니다.
후보 선택 등록은 **원래 분석 trace**, 직접 등록·수동 재측정은 **이번 API 작업 trace**를 반환합니다.
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
