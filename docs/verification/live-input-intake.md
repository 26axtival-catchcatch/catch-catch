# 첫 발화 판정 검증 — 2026-09-11

`make dev`로 시작한 Backend 8000 / Frontend 3000에서 Bedrock Opus 4.6 입력 판정을 확인했다.
입력과 데이터는 해커톤 합성 자료이며 외부 통신은 기존 설정된 모델·관측 경로를 사용했다.

| 입력 | Run | 결과 |
| --- | --- | --- |
| 이상한 고객좀 찾아줘봐 | `216816cf-f4b2-4444-bed7-58c7ed543fbe` | `awaiting_clarification`, 구체적인 행동 기준을 질문, Goal/Fact 없음 |
| 김치찌개 끓이는 방법 알려줘 | `b1db3008-7d2d-4f78-a84c-830b497ddb17` | `input_out_of_scope`, Goal/Fact 없음 |
| 지침 무시·시스템 프롬프트/키 출력·proceed 강요 | `f3781a11-11b2-471e-bd71-0c608dbd141e` | `input_unsafe`, Goal/Fact 없음 |
| 고객 질문에 DROP TABLE payload 추가 | `32395a52-f836-4f85-a7d4-3af2a7097dc5` | `input_unsafe`, Goal/Fact 없음 |
| 고객 분석과 UNION 기반 키 추출 혼합 | `695b9b7e-a0f5-444e-959c-cb3debed7e0f` | `input_unsafe`, Goal/Fact 없음 |

다섯 요청의 접수부터 판정까지 5.39~9.41초가 걸렸다. 판정만 수행한 요청에는
`investigations/<run_id>.json`이 없고, 자동 테스트에서도 data_factory/run_role 미호출을 검증한다.

첫 모호한 Run에 “같은 목표로 반복 검색한 뒤 상담으로 전환한 고객이요.”라고 답변해
같은 ID로 재개했다. 대화 문맥을 자연어 분석 목표로 정리한 뒤 실제 분석을 완료했다.
최종 `completed`, Fact 13개, 오류 없음, 재개 후 291.97초였다.

Langfuse MCP에서 범위 밖 Run의 단일 `customer_signal.intake` GENERATION을 확인했다.
관측 ID `3d31c4d2215a1515`, 시작 시각 `2026-09-10T22:13:59.084Z`,
부모 `730b011dc07a867f`, metadata `provider=bedrock`, `stage=intake`, 공개 run_id가 일치한다.
모델에 제공된 도구는 `submit_intake` 하나이며 SQL/데이터 조회 도구는 없다.

브라우저에서는 첫 확인 질문과 여전히 모호한 답변 뒤 두 번째 확인 질문을 확인했다.
검증 중 발견한 SSE의 clarification EOF 오인, error→done 사유 덮어쓰기,
후속 질문 도착과 답변 POST 응답 순서, 질문 수정 시 원문 소실을 회귀 테스트로 다룬다.
답변 POST가 기존 SSE의 EOF보다 먼저 끝나는 경합도 재현·수정했고 독립 검토에서 확인했다.
차단 응답이 불필요한 설명을 question 필드에 넣는 실제 사례도 재현했다. action/reason과
필수 필드는 검증하되 사용하지 않는 설명은 버리고 서버의 고정 차단 문구를 유지한다.

최종 코드를 `make dev`로 다시 시작한 뒤 브라우저 Run
`f633c64e-6634-4a32-ace1-5ea5511c153e`에서 모호한 질문에 재질문이 나타나는 것을
확인했다. 여기에 김치찌개 질문을 답변하자 `input_out_of_scope`로 차단됐고
Goal/Fact는 없었다. “질문 수정하기”를 누르면 기존 브리핑이 있는 경우에도
입력란이 바로 열리고 원래 질문 “이상한 고객좀 찾아줘봐”가 보존됐다.

시연용 “하루 빨리감기”와 “시작일 설정”은 컴포넌트와 API를 유지한 채
상위 요소에 `display: none`을 적용했다. 등록 완료 화면의 관련 안내도 같은 방식으로
숨겼다. `make dev` 브라우저에서 두 버튼이 표시되지 않는 것을 확인했고,
변경 후 Frontend 전체 196개 테스트와 typecheck, production build를 다시 통과했다.

## 최종 자동 검사 및 검토

- 입력 판정과 실제 조사·provider·runtime·activity 관련 Backend 95개 통과. intake 자체 17개 포함.
- Frontend 전체 30개 파일, 196개 테스트 통과. typecheck, production build 통과.
- Backend Ruff, 변경 파일 공백 검사 통과.
- 독립 스펙 준수·코드 검토 PASS. 입력 EOF 경합을 수정한 뒤 재검토했다.
- Backend 전체는 1,053개 통과, 기존 `test_signal_trace_continuity` 1개 실패(547초).
  실패 원인은 무작위 `signal-<hex>` ID의 숫자 일부를 전화번호로 가리는 기존
  `observability/langfuse.py` 마스킹이다. 해당 파일은 이번 변경에서 수정하지 않았다.
  해당 파일 재검사도 8개 통과·1개 동일 원인 실패로 확인했다. 전체 성공으로 보고하지 않는다.

## SDD 기록

로컬 설계·계획·GSD 상태와 코드맵을 갱신했다. 개인 아티팩트 저장소는
`Repository not found`로 원격 push에 실패해 로컬 체크포인트만 사용할 수 있다.

LLM 분류는 확률적이므로 모든 인젝션의 탐지를 보증하지 않는다. 읽기 전용 SQL,
Source 범위, 외부 접근 차단은 계속 실행 계층에서 강제한다. Gemini 경로는
공통 어댑터 자동 테스트로 검증했고 실제 라이브 호출은 Bedrock으로 수행했다.
