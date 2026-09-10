# 해커톤 발표 자료

현재 발표 자료는 12장입니다. 편집 원본은 기존 파일명인
`presentation-hackathon-10pages.html`을 유지합니다.

## 발표 영상

| 슬라이드 | 영상 | 길이 |
| --- | --- | --- |
| 6장 | 질문부터 고객 여정과 근거 확인까지, 최신 수정본 2배속 | 1분 0.5초 |
| 7장 | 동일한 시연 실행의 Langfuse 트레이스 | 8초 반복 |
| 8장 | 시그널 등록부터 알림과 지표 추적까지, 최신 수정본 2배속 | 51.5초 |

슬라이드에 진입하면 해당 영상이 처음부터 자동 재생됩니다.
다른 장으로 이동하면 정지하고 재생 위치를 초기화합니다.
자동 재생이 제한된 브라우저에서는 영상의 재생 버튼을 누르면 됩니다.
영상 컨트롤에서 일시 정지, 탐색과 전체 화면을 사용할 수 있습니다.
영상이 이미 2배속 파일이므로 재생 속도는 기본 1배속으로 둡니다.

Langfuse 영상은 시연 실행 `14c4a166-47d8-45e2-a63a-b8478667e3f9`의
실행 트리, 타임라인, 그래프 확대와 coordinator의 입력 및 결과를 담았습니다.
로그인 이후부터 촬영했습니다. 인증 정보는 HTML이나 미디어에 포함하지 않습니다.
촬영 원본과 기존 편집본은 로컬 `.local/recordings/`에 보존합니다.
공개 가능한 실행 정보, 원본 선택 구간과 파일 해시는 `presentation-media.json`에 있습니다.

## 정적 서빙

Next 서버를 빌드하고 배포하면 `/presentation`에서 발표 자료를 엽니다.
특정 장은 `/presentation#6`, `/presentation#7`, `/presentation#8`로 열 수 있습니다.
`/presentation/`와 `/presentation/index.html`도 사용할 수 있습니다.

`frontend/public/presentation/index.html`과 같은 폴더의 이미지 및 영상을 서빙합니다.
`next.config.ts`의 rewrite가 `/presentation` 요청을 정적 HTML로 연결합니다.
영상은 같은 서버의 MP4 파일이므로 Langfuse 로그인이나 서버 연결 없이 재생됩니다.
기존 Frontend Dockerfile이 `public`을 복사하므로 배포 설정을 추가할 필요가 없습니다.

HTML 원본이나 `ppt`의 이미지를 수정한 뒤에는 저장소 루트에서 실행합니다.

```bash
node scripts/sync-presentation.mjs
```

또는 `frontend`에서 `npm run presentation:sync`를 실행합니다.
갱신된 `frontend/public/presentation/`도 함께 커밋합니다.
영상 교체는 이 폴더의 `media/` 파일을 바꾸고 HTML 경로와 포스터를 맞추면 됩니다.
배포 빌드는 커밋된 정적 파일을 사용하며 별도 동기화나 원본 촬영 파일을 요구하지 않습니다.

## 확인한 항목

- Frontend 타입 검사와 프로덕션 빌드
- Next standalone 서버의 HTML, 이미지와 MP4 응답
- 세 영상의 `Range` 요청 `206` 응답과 재생 시간
- 브라우저에서 6장, 7장, 8장 재생과 장 이동 시 정지
- 10장과 11장의 기존 이미지 로드
- 8초 편집 영상 전체 디코딩과 두 2배속 파일의 원본 해시 일치
