# 브라우저 시그널 알림 검증

검증일은 2026년 9월 10일입니다. 등록 화면에서 기준을 저장한 시그널을 다음 날의 실제
Source 데이터로 측정하고, 기존 폴링에서 받은 이벤트를 브라우저 네이티브 알림으로 표시합니다.

프론트 단위 테스트 **132개**, 데스크톱과 모바일 E2E **6개**, TypeScript 검사와
프로덕션 빌드를 통과했습니다. 네이티브 알림 전달 모듈의 마지막 변경 뒤 관련 단위 테스트
13개도 다시 통과했습니다. 화면 확인에서 발견한 알림함과 상세 모달의 겹침은 수정 후
최종 E2E에 포함했습니다. 로컬 캡처와 실행 로그는 `data/live-validation/browser-notifications/`에
저장했습니다.

## 실행 흐름

1. 최초 질의 기간은 한국 시각 9월 4일 00:00부터 9월 11일 00:00까지
2. 결과 화면의 `변화 캐치 맡기기`에서 대상 고객 수 기준을 1명으로 저장
3. 상단 `하루 빨리감기`로 9월 11일 하루의 실제 SQL 실행
4. 대상 고객 28명, 모집단 50명, 비율 56% 확인
5. 같은 측정 ID에 연결된 알림 이벤트 1개와 실제 `showNotification()` 호출 확인
6. 서비스 워커의 알림 클릭 핸들러에서 해당 시그널 상세와 측정 이력 조회

비율은 부동소수점 계산 결과를 허용 오차로 비교합니다. 화면에서는 56%로 표시합니다.
네이티브 알림 본문은 `대상 고객 수 28명`입니다.

## 확인한 계약

| 항목 | 검증 방식 |
| --- | --- |
| 실제 일자 분석 | Fast-forward 응답의 한국 시각 9월 11일 범위, SQL 측정값과 이벤트의 측정 ID 대조 |
| 브라우저 알림 | 전체 Chromium에서 권한 허용 후 실제 서비스 워커의 `getNotifications()` 조회 |
| 여러 탭 중복 방지 | 두 탭이 이벤트를 받고 실제 `showNotification()` 호출은 한 번 |
| 새로고침 중복 방지 | 저장된 순번 유지, 네이티브 재표시 없음 |
| 알림 클릭 | 실제 워커에 `notificationclick` 이벤트 전달 후 해당 시그널 상세 표시 |
| 권한 거절 | 네이티브 권한이 `denied`여도 알림함과 상세에 SQL 측정 결과 도착 |
| 응답 유실 | 실제 서버 완료 후 첫 HTTP 응답만 유실, 새로고침 후 같은 UUID로 재시도 |
| 날짜 중복 방지 | 재시도 이후 일별 실행 1개와 동일한 측정 ID 유지 |
| 작은 화면 | 375px 모바일 화면에서 가로 스크롤 없음, 열린 알림함이 상세를 가리지 않음 |
| 네이티브 API 실패 | 표시 예외와 무관하게 폴링 커서와 앱 안의 알림함 유지 |

최초 fixture Run은 실제 HTTP로 완료합니다. fixture planner에는 SQL 후보 생성이 없어,
같은 기간과 승인된 합성 Source를 실제 SQL로 측정한 후보를 테스트 준비 단계에서 저장합니다.
등록과 알림 조건 저장, 일별 측정과 이벤트 생성에는 실제 API를 사용합니다.
네이티브 메서드는 호출 횟수만 관찰하며 원래 브라우저 구현을 그대로 실행합니다.

운영체제 배너 자체를 마우스로 누르는 과정은 자동화하지 않았습니다. 브라우저 알림 저장과
실제 클릭 핸들러를 검증했습니다. 모바일 검증은 Chromium의 375px 기기 에뮬레이션이며,
iOS와 Android 실기기 검증을 뜻하지 않습니다. 이번 검증에서 새 외부 LLM 호출은 없습니다.

## 재현 명령

```sh
npm --prefix frontend test -- --run
npm --prefix frontend run typecheck
npm --prefix frontend run build

ONBOARDED_SOURCES_DIR="$PWD/data/investigation-demo-sources" \
SIGNAL_SCHEDULER_ENABLED=false \
E2E_BACKEND_PORT=38121 E2E_FRONTEND_PORT=33121 \
npm --prefix frontend run e2e -- signal-notifications.spec.ts
```

별도 포트와 Backend 저장소, `.next-e2e-<port>` 출력 폴더를 사용합니다.
Playwright 기본 Headless Shell은 이 환경에서 네이티브 알림 권한을 거부하므로,
이 테스트 파일만 `channel: "chromium"`으로 실행합니다.
[Playwright의 전체 Chromium headless 모드](https://playwright.dev/docs/browsers#chromium-new-headless-mode)를 사용합니다.

## 사용 범위

앱이 열린 동안 기존 폴링으로 새 이벤트를 받습니다. 모든 탭이 닫힌 뒤의 서버 Web Push는
구현 범위에 포함하지 않습니다. HTTPS 또는 localhost 계열과 브라우저 알림 권한이 필요합니다.
운영체제의 알림 설정에 따라 브라우저가 수락한 알림도 배너로 보이지 않을 수 있습니다.

사용 흐름과 데이터가 없는 날짜의 동작은 [FE 연결 문서](../signal-fast-forward-fe-handoff.md)에
정리했습니다. Backend 단독 검증은 [빨리감기 검증 기록](signal-fast-forward.md)에 있습니다.
