# 앱과 Langfuse 로컬 실행

Next.js, FastAPI, Langfuse와 저장소를 하나의 Docker Compose 프로젝트로 실행합니다.
프로젝트 이름은 `catch-catch-local`이며 다른 프로젝트의 컨테이너와 볼륨을 재사용하지 않습니다.
외부 AWS 리소스를 생성하지 않습니다.

## 준비와 실행

Docker Engine, Docker Compose 2.30 이상, Python 3, uv가 필요합니다.
Compose의 `env_file.format: raw`를 사용하므로 오래된 Compose는 사용할 수 없습니다.
Langfuse 공식 VM 권장은 4코어, 16GiB 메모리이며, 이 구성에는 로컬 데모용
ClickHouse 1GiB 제한과 작은 백그라운드 작업 풀을 적용했습니다.
작은 Docker VM에서 다른 무거운 서비스를 함께 실행하면 메모리가 부족할 수 있습니다.

저장소 루트에서 실행합니다.

```bash
make compose-init
make compose-up
make compose-verify
```

`compose-init`은 기존 환경 파일을 다음 순서로 선택합니다.

1. `ENV_FILE`로 지정한 파일
2. 현재 저장소의 `.env`, `backend/.env`
3. Git 공통 디렉터리의 원본 checkout에 있는 `.env`, `backend/.env`

선택한 파일이 없으면 현재 실행 환경에서 모델 관련 값만 가져옵니다.
모델 키와 명시적인 실행 모드가 없으면 `fixture`로 실행합니다.
명시한 `bedrock` 또는 `gemini` 모드의 키가 없으면 초기화를 중단합니다.
기존 환경 파일은 수정하거나 shell에서 `source`하지 않습니다.

```bash
ENV_FILE=/absolute/path/to/demo.env make compose-init
make compose-up
python3 scripts/compose.py verify --mode bedrock
```

실제 모델 검증 명령은 합성 질문 한 건을 해당 provider에 전달합니다.
기본 `make compose-verify`는 외부 모델을 호출하지 않습니다.
`BEDROCK_INVESTIGATOR_MODEL`은 조사 역할의 모델이며 Compose Backend에도 전달합니다.
현재 기본값은 `us.anthropic.claude-sonnet-4-6`입니다.
조율과 보고 역할은 `BEDROCK_MODEL`을 사용합니다.
검증 역할도 기본적으로 같은 모델을 사용하며, 선택 설정인 `BEDROCK_VERIFIER_MODEL`로
별도 지정할 수 있습니다. Compose는 이 설정을 Backend에만 전달합니다.
모델 오류 뒤 서버 대체 요약으로 실행이 종료되면 trace 적재가 성공했더라도
실제 모델 검증은 종료 코드 1을 반환합니다. 결과의 `model_execution`과
`provider_error_types`에서 부분 실행 여부와 오류 종류를 확인합니다.

## 접속 주소

| 주소 | 용도 |
| --- | --- |
| `http://localhost:3200` | 현재 프로토타입 화면 |
| `http://localhost:3200/legacy` | 실제 Backend에 연결된 분석 화면 |
| `http://localhost:3200/backend/docs` | Swagger |
| `http://localhost:3200/backend/health` | Backend 상태 |
| `http://localhost:3210` | 새 Langfuse |
| `http://localhost:3290` | Langfuse 미디어 저장소 |

포트는 기본적으로 `127.0.0.1`에만 바인딩합니다.
현재 저장소의 첫 화면은 정적 시연 데이터를 사용하며 실제 Run을 만들지 않습니다.
실제 분석과 Langfuse 적재를 보려면 `/legacy` 화면을 사용합니다.
앱의 API, SSE, 다운로드 요청은 `/backend` 프록시를 거치므로 브라우저의 접속 주소와 같습니다.
Langfuse 로그인 정보는 `.local/compose/langfuse-login.txt`에서 로컬로 확인합니다.
이 파일의 비밀번호나 API 키를 로그, 문서, 채팅에 복사하면 안 됩니다.

포트나 URL을 변경할 때는 `.local/compose/stack.env`의 `*_PORT`, `*_URL` 값을 함께 수정하고
`make compose-up`을 다시 실행합니다. 프론트엔드의 API URL은 상대 경로여서 별도 변경이 필요 없습니다.

## 환경값과 데이터

- `.local/compose/stack.env`: Langfuse 저장소 비밀번호, 프로젝트 키, 접속 주소
- `.local/compose/backend.env`: 선택한 모델 설정, LangSmith 설정, 새 Langfuse의 연결 설정
- `.local/compose/langfuse-login.txt`: 초기 관리자 로그인 정보

위 파일들은 Git에서 제외하며 권한은 `600`, 상위 디렉터리는 `700`입니다.
`compose-init`을 다시 실행해도 Langfuse 비밀번호와 프로젝트 키를 유지합니다.
Backend 환경 파일은 선택한 원본 환경 파일을 다시 읽어 갱신합니다.
Langfuse 연결 정보는 항상 이 Compose 프로젝트에 맞춰 덮어씁니다.

Docker build context에는 소스, lockfile, 지정한 합성 데이터만 포함합니다.
실제 `.env`, 로컬 보고서, 기존 데이터베이스를 이미지에 복사하지 않습니다.
Frontend에는 모델 키, LangSmith 값, Langfuse 키를 전달하지 않습니다.
선택한 환경 파일은 `uv run --env-file`로 Python 시작 전에 읽으며,
상속된 `LANGSMITH_*`, `LANGCHAIN_*` 값보다 우선합니다.
컨테이너에서도 Docker가 환경값을 주입한 뒤 Python을 시작합니다.

앱은 `/app/data` 볼륨에 DuckDB, SQLite journal, 보고서와 온보딩 소스를 보존합니다.
첫 기동 때 합성 DuckDB를 생성하고, 이미지에 포함된 해커톤 합성 소스 중 없는 항목만 복사합니다.
Langfuse의 PostgreSQL, ClickHouse, Redis, MinIO는 각각 별도 named volume을 사용합니다.
활성 Run은 메모리에 있으므로 Backend는 worker 1개로 실행합니다.
분석 중 Backend를 재시작하면 진행 중 실행을 그대로 이어갈 수 있다는 보장은 없습니다.

Langfuse Web과 Worker는 기존 연동에 사용하던 서버 v3 이미지를 digest로 고정했습니다.
Python SDK의 버전 번호와 Langfuse 서버의 버전 번호는 서로 다릅니다.
v4 업그레이드는 별도의 데이터 마이그레이션과 호환성 검증이 필요합니다.

## 검증과 종료

`make compose-verify`는 다음 항목을 실제 HTTP 요청으로 확인합니다.

- 앱, Backend, Langfuse 상태와 Swagger의 실제 OpenAPI URL
- 합성 질문 실행 완료, Fact 생성, SSE 이벤트와 `Last-Event-ID` 재연결
- JSON과 Markdown 보고서 다운로드
- 새 Run ID와 일치하는 Langfuse trace ID, 생성 시각, `customer_signal.turn` 이름
- 부모 workflow, 분석 Tool의 연결과 `stage`, `run_id` metadata
- 실제 모델 모드에서 GENERATION span의 이름, provider, stage와 부모 연결
- Frontend 컨테이너의 비밀값 격리

Fixture가 매우 빨리 끝나면 SSE 수신 시점에 이미 완료됐을 수 있습니다.
검증 결과의 `sse_observed_while_active`가 실제 진행 중 이벤트 수신 여부입니다.
Fixture에는 LLM GENERATION이 없어도 정상이며, 실제 모델 호출을 검증했다는 뜻은 아닙니다.
검증 결과는 입력 원문과 provider 응답을 제외한 공개 metadata만
`.local/compose/verification-<run_id>.json`에 저장합니다.

```bash
make compose-ps
make compose-down
make compose-up

# 재시작 후 이전 실행과 trace를 다시 확인합니다.
uv run --no-env-file --project backend python scripts/verify-compose.py --run-id <run_id>
```

`compose-down`은 컨테이너와 네트워크를 내리고 볼륨을 유지합니다.
`docker compose down -v`는 데이터를 삭제하므로 일반 종료에 사용하면 안 됩니다.
이 로컬 Compose는 TLS, 고가용성, 자동 백업을 구성하지 않습니다.
AWS에 올릴 때는 접속 제어, TLS와 EBS 보존 정책을 별도로 설정해야 합니다.

## Docker Desktop 인증 도우미가 멈추는 경우

공개 이미지 다운로드가 `docker-credential-desktop`에서 멈추면 다음 명령을 사용합니다.

```bash
make compose-up COMPOSE_FLAGS=--anonymous-pulls
```

이 옵션은 현재 Docker 엔진을 유지하면서 해당 명령에만 별도의 공개 이미지용 설정을 적용합니다.
기존 `~/.docker/config.json`과 로그인 정보는 수정하지 않습니다.
인증 없는 Docker Hub 다운로드 제한이 적용될 수 있습니다.

## 참고

- [Langfuse 공식 Compose 배포](https://langfuse.com/self-hosting/deployment/docker-compose)
- [Langfuse 초기 사용자와 프로젝트 자동 생성](https://langfuse.com/self-hosting/administration/headless-initialization)
