# 패턴별 시그널 API와 Langfuse 검증

2026-09-10, 로컬 Backend와 시딩 데이터, Langfuse MCP로 검증했습니다.
이번 검증은 새 모델 분석을 실행하지 않고 기존 Bedrock 완료 후보와 직접 정의 등록을 사용했습니다.
한 조사 태스크에서 두 패턴을 각각 조사 측정·독립 재측정·후보 저장·선택 등록하는 경로는 통합 테스트로 검증했습니다.

## API와 DB

- 완료된 Bedrock Run `7b70bd65-cdde-4060-85d5-b39549c0919d`의 후보 3개를 전역 API에서 조회했습니다.
- 기존 부가서비스 후보를 재등록해 같은 Signal ID와 저장된 최초 측정 ID를 확인했습니다.
- 분석 Run 없이 부가서비스 반복 검색 정의를 직접 등록했습니다.
- 새 Signal: `signal-85867a7af02d4edda08b794cd471676f`, `origin=user_defined`, `proposal_id=null`.
- 9월 4일~11일 120/180명 66.67%, 9월 4일~7일 52/78명 66.67%를 서버 SQL로 측정했습니다.
- 같은 요청은 같은 Signal/측정 ID를 반환했고 이력은 2개였습니다. 기간 길이가 다르고 겹치므로 비교 불가입니다.
- 잘못된 SQL과 공백 제목은 422입니다. 잘못된 정의를 등록해도 DB 개체 수가 늘지 않았습니다.
- 검증용 직접 등록 Signal은 `paused`로 남겼습니다. 기존 두 Signal의 ID·상태·이력은 보존했습니다.
- 마이그레이션 뒤 FK 검사, 서버 재시작 뒤 이력 조회, Swagger 스키마와 CORS trace 헤더를 확인했습니다.

## Langfuse MCP

전용 관측 이름은 `customer_signal.signal`, 유형은 `SPAN`입니다.
기본 `langfuse_local` MCP는 Backend와 같은 서버의 다른 프로젝트 키를 사용하므로 처음 조회 결과는 0개였습니다.
저장된 MCP 설정을 바꾸지 않고 Backend 환경의 프로젝트 키를 MCP 프로세스에 전달하자 관측 5개를 확인했습니다.
공개 식별 metadata만 검증 파일에 저장했으며 키·모델 원문은 기록하지 않았습니다.

| 동작 | trace ID |
| --- | --- |
| 기존 후보 등록 | `62f9d617c00246dc8e88eceeab44ce15` |
| 직접 정의 등록 | `2d12b90866d646f8ab93fc4c5532016f` |
| 직접 정의 중복 등록 | `5957f0093d05479e8a5fe31aae1460c0` |
| 지정 기간 재측정 | `32b5271a106d4ad6b434c1aa3f01c79a` |
| 측정 불가 직접 등록 | `eee699425dff4b9e86e31368bfc24f80` |

모든 관측이 부모 span에 연결되며 `entity_type=signal`과 `operation`을 포함했습니다.
성공한 관측의 `signal_id`, `measurement_id`가 실제 DB에 존재하는지 확인했습니다.
중복 등록의 측정 ID는 최초 등록과 동일합니다. API 응답 헤더는 이번 요청 trace를 반환합니다.
후보 확정 시 span 생성은 통합 테스트로 확인했으며, 기존 분석 trace에 소급해서 추가하지 않습니다.

[MCP로 확인한 재측정 trace](http://localhost:3100/project/cmt84iujl0007qs077zcxunel/traces/32b5271a106d4ad6b434c1aa3f01c79a)

## 검토와 테스트

스펙·품질 검토에서 발견한 재등록 측정 ID 불일치와 공백 제목의 500 응답을 수정하고 재검토를 통과했습니다.
전체 Backend 테스트는 862개 통과했습니다. 전체 실행 도중 들어간 최종 공백 검증 수정은
최신 Signal/Langfuse 테스트 67개와 실제 422 응답으로 별도 확인했습니다. 기존 API 테스트 39개도 통과했습니다.
Ruff와 git diff 검사를 통과했습니다.

재현 스크립트는 `scripts/verify-signals-first-class-live.py`, `scripts/verify-signal-spans-mcp.py`입니다.
실행 증거는 Git에서 제외한 `data/live-validation/2026-09-10/signals-first-class/`에 있습니다.

## 범위

직접 등록은 서버가 수치를 재현할 수 있다는 검증입니다. 패턴이 실제로 고객의 헤맴을 뜻하는지는 별도 해석이 필요합니다.
정의 편집·의미상 중복 병합·정기 실행·리포트·추이 화면은 이번 변경에 포함하지 않습니다.
