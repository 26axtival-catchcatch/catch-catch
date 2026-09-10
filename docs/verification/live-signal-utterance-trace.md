# 발화별 trace와 패턴 묶음 검증

2026-09-10 사용자 요청에 따라 분석 발화 하나의 trace 안에서 발견 패턴과 선택 등록을 연결했습니다.
이 문서는 이전 `live-signals-first-class.md`의 후보 등록 trace 분리 동작을 대체합니다.

## 구현

분석 trace의 `customer_signal.turn` 아래 조사·검증·보고 역할과 `customer_signal.signals` 묶음이 있습니다.
묶음 아래 각 `customer_signal.signal` span에 제목, 판정, 사유, 근거, 지표와 제한사항을 남깁니다.
확정되지 않은 패턴도 표시하며, 독립 검증을 통과한 후보만 DB에 저장합니다.
새 후보의 `trace_id`, `observation_id`를 보존하고, 이후 사용자 선택 등록은 원래 패턴 span의 자식으로 추가합니다.
등록 때 두 번째 발화 root를 만들지 않습니다. 분석과 관계없는 직접 정의 등록·별도 기간의 재측정은 개별 API 작업 trace입니다.

별도 등록 에이전트는 없습니다. 코디네이터는 조사 배분, 조사 에이전트는 패턴 제안,
검증 에이전트는 독립 확인, SignalService/API는 사용자 선택 저장을 담당합니다.

## 실제 Bedrock 시도와 제한

- 전체 질문 Run `375cf4e9-1226-4e2b-8652-60e37e566465`: 일부 조사 모델 호출에서 연결 오류가 발생했고 남은 응답이 장시간 돌아오지 않았습니다. 검증용 실행을 수동 중단했으며 최종 상태는 `failed/run_cancelled`입니다.
- 부가서비스·로밍 범위 Run `0493d765-1504-4b2a-ae98-2e9914649d85`: 코디네이터 Bedrock 호출이 약 54초 후 실패했고 `failed/investigation_failed`로 종료됐습니다.
- MCP에서 해당 GENERATION의 ERROR 및 연결 관련 오류 표시를 확인했습니다. 상세 네트워크 원인은 이번 범위에서 확정하지 않았습니다.
- 새 Bedrock 분석 성공을 검증했다고 주장하지 않습니다. 애플리케이션 시간·호출 제한은 추가하지 않았습니다.

## 결정적 합성 데이터로 실제 Langfuse 검증

모델 호출 없이 실제 SQL 측정·독립 재측정·SQLite 후보 저장·선택 등록을 실행했습니다.
Langfuse SDK에 기록하고 **Langfuse MCP**에서 실제 관측을 조회했습니다.

- trace ID: `4867109a38f84177803376afe2645656`
- root 제목: `검증용: 모델 호출 없이 패턴 trace 연결 확인`
- 관측 7개: AGENT 3개(발화 root, 조사, 검증), SPAN 4개(묶음, 패턴 두 개, 등록)
- 모든 관측이 하나의 trace ID를 가집니다. `customer_signal.turn`은 하나입니다.
- 묶음 span `691ab524ecb08868`은 root의 자식입니다.
- 확정 패턴 `c9faddf9f5796d62`와 미확정 패턴 `b9dcd5bb0799d198`은 묶음의 자식입니다.
- 등록 span `89f659b74db17026`은 확정 패턴의 자식입니다.
- 등록은 별도 검증 DB에서 수행했으며 실사용 Signal 목록에 합성 검증 패턴을 넣지 않았습니다.

[합성 배선 검증 trace](http://localhost:3100/project/cmt84iujl0007qs077zcxunel/traces/4867109a38f84177803376afe2645656)

## 자동 검증

관련 테스트 84개와 Ruff, diff 검사를 통과했습니다. 스펙·코드 품질 검토에서 잔여 지적이 없습니다.
같은 조사 task의 여러 패턴, 확정/미확정/기각/재조사 상태, 정의 없는 후보,
이전 DB 행의 optional 필드 호환, 같은 trace를 유지하는 등록 응답 헤더를 검증했습니다.

재현 스크립트:

- `scripts/verify-signal-trace-wiring-live.py`: 모델 호출 없는 실제 SQL/DB/Langfuse 배선 검증
- `scripts/verify-signal-utterance-live.py`: 실제 Bedrock 분석 및 선택 등록 검증
- `scripts/verify-signal-spans-mcp.py --trace-id <ID> --trace-tree`: 전체 관측의 공개 metadata와 부모 관계 확인

실행 증거는 Git에서 제외한 `data/live-validation/2026-09-10/signals-one-utterance*`에 저장합니다.
