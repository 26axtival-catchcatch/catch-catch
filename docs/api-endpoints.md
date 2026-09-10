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
`mode=gemini`와 `mode=bedrock`은 총괄, 가설별 조사, 독립 검증과 보고 역할을 실행합니다.
Bedrock 호출 실패 시 다른 모델이나 fixture로 자동 전환하지 않습니다.
상태 응답과 SSE의 `agent_mode`에 `bedrock`이 표시되며, 저장 Artifact의
`versions.model_version`에 실제 Bedrock 모델 ID, `versions.agent_mode`에 실행 provider를 기록합니다.
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
