# 고객 여정 멀티에이전트 FE 인계 문서

갱신일: 2026-09-10. Backend 핵심 구현과 제한, 확장 데이터의 실제 Gemini 실행을 검증했습니다.

FE 담당자가 기존 중앙 어댑터로 새 분석을 연결할 수 있도록 실행 순서와 결과 매핑을 정리했습니다.
FE 화면 구현은 이번 변경에 포함하지 않습니다.

## 실행 순서

`첫 분석 완료 → FE에서 데이터 추가 → 같은 질문과 기간으로 새 분석 실행`으로 진행합니다.
질문은 다음 문장을 그대로 사용합니다.

> 최근 일주일간 앱에서 원하는 문제를 해결하기 위해 곧바로 못 찾고 헤맨 고객 찾아줘

기간은 한국 시간 `2026-09-04T00:00:00+09:00` 이상, `2026-09-11T00:00:00+09:00` 미만입니다.
시드의 기준 주간을 고정하므로 FE가 매번 현재 시각으로 기간을 다시 계산하면 안 됩니다.
제한 결과는 실제 실행 후 캡처로 비교하고, 확장 풀케이스 한 번의 전체 흐름을 녹화합니다.

1. `GET /api/sources`로 현재 등록된 소스를 가져옵니다.
2. `POST /api/runs?mode=gemini`에 아래 요청을 보냅니다.
3. 응답의 `events_url`을 구독하고 `status_url`로 상태를 조회합니다.
4. 첫 Run이 완료되면 외부 데이터 추가 흐름을 실행합니다.
5. Source 목록을 다시 조회하고 추가된 소스를 포함해 같은 질문과 기간으로 새 Run을 생성합니다.

```json
{
  "question": "최근 일주일간 앱에서 원하는 문제를 해결하기 위해 곧바로 못 찾고 헤맨 고객 찾아줘",
  "start_at": "2026-09-04T00:00:00+09:00",
  "end_at": "2026-09-11T00:00:00+09:00",
  "enabled_sources": [
    "hackathon_search_history",
    "hackathon_search_feedback",
    "hackathon_voc"
  ]
}
```

확장 요청에는 `hackathon_app_behavior`, `hackathon_vas_subscription`,
`hackathon_billing_profile`, `hackathon_roaming_usage`를 추가합니다.
진행 중인 Run의 공간은 고정되며, 추가된 데이터는 새 Run에서 읽습니다.
새 업로드 HTTP 엔드포인트는 추가하지 않았습니다. 외부 데이터 등록 담당자는 기존 승인된
`spec.json`과 `data.csv`를 `ONBOARDED_SOURCES_DIR/<source_id>/`에 준비해야 합니다.
실제 라이브 검증 디렉터리는 `data/investigation-demo-sources`입니다.

## 기존 중앙 어댑터와 계약

[wire_projection.py](../backend/src/customer_signal/runtime/wire_projection.py),
[run-client.ts](../frontend/src/features/customer-intelligence/run-client.ts)와 FE 소스는 변경하지 않았습니다.
요청 필드, `mode`, 202 응답의 세 필드, SSE 이름과 payload, 상태 enum,
Artifact `schema_version=1`, `report_kind=customer_signal`을 유지합니다.

| 화면에서 사용할 내용 | 기존 응답 위치 | 의미 |
| --- | --- | --- |
| 확정 고객 수 | `report.metrics`, key `verified_customer_count` | 확정된 모든 패턴의 고객을 중복 제거한 수 |
| 미확정 후보 수 | key `candidate_customer_count` | 독립 검증이 부족한 후보의 고객 수. 확정과 중복 가능 |
| 확인된 패턴 | `report.findings` | 서버가 실제 질의 집계에 묶은 Claim과 독립 검증 설명 |
| 개선 제안 | `report.recommendations` | 근거에 연결한 개선 가설. 개선 효과를 측정한 결과가 아님 |
| 미확정 사유와 데이터 한계 | `report.limitations` | 확정 결과와 분리해 표시 |
| 대표 여정 | `report.representative_journeys` | 실제 이벤트의 공개용 발췌 |
| 대표 고객 ID | `facts[].payload.kind=get_customer_journey`의 `customer_id` | 상세 여정 API에서 사용할 마스킹 ID |

위험 점수는 계산하지 않으므로 `ranked_customers`는 빈 배열입니다.
위험도나 순위를 임의로 표시하면 안 됩니다. 대표 여정 Fact의 고객 ID로
`GET /api/runs/{run_id}/customers/{customer_id}/journey`를 호출합니다.
근거 ID로 `GET /api/runs/{run_id}/evidence/{evidence_id}`를 호출합니다.
두 상세 조회는 완료된 Run에서만 가능합니다.
새 분석의 상세 조회는 해당 Run에 저장한 공개 Fact를 반환하므로 Source 변경이나
Backend 재시작 후에도 완료 당시의 여정과 근거를 유지합니다.

대표 여정은 고객당 최대 20개, 보고서 전체 최대 100개 이벤트를 표시합니다.
긴 여정은 시작과 끝을 포함해 발췌하며 전체 고객 집계와 구분합니다.
전체 cohort 질의 결과와 상세 조사 기록은 Backend 내부 감사 파일에 보관합니다.
기존 다운로드 JSON은 공개 Artifact이고 내부 감사 파일 전체를 반환하지 않습니다.

공개 SSE에는 신규 역할 enum을 넣지 않았습니다. 기존 Goal과 Plan은 시작 시,
Fact와 Note는 확보한 결과를 공개 계약으로 변환할 때 발행합니다.
`step_started/completed`의 시간은 해당 공개 Fact 기록 단계의 시간입니다.
모델 조사 역할의 실제 소요 시간은 Langfuse에서 확인합니다.
Fact의 `processing`은 이미 계산한 결과를 공개 형식으로 변환한 단계의 통계이며,
전체 공간의 이벤트 수와 실제 SQL은 내부 감사 파일에 기록합니다.

현재 [use-catch-session.ts](../frontend/src/features/signal-catcher/state/use-catch-session.ts)는
mock과 타이머를 사용합니다. 이 화면의 실데이터 연결은 FE 담당자의 후속 작업입니다.
Backend가 구동된 것만으로 이 화면의 실연결이 완료되지는 않습니다.

## 추가 구현 내역

공개 API, SSE 종류, 필수 응답 필드는 추가하지 않았습니다.

| 추가 내용 | 위치 | FE 영향 |
| --- | --- | --- |
| 총괄, 병렬 조사, 독립 검증과 재조사, 보고 | `backend/src/customer_signal/investigation/runner.py` | 기존 POST 뒤에서 실행 |
| 모든 허용 테이블의 읽기 전용 SQL, 여정 조회 | `investigation/data.py` | Source 선택만 기존 요청으로 전달 |
| Gemini 역할별 tool calling | `investigation/model.py` | fixture는 그대로, gemini에 적용 |
| 기존 Goal, Plan, Fact와 Report 변환 | `investigation/projection.py` | 기존 타입으로 읽음 |
| 역할과 쿼리 감사 기록 | `data/run-artifacts/investigations/{run_id}.json` | Backend 내부 파일, 신규 FE API 없음 |
| Source 목록 및 새 실행 시 등록 재조회 | `api.py` | 데이터 추가 뒤 목록을 다시 조회 |
| 완료된 Run의 여정과 근거 복원 | `runtime/coordinator.py` | 기존 상세 API 경로로 저장된 Fact 조회 |
| Langfuse 역할별 부모 관측 | `observability/langfuse.py` | 공개 run_id로 trace를 찾음 |

2026-09-10 추가 결정으로 호출 횟수와 전체 시간을 포함한 실행 예산 제한을 해제했습니다.
분석은 역할이 결과를 제출하고 검증을 마칠 때까지 진행합니다. 15분 이내 종료를 보장하지 않습니다.
완료하지 못한 후보는 한계와 함께 남기며, 모델이나 데이터 연결 실패는 기존 실패 상태로 반환합니다.

## Langfuse 확인

사용자 결정에 따라 Langfuse를 사용합니다. 기존 AGENTS의 LangSmith 설정 및 적재 지시는
이번 관측 대상에 적용하지 않으며, 키와 개인정보를 노출하지 않는 원칙은 유지합니다.

`customer_signal.turn` 부모 아래에 `customer_signal.coordinator`,
`customer_signal.investigator`, `customer_signal.verifier`, `customer_signal.reporter`가 연결됩니다.
모델과 `catalog_data`, `query_data`, `customer_journey`, `finish` 도구는 각 역할 아래에 남습니다.
metadata의 `run_id`, `role`, `task_id`, `round_index`로 실행을 구분합니다.
trace ID는 공개 Run UUID의 하이픈을 제거한 값입니다.

환경은 기존 `scripts/dev.sh gemini`가 선택한 `.env`를 Backend 프로세스 시작 시 전달합니다.
새 조사 모델 호출은 legacy LangSmith 플래그가 켜져 있어도 LangSmith 추적을 끄고
Langfuse callback을 유지합니다. 다른 실행기의 설정과 환경 파일은 변경하지 않았습니다.
환경 파일을 source하거나 키를 문서에 복사하면 안 됩니다.

현재 확인한 Langfuse는 [로컬 서버](http://localhost:3100)의 `demo-1` 프로젝트입니다.
프로젝트 ID는 `cmt84iujl0007qs077zcxunel`입니다.

## 검증 결과와 재현

| 실행 | Run ID | 소스 / 이벤트 | 시간 | 확정 / 미확정 고객 |
| --- | --- | --- | --- | --- |
| 제한 데이터 | `872e0d6e-efc8-4a41-93fd-1c8f4e0cb5c3` | 3개 / 1,135개 | 123.89초 | 270명 / 70명 |
| 확장 풀케이스 | `d4a7b26c-ed24-473a-a2b1-41ce03b3cda1` | 7개 / 9,106개 | 171.96초 | 215명 / 51명 |

제한 실행에서는 부가서비스 검색 실패 120명과 소액결제 가이드 탐색 실패 150명을 확인했습니다.
로밍 상담 전환 70명은 정상 채널 선택과 구분할 앱 행동이 부족해 미확정으로 남겼습니다.

확장 실행에서는 로밍 상세 반복 조회 후 이탈하고 상담으로 가입한 56명과,
소액결제 약관 동의 시트를 반복해서 닫은 159명을 확인했습니다.
결제 159명 중 **9명은 제한 데이터의 모든 테이블에 이벤트가 없던 고객**입니다.
비교 근거는 로컬 검증 디렉터리의 `scope-comparison.json`에 보관합니다.
확장 Run이 실행한 고객 목록 질의와 제한 스냅샷의 전체 고객 집합을 비교해 확인했습니다.
본인인증 실패 51명은 기능 실패만으로 헤맴을 확정할 수 없어 후보로 남겼습니다.

전체 확정 수가 늘어나는 것을 성공 조건으로 삼으면 안 됩니다.
독립된 새 실행에서 조사 가설과 검증 범위가 달라지므로, 새 고객의 발견과 구체적인
여정 근거의 추가를 비교해야 합니다. 위 수치는 고정된 시연 기대값이 아니라 실제 실행 결과입니다.

- 실제 Source 디렉터리에 네 개 테이블 추가 후, 재시작 없이 해커톤 Source 목록 3개에서 7개로 반영 확인
- 두 Run의 대표 여정 4건과 근거 4건씩 HTTP 200, JSON과 Markdown 다운로드, SSE 재연결과 presentation 조회 통과
- 제한 Run은 Backend 재시작 후 같은 ID로 위 조회를 재검증
- 두 Run 모두 Langfuse API HTTP 200, AGENT 7개, GENERATION 90개, TOOL 96개 적재
- 모델 호출 90개와 도구 95개가 역할 아래에 중첩, 나머지 도구 1개는 부모의 데이터 스냅샷 생성
- FE 기존 run-client 테스트 42개 통과, FE 소스와 중앙 어댑터 변경 없음

확장 실행의 부가서비스 조사는 도구 호출 예산 안에 전체 고객 목록 질의를 마치지 못했습니다.
그 관찰 내용은 보고서의 제한사항에 보존했습니다. 이는 해당 실행의 조사 미완료이며
부가서비스 데이터가 없어 분석할 수 없다는 뜻은 아닙니다.

LangSmith 추적을 끈 최종 코드로도 확장 전체 실행을 다시 검증했습니다.
Run `c648510c-8aa7-4b72-be21-59c2d177031f`는 185.33초에 완료했으며
확정 266명, 후보 14명입니다. 여정 5건과 근거 6건, 다운로드, SSE 재연결과 presentation이
통과했고, Langfuse에 AGENT 7개, GENERATION 101개, TOOL 109개가 적재됐습니다.
모델 101개와 도구 108개는 각 역할 아래에 연결됐습니다.

**판정 변동이 남아 있습니다.** 최종 실행은 본인인증 반복 실패 51명을 확정으로 분류했고,
앞선 풀케이스는 경로 탐색 실패 근거가 부족해 후보로 남겼습니다.
인증 오류를 반복한 것만으로 원하는 경로를 찾지 못했다고 단정할 수 없으므로,
이 51명은 시연의 검증된 신규 발견 수에 포함하면 안 됩니다.
두 확장 실행에서 공통으로 확인된 로밍 56명과 약관 동의 시트 이탈 159명을 비교 근거로 사용합니다.
제한 공간에 없던 결제 고객 9명도 두 실행에서 동일하며,
최종 비교 파일은 `scope-comparison-final.json`입니다.
독립 검증과 실제 질의 연결은 동작하지만 의미상 경계 사례의 판정 일관성을 보장하는 수준은 아닙니다.

```sh
ONBOARDED_SOURCES_DIR=data/investigation-demo-sources bash scripts/dev.sh gemini
uv run --project backend python scripts/verify-investigation-live.py limited
uv run --project backend python scripts/verify-investigation-live.py expanded
```

검증 결과, 실제 JSON과 Markdown 다운로드, SSE 기록은 `data/live-validation/2026-09-10/`에 남깁니다.
이 디렉터리와 데모 데이터 복제본은 로컬 산출물로 Git에서 제외합니다.
기존 완료 결과를 모델 재호출 없이 확인하려면 위 검증 명령에 `--run-id <run_id>`를 붙입니다.
`scripts/verify-langfuse-live.py <run_id>`는 선택한 환경 파일을 Backend와 같은 방식으로
전달해 실행하며, 공개 실행 시각과 관측 이름만 저장합니다.
검증 도구의 `limited-*`, `expanded-*` 파일은 해당 모드의 마지막 실행으로 덮어씁니다.
위 확장 풀케이스의 결과 사본은 같은 디렉터리의 `d4a7b26c-*` 파일입니다.
실제 녹화와 화면 캡처는 FE 연결 후 발표자가 진행합니다.

데이터 한계와 추가 시딩 후보는 [데이터 탐색 가능성 검토](seeding/scope-expansion-feasibility.md)에 정리했습니다.
앱과 일부 테이블은 행동 시각 대신 적재 시각을 매핑하므로 서로 다른 소스의 분 단위 순서를
확정하는 근거로 사용하면 안 됩니다. 새 앱 스크롤/GNB 행동을 가정해서 결과에 추가하지 않습니다.

## 실행 제한 해제 내역

아래 변경은 앞의 라이브 결과를 확보한 뒤 적용했습니다. 기존 결과의 수치와 실행 시간은 그대로 보존합니다.

| 항목 | 변경 전 | 변경 후 |
| --- | --- | --- |
| 역할별 모델 호출 | 최대 32회, 마지막 3회 강제 제출 | 횟수 제한과 강제 제출 제거 |
| 모델 호출 응답 대기 | 55초 | 애플리케이션 타이머 제거 |
| Bedrock 호출의 출력 토큰 지정 | 8,192 | 지정 제거, 서비스 기본값 적용 |
| 조사 및 검증 | 데이터 준비 포함 680초 | 시간 제한 제거 |
| 재조사 | 최대 1회, 3건, 남은 시간 120초 이상 | 요청 건수, 라운드 및 잔여 시간 조건 제거 |
| 보고 | 최대 90초 | 시간 제한 제거 |
| 전체 Run / 상위 실행기 | 870초 / 890초 | 시간 제한 제거 |
| SQL | 16,000자, 10초, 결과 50,000행 | 세 제한 제거, 전체 결과 저장 |
| DuckDB 자원 | 메모리 256MB, 스레드 2개 | 별도 강제 설정 제거, 엔진 기본 설정 사용 |
| 라이브 검증 스크립트 | 최대 910초 대기 | 완료 또는 실패까지 대기 |

선택한 Source와 기간, 읽기 전용 SELECT, 외부 접근 차단, 실제 근거 참조 검증은 유지합니다.
SQL 결과 미리보기와 여정 도구는 100행/이벤트를 표시하지만 전체 이벤트와 질의 결과는 서버에 있습니다.
필요한 중간 구간은 SQL 조건과 LIMIT/OFFSET으로 조회할 수 있습니다.

조사 분배 최대 3개, 역할 응답의 후보 최대 6개와 대표 고객 최대 2명, 검증 판정 최대 18개는
현재 협업 응답 스키마에 남아 있습니다. 공개 보고서는 대표 여정 최대 5명과 총 100개 이벤트,
발견 최대 32개, 개선 제안 최대 16개 등 기존 FE 스키마를 유지합니다.
이 항목들은 호출 횟수나 전체 조사 행 수를 제한하는 예산과 구분합니다.
모델 서비스의 컨텍스트, 출력 길이, 요청 속도 제한과 로컬 머신의 자원 한계는 남습니다.


제한 해제 후 실제 Gemini Run `f6ef453f-2711-4aa0-960b-a5b032ea5a39`는 227.21초에 완료했습니다.
부가서비스 조사 역할은 모델 51회와 SQL 42회를 사용해 두 후보를 제출했고 독립 검증까지 진행됐습니다.
전체 SQL은 93개이며 Langfuse에는 역할 7개, 모델 호출 119개, 도구 131개가 기록됐습니다.
모델 호출 119개 전부 역할 아래에 연결됐습니다. 여정 5건과 근거 6건, 다운로드, SSE 재연결과
presentation 조회를 통과했습니다. 최신 `expanded-*` 파일은 이 실행의 결과입니다.

이 검증은 조사 예산으로 인한 조기 종료가 해소됐음을 보여줍니다.
최종 분류의 의미상 정확성과 데이터 한계가 모두 해결됐다는 뜻은 아닙니다.
보고서는 부가서비스 90명/97명 패턴과 결제 159명을 확정하고 로밍 56명을 후보로 남겼습니다.
앞선 실행들과 판정 범위가 달라진 사실을 보존하며, 단순 총 확정 수 증감으로 품질을 판단하지 않습니다.

## 시그널 정량 추적 확장

새 조사에서는 지표를 실제 계산하고 독립 재측정한 패턴을 등록 후보로 제공합니다.
에이전트가 제안하고 사용자가 선택해 등록합니다. 기존 중앙 어댑터 계약은 유지하며
추가 API 호출 순서, 값 해석, 재측정과 보존 정책은 [시그널 FE 인계](signal-fe-handoff.md)에 정리했습니다.
