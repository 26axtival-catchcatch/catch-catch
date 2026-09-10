# AWS 해커톤 배포와 재배포

EC2가 공개 GitHub 저장소에서 직접 소스를 받아 FE, BE, Langfuse를 실행합니다.
PC의 소스 묶음이나 `.env`는 전송하지 않습니다. Bedrock은 EC2 IAM 역할로 인증합니다.
서버는 `t3.xlarge`(4 vCPU, 16 GiB RAM), 암호화된 gp3 100 GiB 디스크를 사용합니다.

Langfuse 웹과 워커는 v3.225.7의 공식 이미지 digest로 고정합니다.
[공식 릴리스](https://github.com/langfuse/langfuse/releases/tag/v3.225.7)를 기준으로
2026-09-11에 확인한 v3 최신 정식 버전입니다.
Postgres, ClickHouse, Redis, MinIO 데이터는 Docker 볼륨에 유지합니다.

## 현재 접속 주소

| 서비스 | 주소 |
| --- | --- |
| 앱 | https://100.54.240.157 |
| 기존 분석 UI | https://100.54.240.157/legacy |
| Swagger | https://100.54.240.157/backend/docs |
| BE 상태 | https://100.54.240.157/backend/health |
| Langfuse | http://100.54.240.157:3210 |

Langfuse 표시 이름은 `4bit`, 로그인 ID는 `4bit@catchcatch.local`입니다.
관리자 비밀번호는 SSM `/catch-catch-hackathon/langfuse-admin-password`의 SecureString에서 읽습니다.
앱과 BE는 HTTPS로 공개합니다. 기존 HTTP 앱 주소는 HTTPS로 이동합니다.
HTTPS 주소에서 앱의 **브라우저 알림 켜기**를 누르고 브라우저 권한을 허용합니다.
브라우저 알림과 Service Worker를 지원하는 브라우저가 필요하며, 현재 알림은 앱이 열려 있는 동안 동작합니다.
Langfuse와 미디어 저장소의 기존 포트 및 주소는 유지합니다.

Caddy는 Let's Encrypt의 공인 IP 인증서(`shortlived`, 약 6일)를 발급하고 자동 갱신합니다.
인증서와 개인키는 서버의 `caddy-data` 볼륨에 저장하며 PC로 복사하지 않습니다.
인증서 발급과 갱신을 위해 TCP 80, HTTPS 접속을 위해 TCP 443을 열어 둡니다.
`deploy/aws-public-url.py`가 IMDSv2에서 공인 IP를 읽어 재배포 시 주소를 갱신합니다.
인증서 형식은 [Let's Encrypt 공식 안내](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability.html)를 참고합니다.

## 메인 재배포

먼저 변경을 GitHub의 `main`에 반영합니다.
AWS Systems Manager의 **자동화**에서 `CatchCatch-RedeployMain` 문서를 열고
**실행**을 누르면 추가 입력 없이 이 서버의 메인을 재배포합니다.
정의는 `deploy/aws-redeploy-document.json`이며 수동 실행 전용입니다.
Langfuse는 v3.225.7로 배포되어 있습니다. HTTPS 전환은 gateway에 적용하며 FE/BE 메인 코드의 재배포는 이 작업을 실행할 때 적용됩니다.

수동 명령으로 실행하려면 다음 절차를 사용합니다.
인앱 브라우저의 AWS 콘솔에서 리전을 `us-east-1`로 선택하고,
Systems Manager의 **명령 실행 → 명령 실행**을 엽니다.
문서는 `AWS-RunShellScript`, 대상은 `catch-catch-hackathon`
(`i-0ba6c57529146ac3d`) 한 대를 선택합니다. Execution Timeout은 1800초로 설정합니다.
Commands에 다음 내용을 입력하고 실행합니다.

```bash
set -eu
export HOME=/root
cd /opt/catch-catch
bash deploy/aws-redeploy.sh main
```

서버가 `main`을 fetch하고 해당 커밋을 checkout한 뒤 이미지를 빌드합니다.
컨테이너 주소가 바뀐 뒤에도 프록시가 연결되도록 gateway를 다시 시작하고 상태를 확인합니다.
출력에서 명령 성공, 배포 커밋, 컨테이너 상태를 확인합니다.
서버의 추적 파일에 미커밋 변경이 있으면 배포를 중단하며 강제로 덮어쓰지 않습니다.
동시에 실행한 다른 배포도 중단합니다. `.local/compose`와 데이터 볼륨은 유지합니다.

같은 소스를 다시 빌드할 때는 다음 명령을 사용합니다.

```bash
cd /opt/catch-catch
sh deploy/aws-compose.sh up --build -d
sh deploy/aws-compose.sh restart gateway
sh deploy/aws-compose.sh up -d --wait --wait-timeout 600
```

FE/BE 재시작 중에는 잠시 접속이 끊길 수 있고 실행 중인 분석은 중단될 수 있습니다.
필요한 분석이 끝난 뒤 실행합니다. EC2를 중지 후 시작하면 공인 IP가 바뀔 수 있습니다.

## 최초 설치와 검증

`deploy/aws-stack.json`은 EC2, 역할, 보안 그룹을 생성합니다.
`deploy/aws-bootstrap.sh`는 Docker를 설치하고 공개 저장소의 메인을 받습니다.
SSM에 관리자 비밀번호를 준비한 뒤 서버에서 `bash deploy/aws-prepare.sh`를 실행합니다.
이 스크립트는 서버에서 비밀번호와 프로젝트 키를 만들고 환경 파일을 권한 600으로 저장합니다.
Frontend에는 모델 및 trace 자격증명을 주입하지 않습니다. LangSmith는 별도 키 없이 비활성화합니다.

서버에서 `uv run --no-env-file --no-project --with httpx python scripts/verify-compose.py --mode fixture`와
`--mode bedrock`을 실행하면 합성 입력, SSE, 보고서 다운로드, 새 Langfuse trace를 검증합니다.
검증 결과는 `.local/compose/verification-*.json`에 공개 metadata만 기록합니다.

## 종료

`sh deploy/aws-compose.sh down`은 볼륨을 유지합니다. `down -v`는 데이터를 삭제하므로 사용하지 않습니다.
워크스페이스 종료 후 서버와 데이터가 사라질 수 있습니다. 별도 자동 삭제 예약은 설정하지 않았습니다.
수동 정리 시 `catch-catch-hackathon` CloudFormation 스택과 위 SSM 파라미터를 삭제합니다.
필요한 보고서는 워크스페이스 종료 전에 보관합니다.
