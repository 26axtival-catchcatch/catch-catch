# 앱과 Langfuse 통합 Compose 검증

2026-09-10에 Apple Silicon Mac의 Docker Desktop에서 검증했습니다.
Docker Engine은 `27.5.1`, Compose는 `2.32.4`이며 Docker VM에 약 8GiB가 할당되어 있습니다.
AWS 리소스는 생성하지 않았습니다.

## 검증 결과

| 항목 | 결과 |
| --- | --- |
| Backend 이미지 | Python 3.12, uv lockfile을 사용한 빌드 성공 |
| Frontend 이미지 | Next.js production build, TypeScript 검사 성공 |
| 통합 스택 | 컨테이너 9개 실행, 상태 검사 대상 8개 healthy |
| 환경값 격리 | 초기화, 재실행, 파일 권한, 환경 우선순위 테스트 5개 통과 |
| Langfuse 회귀 테스트 | 11개 통과 |
| LangSmith import 시점 | 별도 환경 파일을 읽은 새 subprocess에서 `tracing_is_enabled() == True` 확인 |
| Swagger | `/backend/docs`의 스키마 URL과 `/backend/openapi.json` 응답 확인 |
| 합성 분석 | 부정 피드백 고객 6명, Fact 3개, 실행 완료 |
| SSE | 실행 중 이벤트 수신, 이벤트 18개, 재연결 확인 |
| 다운로드 | JSON, Markdown 응답 확인 |
| Langfuse | workflow 1개와 하위 Tool span 3개 적재 확인 |
| 데이터 보존 | 전체 `down`과 `up` 이후 같은 Run, 보고서, trace 조회 성공 |
| 브라우저 | `/legacy`에서 Run 생성 HTTP 202, 진행 상태, 최종 6명 결과 확인 |
| 정적 검사 | 변경 Python 파일 Ruff, `git diff --check` 통과 |

## Bedrock 실호출 검증

사용자가 루트 `.env`를 설정한 뒤 `compose-init`으로 Backend 실행 환경을 갱신하고
Backend 컨테이너를 재생성했습니다. 새 Langfuse의 프로젝트와 키는 유지했습니다.

```bash
python3 scripts/compose.py verify --mode bedrock
```

- Run ID: `cbdecb6d-416a-4cec-aff5-4f0228d0e7a5`
- Trace ID: `cbdecb6d416a4cecaff54f0228d0e7a5`
- 생성 시각: `2026-09-10T07:18:04.796Z`, 한국 시각 16:18:04
- 검증 완료 시각: `2026-09-10T07:21:43.947Z`
- 실행 모드: `bedrock`, 리전: `us-east-1`
- 모델: `us.anthropic.claude-opus-4-6-v1`
- 실행 결과: `completed`, Fact 3개, SSE 이벤트 18개
- 관측 개수: `AGENT` 7개, `GENERATION` 44개(오류 2개 포함), `TOOL` 105개
- 모델 역할: `coordinator`, `investigator`, `verifier`, `reporter`
- 모델 metadata: `provider=bedrock`, 역할별 stage, 같은 Run ID
- 검증 항목: workflow 부모 연결, 실행 중 SSE, 재연결, JSON과 Markdown 다운로드, Frontend 비밀값 격리

[Bedrock trace 열기](http://localhost:3210/project/catch-catch-local/traces/cbdecb6d416a4cecaff54f0228d0e7a5)

같은 Run ID로 재조회해 모델명과 역할 metadata를 추가 기록했습니다.
재조회는 모델을 다시 호출하지 않습니다. Backend는 Bedrock 모드로 실행 중입니다.

**Bedrock 연결과 trace 적재는 통과했지만, 분석 전체가 오류 없이 완료된 것은 아닙니다.**
`verifier`와 `reporter`의 모델 호출이 각각 `InternalServerException`으로 실패했습니다.
앱은 확보한 후보와 서버 대체 요약으로 `completed` 상태를 반환했습니다.
검증 스크립트는 이 경우 `trace_ingestion=passed`, `model_execution=partial`을 기록하고
종료 코드 1을 반환하도록 보완했습니다. 원본 provider 오류 메시지는 기록하지 않습니다.

## Fixture trace와 재기동 검증

API 검증은 다음 실행을 새로 만들고 Langfuse의 공개 API로 결과를 조회했습니다.

- Run ID: `48b6c9ab-c752-4a0c-883a-f180947dc3b6`
- Trace ID: `48b6c9abc7524a0c883af180947dc3b6`
- 생성 시각: `2026-09-10T06:53:47.947Z`, 한국 시각 15:53:47
- Trace 이름: `customer_signal.turn`
- 부모 workflow: `AGENT` 1개, provider `server`
- 자식 Tool: `catalog_sources`, `profile_events`, `aggregate_events`
- Tool metadata: stage `tool`, 원래 Run ID와 일치하는 `run_id`
- SSE 진행 중 수신: `true`

[이 trace 열기](http://localhost:3210/project/catch-catch-local/traces/48b6c9abc7524a0c883af180947dc3b6)

스택 전체를 내렸다가 다시 올린 뒤 같은 Run의 snapshot, SSE 재연결,
다운로드와 trace를 재검증했습니다.
브라우저에서 별도로 생성한 Run `1a204d88-da7c-49e9-ac07-ddc87cd26a5d`도
완료됐으며 동일한 workflow 1개와 Tool span 3개를 확인했습니다.

기존 SDK는 명시적인 trace ID를 사용할 때 기록하지 않는 원격 부모 ID를 만들 수 있습니다.
검증은 부모 ID가 무조건 비어 있는지 확인하는 대신, 기록된 span 안에서 workflow가
유일한 최상위 span이고 Tool들이 해당 workflow 아래에 연결되는지 확인합니다.

## 확인 범위

후속 작업에서 `feature/aws`에 `origin/main`의 `f6aca41`을 반영했습니다.
루트 `.env`의 `BEDROCK_INVESTIGATOR_MODEL=us.anthropic.claude-sonnet-4-6`을
Compose Backend에 전달하고 이미지를 다시 빌드했습니다.
실행 중인 컨테이너에서 조사 역할은 Sonnet 4.6, 조율, 검증, 보고 역할은
기존 Opus 4.6으로 선택되는 것을 확인했습니다.
관련 Backend 테스트 37개와 Compose 환경 테스트 5개가 통과했습니다.
이 모델 분리 설정으로 추가 실호출은 수행하지 않았으며, 위 Bedrock trace는 변경 전 기록입니다.

초기에는 `fixture`로 앱과 저장소를 검증했고, 루트 환경 파일을 설정한 뒤
Bedrock 실제 호출과 LLM GENERATION 적재까지 추가 검증했습니다.
Bedrock의 두 역할 호출이 실패해 최종 분석은 부분 결과입니다.
Gemini는 호출하지 않았습니다. 검증 명령은 [실행 가이드](../local-compose.md)에 있습니다.
LangSmith 검사는 import 전 환경 초기화에 대한 검사이며, LangSmith 서버의 실제 적재 검사는 아닙니다.
현재 실제 실행 환경의 LangSmith tracing은 비활성 상태이며 Langfuse 적재는 활성 상태입니다.

첫 화면 `/`은 기존 정적 프로토타입입니다. 실제 Backend 연결은 `/legacy`에 있습니다.
배포 작업에서 두 화면의 기존 역할은 변경하지 않았습니다.

검증 후 통합 스택의 메모리 사용량은 약 1.8GiB였습니다.
짧은 Fixture 실행의 관측값이므로 장시간 실행이나 실제 모델 분석의 용량 보장은 아닙니다.

## 기존 서비스 상태

사용자 승인에 따라 기존 Langfuse와 Supabase를 포함한 컨테이너 17개를 중지했습니다.
데이터 볼륨은 유지했으며 새 통합 스택을 실행 상태로 남겼습니다.
기존 컨테이너 목록은 Git에서 제외된 `.local/compose/previous-containers.json`에 있습니다.

기존 환경으로 돌아갈 때는 새 스택을 내린 뒤 저장한 컨테이너를 시작합니다.

```bash
make compose-down
python3 - <<'PY'
import json
from pathlib import Path
import subprocess

names = json.loads(Path('.local/compose/previous-containers.json').read_text())
if names:
    subprocess.run(['docker', 'start', *names], check=True)
PY
```
