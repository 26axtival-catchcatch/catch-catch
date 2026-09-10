# 시그널 알림 검증 기록

검증일: 2026-09-10
기준 커밋: `main`의 `5473bda`
작업 브랜치: `codex/signal-alert-thresholds`

## 기능 검증

알림 조건 선택, 임계값 변경과 해제, 측정 후 이벤트 저장, 커서 조회를 검증했습니다.
모델 추천은 사용자 선택 전에는 활성화되지 않습니다.

| 항목 | 확인 내용 |
| --- | --- |
| 모델 추천 | Gemini와 Bedrock 어댑터의 구조화 결과 검증, 지표와 단위 확인, 외부 오류 비공개 처리 |
| 등록 | 제안 선택과 직접 정의 모두 추천 반환, 실패해도 시그널 유지, 명시적 재시도 |
| 조건 | 현재값, 차이, 상대 변화율, 초과/이상/미만/이하, 사용자 정의 지표 |
| 단위 | 비율의 퍼센트포인트와 상대 백분율 구분 |
| 선택 | 기본 비활성, 전체 교체, 빈 목록 해제, 잘못된 ID와 중복 선택 거절 |
| 동시 편집 | `revision` 충돌 시 409, 동일 선택은 기존 상태 유지 |
| 상태 전이 | 처음 충족 시 1개, 유지 중 중복 없음, 정상값 이후 재진입 시 새 이벤트 |
| 측정 불가 | 결측, 비교 불가, 기준값 0, 산술 오버플로에서 평가 생략 |
| 지표 독립성 | 다른 지표가 결측이어도 선택 지표는 평가 |
| 시간 | 하루가 아닌 측정, 역순 이력, 같은 기간 수정의 추가 알림 방지 |
| 상태 | 시그널 일시정지와 보관 시 평가 생략 |
| 저장 | 동시 중복 저장과 재시작, 이벤트 저장 실패 시 측정과 상태까지 롤백 |
| 폴링 | 최초 커서 부트스트랩, 오름차순 페이지, 이어 읽기, 빈 페이지의 커서 유지 |
| API | 한국어 summary, signals 태그, 응답 스키마, 404/409/422 |
| 오류 입력 | JSON의 NaN, Infinity, 1e309를 500 대신 422로 처리 |
| 스케줄러 | 기존 DailyScheduler 실행에서 새 이벤트가 생성되고 HTTP 폴링으로 조회 |

## 실제 Bedrock과 HTTP 검증

다음 명령으로 임시 백엔드를 시작하고 승인된 해커톤 합성 데이터를 측정했습니다.
검증 스크립트는 선택한 환경 파일을 `uv --env-file`로 백엔드에만 전달하며,
기존 shell의 LangSmith, LangChain, Langfuse 환경변수를 실행 직전에 제거합니다.

```sh
uv run --project backend python scripts/verify-signal-alerts-live.py --mode bedrock
```

검증 결과입니다.

- 모델 추천 3개 생성: 비율 75% 이상, 비율 증가 10%p 이상, 모집단 고객 수 50% 증가
- 모든 추천이 서버에 존재하는 지표와 단위로 검증됨
- 추천 ID를 선택하고 테스트용 임계값을 명시적으로 변경한 뒤 이벤트 발생
- 같은 관측 기간과 스냅샷 재요청에서 기존 측정 ID 반환, 이벤트 중복 없음
- 백엔드 종료와 재시작 후 추천, 규칙과 이벤트 동일
- 저장한 커서 이후 조회에서 이미 처리한 이벤트 미반환

이벤트 발생 테스트는 프론트의 임계값 수정 경로를 함께 검증하기 위해 테스트용 값을 사용했습니다.
모델이 제안한 원래 75% 임계점의 통계적 적절성을 검증한 결과는 아닙니다.

Trace ID: `d2d70f76dea24dedb3d5ecf1ba04e0d5`

공급자 호출 설정의 `customer_signal.alert_recommendation` 이름, `stage`와 provider 태그,
원래 등록 trace 아래의 추천 span 연결은 자동 테스트로 확인했습니다.
로컬 Langfuse 조회는 연결 실패로 원격 적재 여부를 확인하지 못했습니다.
Gemini 어댑터는 주입한 공급자 테스트로 검증했으며 실제 원격 호출은 Bedrock으로 수행했습니다.

## 실행한 검사

```sh
uv run --project backend pytest backend/tests -q
uv run --project backend pytest backend/tests/test_signal_alerts.py \
  backend/tests/test_signal_alert_api.py backend/tests/test_signal_alert_recommendations.py \
  backend/tests/test_signal_trace_continuity.py -q
npm --prefix frontend run typecheck
npm --prefix frontend test -- --run
```

- 백엔드 전체 회귀: 981개 통과, 660.92초
- 전체 회귀 실행 중 추가한 입력 검증과 오버플로 보완을 포함한 집중 검사: 41개 통과
- 프론트 타입 검사: 통과
- 프론트 테스트: 14개 파일, 109개 통과
- 변경 Python 파일 Ruff 검사와 `git diff --check`: 통과
- 인계 문서 JSON 예시 5개: 실제 Pydantic 응답/요청 모델 검증 통과
- 인계 문서 TypeScript 폴링 예시: strict 타입 검사 통과

프론트 의존성은 기존 잠금 파일로 `npm ci`하여 복원했습니다. 의존성 버전은 변경하지 않았습니다.
백엔드 검사에서 기존 FastAPI TestClient의 httpx 사용 중단 예정 경고가 출력됩니다.

## 적용 범위

백엔드 API와 프론트 인계 문서를 구현했습니다. 프론트 화면, 브라우저 알림과 Web Push는
이번 변경에 포함하지 않습니다. 조건과 이벤트는 기존 앱의 공유 저장소 범위를 따릅니다.
성공한 추천은 고정하며 사용자 임계값 변경 후에도 `rationale`은 원래 추천 설명을 유지합니다.
동시에 최초 추천을 요청하면 모델 호출이 중복될 수 있지만 처음 저장한 성공 추천의 ID를 유지합니다.
