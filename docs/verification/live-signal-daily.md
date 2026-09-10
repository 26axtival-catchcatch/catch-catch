# 일별 시그널 자동 측정 API 라이브 검증

검증일: 2026-09-10. SDD 설계 → TDD → 코드 리뷰 → 실제 Backend 검증을 수행했습니다.
구현 범위는 API와 자동 측정이며 화면과 LLM 정기 리포트 생성은 포함하지 않습니다.

## 구현과 실행 설정

신규 등록과 기존 시그널에 SQLite 일별 일정을 연결했습니다. 매일 한국시간 00:00에
직전 하루를 등록된 SQL/Source/모집단/지표로 측정합니다. 실제 처리 시각은 자정 이후
다음 worker poll이며 기본 간격은 60초입니다. 같은 SignalService와 InvestigationData,
measure_definition을 사용하고 누락 기간을 순차 보충합니다.

현재 Backend: http://127.0.0.1:8000, Swagger: http://127.0.0.1:8000/docs.
`ONBOARDED_SOURCES_DIR=data/investigation-demo-sources`, 기존 `data/run-artifacts` 저장소,
`SIGNAL_SCHEDULER_ENABLED=true`, `SIGNAL_SCHEDULER_POLL_SECONDS=60`으로 실행했습니다.
선택한 `.env`를 uv 프로세스 실행에 전달하기 전 inherited LANGSMITH/LANGCHAIN/LANGFUSE
환경을 제거했습니다. 프론트엔드에는 환경 값을 전달하지 않았습니다.

기존 활성 시그널 2개에 9월 8일·9일의 일별 결과를 자동 적재했습니다.
- `signal-67575879e224408abbe4bc9d2287d6b6`
- `signal-a0a29924499e490685af65c5e7dd5d5f`

각각 대상 고객 17/26명 → 17/25명, 비율 65.3846% → 68%, +2.6154%p로 비교됩니다.
기존 paused 시그널은 일별 실행 0건을 유지합니다. 다음 실행은 두 활성 시그널 모두
**2026-09-11 00:00 Asia/Seoul** (`2026-09-10T15:00:00Z`)입니다.
최종 코드 반영 후 Backend를 재시작하고 4개 실행, 일정과 비교 결과 보존을 재확인했습니다.

## 독립 라이브 재현

```sh
uv run --project backend python scripts/verify-signal-daily-live.py
```

이 스크립트는 별도 8001번 포트와 격리된 Artifact 디렉터리에서 실제 uvicorn을 시작하고
검증 후 종료합니다. 승인된 합성 Source 파일을 실제 어댑터/SQL로 읽으며 모의 HTTP나
모의 worker를 사용하지 않습니다. 정기 측정은 고정 SQL 경로이므로 LLM 호출은 0회입니다.

최종 검증 시각: `2026-09-10T09:16:44.954847+00:00`.
검증 시그널: `signal-ff6555a23e4649838ebdd34c56f4c0a2`.

9월 4일·5일·6일의 3개 완료된 하루를 일정 backfill로 자동 측정했습니다.
대상 고객 수는 18/26 → 17/26 → 17/26, 첫 이틀 차이는 -1명 및 -3.8462%p입니다.
같은 날 수동 재측정은 자동 측정과 같은 값·측정 ID를 반환했습니다.
일정 중지, 페이지네이션, Swagger, 프로세스 재시작 후 보존, 과거 일정 재처리의
실행/측정 중복 방지를 확인했습니다.

## 관측

Langfuse MCP에서 자동 실행 trace `19bbac265ddc4eb092bddf46078a1a13`를 조회했습니다.
`customer_signal.signal` SPAN의 `operation=measurement`, signal_id와 measurement_id를
실제 API/DB 결과와 대조했습니다. 부모 observation도 존재합니다.
재측정이 기존 측정을 재사용하면 measurement.trace_id는 최초 저장 trace를 유지합니다.
일별 실행 자체의 trace는 execution_id에서 하이픈을 제거한 ID로 찾을 수 있습니다.

## 자동 검증

- `uv run --project backend pytest -c backend/pyproject.toml backend/tests -q`: **903 passed** (557.66초).
- 최종 버전/퍼센트 단위 보완 후 `test_signal_schedule_api.py`, `test_signal_scheduling.py`, `test_signals.py`: **56 passed**.
- 변경 Python 파일 Ruff, `git diff --check`: 통과.
- 기존 Starlette/httpx deprecation 경고 1개. 기능 실패 없음.
- KST 경계, 미래 미실행, 누락 보충, 상태 중지/재개, 독립 worker 경합,
  강제 종료 subprocess의 잠금 해제, 측정 저장 후 완료 전 크래시, 실패 후 다음 날,
  pipeline 버전 변경, 0 기준 상대 변화율, 비교 불가와 `%` 단위 회귀를 검증했습니다.

초기 전체 테스트 명령은 Backend pytest 설정을 읽지 않아 async 테스트 실행에 실패했습니다.
설정을 명시한 위 명령으로 전체 재검증했습니다. 첫 라이브 설정의 기본 Source 디렉터리는
payment 데이터만 포함해 등록 422였으며, 시연 Source 경로를 명시한 후 통과했습니다.

## 범위와 운영 조건

24시간을 실제 기다리지는 않았고 완료된 과거 일자를 실제 worker가 처리하도록 검증했습니다.
Backend 실행 중에만 주기 측정이 동작하며 종료 중 누락은 재시작 후 보충합니다.
로컬 POSIX 파일 시스템과 SQLite를 공유하는 worker를 지원합니다. 다중 호스트/네트워크
파일 시스템은 별도 작업 큐와 잠금 구성이 필요합니다. 늦게 적재된 과거 데이터는
POST measurements로 재측정하며, 실패는 0이 아닌 unavailable/null로 남습니다.
개인 SDD 아티팩트 원격 저장소는 접근 불가여서 로컬 체크포인트로 보존했습니다.

증거 JSON은 `data/live-validation/2026-09-10/signals-daily/`에 로컬 보관합니다.
