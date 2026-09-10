# Bedrock 연결 검증

검증일: 2026-09-10. 루트 `.env`의 `AWS_BEARER_TOKEN_BEDROCK`을 사용했다.
토큰 원문과 AWS 오류 본문은 기록하지 않았다.

## 선택한 모델

- 리전: `us-east-1`
- 모델: `us.anthropic.claude-opus-4-6-v1` — Claude Opus 4.6
- API: Bedrock Runtime Converse (`langchain-aws`의 `ChatBedrockConverse`)

확인한 상위 후보 중 실제 응답한 모델을 기준으로 선택했다. 전체 모델의 품질을
벤치마크한 결과는 아니며, 다른 계정·리전·권한에서는 결과가 달라질 수 있다.

## 실제 호출 결과

| 모델 | 호출한 inference profile | 결과 |
| --- | --- | --- |
| Claude Fable 5.1 | `us.`, `global.` | HTTP 403 AccessDeniedException |
| Claude Fable 5 | `us.`, `global.` | HTTP 403 AccessDeniedException |
| Claude Opus 4.8 | `us.`, `global.` | HTTP 403 AccessDeniedException |
| Claude Opus 4.7 | `us.`, `global.` | HTTP 403 AccessDeniedException |
| GPT-5.6 Sol | `us.`, `global.` | HTTP 403 AccessDeniedException |
| Claude Opus 4.6 | `us.anthropic.claude-opus-4-6-v1` | HTTP 200, 텍스트 응답 |
| Claude Opus 4.6 | `global.anthropic.claude-opus-4-6-v1` | HTTP 200, 텍스트 응답 |
| Claude Sonnet 4.6 | `us.anthropic.claude-sonnet-4-6` | HTTP 200, 텍스트 응답 |

Claude Mythos 5.1의 global profile은 HTTP 400으로 응답하여 후보에서 제외했다.
403만으로 구독·IAM·모델 접근 권한 중 어느 설정이 원인인지 단정하지 않았다.

텍스트 응답 이후 새 `BedrockInvestigationModel`로 합성 입력을 전달했다.
Opus 4.6이 `finish(document=...)` 도구를 호출했고 `Narrative` 스키마 검증을 통과했다.

## 전체 API Run 검증

새 Backend 프로세스를 `uv run --env-file <root>/.env --project backend uvicorn ...`으로
시작하고, 별도 임시 DB에 생성한 합성 `search_feedback` 데이터로 실행했다.

- Run ID: `7e24571e-0989-43c7-a04f-661aeed10f6e`
- 결과: `completed`, 상태 API의 `agent_mode=bedrock`
- 실행: 약 367초, 역할 6회, 데이터 질의 64개
- 저장: Artifact 조회 HTTP 200, Fact 23개, 보고서 생성
- Artifact의 `versions.model_version`: `us.anthropic.claude-opus-4-6-v1`
- 보고서는 확인하지 못한 범위 등 limitations를 포함한다. 이 검증은 연결·실행 계약 검증이며 분석 정확도 벤치마크가 아니다.

서버 재시작 후 provider를 잃지 않도록 `versions.agent_mode`도 저장한다.
이 필드가 없는 기존 Artifact는 기존 복원 규칙을 사용한다.

## Langfuse 적재 확인

루트 `.env`에 설정된 Langfuse의 Trace API를 조회해 HTTP 200을 확인했다.

- Trace: `7e24571e098943c7a04f661aeed10f6e`, 이름 `customer_signal.turn`
- 시각: 2026-09-10 13:34:38 KST
- Session ID: 공개 API Run ID와 동일
- AGENT 7개(부모 1개와 역할 6개), GENERATION 40개, TOOL 109개
- GENERATION 40개 모두 모델 `us.anthropic.claude-opus-4-6-v1`, `provider=bedrock`
- Stage: coordinator 4회, investigator 24회, verifier 8회, reporter 4회
- 모델 호출 40개 모두 역할 AGENT 아래에 연결됐으며 ERROR observation은 0개

자격 증명과 모델 입력·출력 본문은 검증 출력에 포함하지 않았다.

## 자동 검증

- `uv run --project backend pytest -c backend/pyproject.toml backend/tests -q`: 803개 통과.
- 이후 추가한 provider 복원 변경은 Bedrock·Artifact·generic runtime 테스트 36개로 검증했다.
- `npm --prefix frontend test -- --run`: 96개 통과.
- Artifact provider 디코딩 추가 후 RunClient 테스트 43개와 TypeScript 검사를 통과했다.
- Launcher의 환경변수 격리와 깨끗한 subprocess의 LangSmith 활성화 테스트를 통과했다.
- 최종 어댑터 코드로 합성 `finish` 도구 호출을 다시 실행해 스키마 검증을 통과했다.

## 실행

루트 `.env`에 토큰과 다음 설정을 두고 `make dev-bedrock`을 실행한다.
`make dev`와 인자 없는 `scripts/dev.sh`도 기본적으로 Bedrock을 선택한다.
Backend Settings 기본값과 루트 `.env`의 `AGENT_MODE`는 `bedrock`이다.

```dotenv
AWS_REGION=us-east-1
BEDROCK_MODEL=us.anthropic.claude-opus-4-6-v1
```

`POST /api/runs?mode=bedrock`으로 명시적으로 선택할 수 있다.
현재 어댑터는 기존 조사 역할과 데이터 도구·결과 검증을 재사용한다.
모델 실패 시 Gemini나 fixture로 자동 전환하지 않는다.

## 공식 자료

- [AWS Bedrock API Key 사용법](https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-use.html)
- [Claude Opus 4.6 모델과 inference profile](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-4-6.html)
- [Claude Opus 4.8 모델](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-4-8.html)
- [Claude Fable 5.1 모델](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-fable-5-1.html)
- [GPT-5.6 Sol 모델](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-56-sol.html)
