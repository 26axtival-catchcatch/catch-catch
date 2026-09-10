# 캐치캐치 프론트엔드 설계 v2

`catch-catch/frontend` 에 **지금 구현되어 있는 것**을 기준으로 다시 쓴 정본 문서입니다.
이 문서 묶음만 읽으면 다른 LLM·다른 세션에서 **처음부터 다시 만들거나**, **이어서
만들 수 있도록** 구성했습니다.

- 기준 시점: **2026-09-09**
- 기준 커밋: `db5e1e1` (`feat: (frontend) 브리핑 메인 화면을 컴포넌트로 준비함`)
- 상태: **Mock 구동 · 백엔드 미연결** (백엔드는 별도로 동작하지만 새 화면은 아직 붙지 않음)

> v1 문서인 `docs/화면 설계서.md` 는 기준 커밋 `2af266e` 의 상태를 담고 있습니다.
> 그 뒤로 결과 화면 구조, 로딩 화면, 메인 화면이 바뀌었습니다. v1 은 **역사 기록으로
> 보존**하고, 앞으로의 작업은 이 v2 문서를 갱신합니다. 두 문서가 충돌하면 v2 가 정본입니다.

---

## 문서 구성

| 문서 | 무엇이 들어 있나 | 언제 읽나 |
| --- | --- | --- |
| [01 제품·UX 기획안](01-product-and-ux-brief.md) | 서비스 정의, 사용자, 설계 원칙, 심사 배점 대응, 화면 서사 | **항상 먼저** |
| [02 아키텍처와 상태 계약](02-architecture-and-contracts.md) | 라우트, phase 머신, 타입 계약 전문, 파일 구조 | 코드를 쓰기 직전 |
| [03 화면 명세](03-screen-specs.md) | 6개 화면의 구조·동작·연출·문구 | 화면 하나를 만들 때 |
| [04 디자인 시스템](04-design-system.md) | 색·타이포·모션 토큰, 컴포넌트 규칙, 알려진 함정 | 스타일을 쓸 때 |
| [05 데이터와 백엔드 연결](05-data-and-backend.md) | Mock 데이터 계약, 백엔드 API·이벤트 매핑, 확인된 갭 | 데이터를 채울 때 / 실연결할 때 |
| [06 실행 프롬프트](06-build-prompts.md) | **처음부터 만들기 / 이어서 만들기 지시문** | 새 세션을 열 때 |

---

## 지금 무엇이 되어 있나 (30초 요약)

```
/                     SignalCatcherApp        ← 새 화면 전부. Mock 으로 구동
/legacy               CustomerIntelligencePage ← 동료의 기존 Working Demo. 백엔드 실연결
```

화면은 라우트가 아니라 `session.phase` 로 갈립니다.

| phase | 화면 | 상태 |
| --- | --- | --- |
| `ask` | **브리핑**(`?main=briefing`) 또는 **질문하기**(기본) | 둘 다 구현. 기본값은 질문하기 |
| `catching` | 캐치하는 중 (심박 + 진행 레일 + 심문 모달) | 구현 |
| `result` | 캐치 결과 (헤드라인 → 여정 맵 → 발견/액션 → 과정 보기) | 구현 |
| `trace` | 검증 기록 (스코어카드 + 주장별 근거 계보) | 구현 |
| `action` | 액션 (미리보기 → 관찰 → 채점 리포트) | 구현 |

- 데이터는 전부 `state/mock.ts`, `state/action-mock.ts`, `briefing/briefing-mock.ts` 입니다.
- 진행은 `setTimeout` 체인입니다. SSE 가 아닙니다.
- **signal-catcher 에는 자동 테스트가 없습니다.** vitest 95개와 e2e 는 전부 `/legacy` 대상입니다.
- `next.config.ts` 는 `output: "export"` 입니다. `next build` 가 `out/` 에 정적 파일만 떨굽니다.

남은 큰 작업은 하나입니다 — **백엔드 실연결**([05](05-data-and-backend.md) §4).

---

## 검증 명령

```bash
npm --prefix frontend run typecheck
npm --prefix frontend test -- --run          # 95개 (legacy 대상)
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 npm --prefix frontend run build
```

화면을 눈으로 확인할 때:

```bash
npm --prefix frontend run dev                # http://127.0.0.1:3000
```

시연용 URL 스위치는 [03 §7](03-screen-specs.md) 에 정리되어 있습니다.
