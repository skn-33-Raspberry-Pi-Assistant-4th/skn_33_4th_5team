# PiCare CI/CD 실행·설정·API 명세서

> 대상: PiCare를 처음 배포하거나 운영하는 팀원  
> 최종 확인: GitHub Actions → ECR → AWS Systems Manager(SSM) → EC2 자동 배포 성공

이 문서는 `main` 브랜치에 코드를 올렸을 때 웹 서버가 자동으로 갱신되는 과정을 처음부터 설명한다. 비밀값은 절대로 Git, 문서, 채팅에 기록하지 않는다.

---

## 1. 한눈에 보는 구조

```text
개발자 PC
  └─ git push origin main
       └─ GitHub Actions
            ① Django/원격 AI 계약 테스트
            ② Linux(amd64) Docker 이미지 빌드
            ③ Amazon ECR에 sha-커밋해시 태그로 업로드
            ④ AWS SSM 명령 전달
                 └─ EC2 (/opt/picare)
                      ⑤ ECR 이미지 pull
                      ⑥ Django + Nginx 컨테이너 교체
                      ⑦ /health/ 헬스체크

사용자 브라우저 → EC2 Elastic IP:80 → Nginx → Django
                                           └─ HTTPS → RunPod AI API
                                                     └─ GPU/RAG/LoRA 런타임
```

| 구성 요소 | 역할 | 현재 값/형식 |
| --- | --- | --- |
| GitHub Actions | 테스트·이미지 빌드·자동 배포 실행 | `.github/workflows/aws-cicd.yml` |
| ECR | 웹 Docker 이미지 저장소 | `picare-web-kimqq` |
| EC2 | Django/Nginx 운영 서버 | `aws-picare` |
| SSM | GitHub Actions에서 EC2에 안전하게 명령 전달 | SSH 수신 규칙 불필요 |
| RDS MySQL | 운영 데이터베이스 | `aws-picare-mysql` |
| RunPod | GPU AI 작업 큐·RAG·LoRA 서버 | RunPod HTTPS Proxy URL |

## 2. 배포가 시작되는 조건

워크플로 파일은 [`.github/workflows/aws-cicd.yml`](../../.github/workflows/aws-cicd.yml)이다.

| 이벤트 | 테스트 | ECR 업로드/EC2 배포 |
| --- | --- | --- |
| `main` 대상 Pull Request | 실행 | 실행 안 함 |
| `main` 브랜치 push | 실행 | 실행 |
| GitHub Actions의 **Run workflow** | 실행 | 실행 |

같은 시각에 두 배포가 겹치지 않도록 `picare-production` 동시 실행 잠금이 적용되어 있다. 먼저 시작한 배포가 끝난 뒤 다음 배포가 이어서 진행된다.

---

## 3. 최초 1회 설정

### 3.1 EC2 준비 상태

EC2에는 아래가 준비되어 있어야 한다.

- Docker 및 Docker Compose v2
- AWS CLI v2
- `/opt/picare/deploy/compose.aws.yaml`
- `/opt/picare/deploy/aws-release.sh`
- `/opt/picare/deploy/nginx.aws.conf`
- `/opt/picare/.env` (권한 `600`)
- 인스턴스 역할 `aws-picare-ec2-ecr-pull-role`

인스턴스 역할에는 아래 두 정책이 연결되어야 한다.

| 정책 | 용도 |
| --- | --- |
| `aws-picare-ecr-pull-policy` | EC2가 ECR의 운영 이미지를 pull |
| `AmazonSSMManagedInstanceCore` | SSM이 EC2에 명령을 전달 |

AWS 콘솔에서 **Systems Manager → Fleet Manager → Managed nodes**로 이동해 `aws-picare`가 **Online**인지 확인한다. Offline이면 EC2에 SSH 접속 후 아래를 실행한다.

```bash
sudo systemctl status snap.amazon-ssm-agent.amazon-ssm-agent.service --no-pager
sudo snap restart amazon-ssm-agent
```

### 3.2 EC2의 `.env` 만들기

EC2에서 한 번만 실행한다.

```bash
cd /opt/picare
cp deploy/aws.env.example .env
chmod 600 .env
nano .env
```

아래 항목만 실제 값으로 바꾼다. `AI_API_TOKEN`, `DJANGO_SECRET_KEY`, `DJANGO_DB_PASSWORD`는 서로 다른 비밀값이다.

```dotenv
PICARE_AI_BACKEND=remote
AI_API_URL=https://<runpod-pod-id>-8000.proxy.runpod.net
AI_API_TOKEN=<32자-이상의-RunPod-공유-토큰>

DJANGO_DEBUG=false
DJANGO_SECRET_KEY=<Django-전용-비밀키>
DJANGO_ALLOWED_HOSTS=<EC2-Elastic-IP>,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=http://<EC2-Elastic-IP>

DJANGO_DB_ENGINE=django.db.backends.mysql
DJANGO_DB_NAME=picare
DJANGO_DB_USER=picare_app
DJANGO_DB_PASSWORD=<RDS-picare_app-비밀번호>
DJANGO_DB_HOST=<RDS-엔드포인트>
DJANGO_DB_PORT=3306
```

편집 후 비밀값 자체는 출력하지 말고, 빈 값만 없는지 확인한다.

```bash
grep -E '^(AI_API_URL|DJANGO_DB_HOST|DJANGO_DB_NAME)=' .env
```

### 3.3 GitHub Secrets 및 Variables

GitHub 저장소에서 **Settings → Secrets and variables → Actions**로 이동한다.

#### Secrets 탭

| Name | 등록할 값 | 주의 |
| --- | --- | --- |
| `AWS_ACCESS_KEY_ID` | 배포 권한을 가진 IAM 사용자의 Access Key ID | 공개 금지 |
| `AWS_SECRET_ACCESS_KEY` | 위 Access Key의 Secret Access Key | 한 번만 표시되는 값, 공개 금지 |

#### Variables 탭

| Name | 값 |
| --- | --- |
| `AWS_REGION` | `ap-northeast-2` |
| `AWS_ACCOUNT_ID` | AWS 계정 ID |
| `ECR_REPOSITORY` | `picare-web-kimqq` |
| `EC2_INSTANCE_ID` | 운영 EC2 인스턴스 ID |

> GitHub Secrets는 화면에 값을 다시 표시하지 않는다. Secret을 잃어버렸다면 새 Access Key를 만든 뒤 GitHub Secret과 로컬 AWS 프로필을 함께 교체한다.

### 3.4 GitHub 배포용 IAM 권한

현재 테스트 목적의 관리자 권한 IAM 사용자는 동작하지만, 운영에서는 GitHub Actions 전용 IAM 사용자를 권장한다. 전용 사용자는 ECR push 권한과 아래 SSM 권한을 가져야 한다.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ssm:SendCommand",
      "Resource": [
        "arn:aws:ssm:ap-northeast-2::document/AWS-RunShellScript",
        "arn:aws:ec2:ap-northeast-2:<ACCOUNT_ID>:instance/<EC2_INSTANCE_ID>"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "ssm:GetCommandInvocation",
      "Resource": "*"
    }
  ]
}
```

ECR push 권한은 기존 `aws-picare-ecr-push-policy`와 동일하거나 그보다 최소 권한으로 별도 부여한다. `ACCOUNT_ID`, `EC2_INSTANCE_ID`는 실제 값으로 치환한다.

---

## 4. 매일 사용하는 자동 배포 방법

### 방법 A: `main`에 푸시하기 (권장)

변경 사항을 검토한 뒤 다음을 실행한다.

#### macOS/Linux Bash

```bash
cd /Users/<사용자명>/SK_AI/skn_33_4th_5team
git status
git add <변경한-파일>
git commit -m "feat: 설명"
git push origin main
```

#### Windows PowerShell

```powershell
Set-Location "C:\Users\<사용자명>\SK_AI\skn_33_4th_5team"
git status
git add <변경한-파일>
git commit -m "feat: 설명"
git push origin main
```

### 방법 B: 이미 올라간 커밋을 수동 배포하기

1. GitHub 저장소의 **Actions** 탭을 연다.
2. 왼쪽 **AWS CI/CD**를 선택한다.
3. 오른쪽 **Run workflow**를 누른다.
4. 대상 브랜치를 `main`으로 선택하고 **Run workflow**를 누른다.

### 성공 여부 확인

GitHub **Actions → AWS CI/CD**에서 최신 실행을 열어 아래 두 작업이 모두 초록 체크인지 확인한다.

```text
✓ Test and validate deployment image
✓ Publish and release to EC2
```

두 번째 작업까지 성공하면 ECR 업로드, SSM 명령 실행, EC2 컨테이너 헬스체크가 모두 끝난 상태다. 배포 이미지는 `sha-<커밋해시>` 태그로 기록된다.

---

## 5. EC2에서 운영 상태 확인

### 웹 서비스 확인

브라우저에서 아래 주소를 연다.

```text
http://<EC2-Elastic-IP>/
http://<EC2-Elastic-IP>/health/
```

정상 준비 상태 예시:

```json
{
  "status": "ok",
  "ready": true,
  "message": "RunPod AI 서비스가 준비되었습니다."
}
```

### SSH에서 확인하기

```bash
ssh -i ~/Downloads/picare-key.pem ubuntu@<EC2-Elastic-IP>
cd /opt/picare
docker compose --project-name picare-aws -f deploy/compose.aws.yaml ps
docker compose --project-name picare-aws -f deploy/compose.aws.yaml logs --tail 100 web
curl -fsS http://127.0.0.1/health/
```

`web`, `nginx`가 모두 `healthy`면 정상이다.

### 현재 또는 이전 이미지 확인

```bash
cd /opt/picare
cat deploy/release.env
cat deploy/previous-release.env 2>/dev/null || true
```

### 롤백

문제가 있으면 `previous-release.env`의 이미지 태그를 확인하고 아래처럼 이전 태그를 명시한다.

```bash
cd /opt/picare
bash deploy/aws-release.sh <이전-sha-태그> <AWS_ACCOUNT_ID> picare-web-kimqq
```

예: `sha-` 뒤의 태그는 ECR 또는 `deploy/previous-release.env`에서 확인한다. `latest`는 사용하지 않는다.

---

## 6. API 명세

PiCare의 AI 처리 API는 공개 브라우저 API가 아니라 **EC2 Django 서버와 RunPod 간 내부 연동 API**다. RunPod URL 및 토큰을 프론트엔드 코드에 넣지 않는다.

### 6.1 공통 규칙

| 항목 | 규칙 |
| --- | --- |
| Base URL | `https://<runpod-pod-id>-8000.proxy.runpod.net` |
| 인증 | 작업 API는 `Authorization: Bearer <AI_API_TOKEN>` |
| 요청/응답 | `application/json` |
| 작업 종류 | `qa`, `recommendation`, `quiz` |
| 작업 상태 | `queued`, `running`, `cancelling`, `succeeded`, `failed`, `cancelled`, `expired` |
| 동시성 | GPU 작업은 단일 worker에서 순차 실행 |
| 기본 대기 큐 | 최대 8개 (`AI_MAX_QUEUED`) |
| 기본 작업 제한 | 300초 (`AI_JOB_TIMEOUT`) |
| 결과 보관 | 1,800초 (`AI_RESULT_RETENTION`) |

### 6.2 RunPod 준비 상태

#### `GET /health/live`

HTTP 프로세스가 살아 있는지만 확인한다. 인증이 필요 없다.

```bash
curl -fsS "https://<runpod-host>/health/live"
```

응답:

```json
{"live": true}
```

#### `GET /health/ready`

모델·인덱스·작업 큐까지 준비되었는지 확인한다. 운영 확인에는 이 API를 사용한다.

```bash
curl -fsS "https://<runpod-host>/health/ready"
```

응답:

```json
{
  "ready": true,
  "message": "Qwen·LoRA·Hybrid RAG 런타임 준비 완료"
}
```

`ready: false`는 Pod가 막 시작되어 모델이나 검색 인덱스를 로딩 중이거나, 런타임 준비에 실패했음을 뜻한다.

### 6.3 AI 작업 생성

#### `POST /v1/jobs`

| 항목 | 값 |
| --- | --- |
| 인증 | 필요 |
| Body | `job_id`, `kind`, `payload` |
| 성공 | `200` |
| 실패 | `401`, `409`, `422`, `429`, `503` |

`job_id`는 영문·숫자·`_`·`-`만 허용하며 최대 120자다. 같은 ID와 같은 요청을 다시 보내면 기존 작업 상태를 돌려주는 멱등 요청이다. 같은 ID에 다른 내용으로 요청하면 `409 job_conflict`다.

```bash
curl -X POST "https://<runpod-host>/v1/jobs" \
  -H "Authorization: Bearer <AI_API_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "job_id": "sample_job_001",
    "kind": "qa",
    "payload": {
      "question": "라즈베리파이 GPIO란 무엇인가요?",
      "retrieval_mode": "hybrid",
      "trace": true
    }
  }'
```

PowerShell 예시:

```powershell
$headers = @{ Authorization = "Bearer <AI_API_TOKEN>"; "Content-Type" = "application/json" }
$body = @{
  job_id = "sample_job_001"
  kind = "qa"
  payload = @{ question = "라즈베리파이 GPIO란 무엇인가요?"; retrieval_mode = "hybrid"; trace = $true }
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri "https://<runpod-host>/v1/jobs" -Headers $headers -Body $body
```

응답 형식:

```json
{
  "job_id": "sample_job_001",
  "kind": "qa",
  "status": "queued"
}
```

### 6.4 AI 작업 상태 조회

#### `GET /v1/jobs/{job_id}`

```bash
curl -fsS "https://<runpod-host>/v1/jobs/sample_job_001" \
  -H "Authorization: Bearer <AI_API_TOKEN>"
```

성공 완료 예시:

```json
{
  "job_id": "sample_job_001",
  "kind": "qa",
  "status": "succeeded",
  "result": {"answer": "..."}
}
```

없는 작업은 `404 job_not_found`, 런타임이 준비되지 않았으면 `503 runtime_not_ready`가 반환된다.

### 6.5 AI 작업 취소

#### `POST /v1/jobs/{job_id}/cancel`

```bash
curl -X POST "https://<runpod-host>/v1/jobs/sample_job_001/cancel" \
  -H "Authorization: Bearer <AI_API_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{}'
```

대기 상태 작업은 즉시 `cancelled`, 실행 중 작업은 `cancelling` 상태가 된 뒤 협력 취소된다.

### 6.6 Django 공개 헬스 API

#### `GET /health/`

외부 사용자가 호출해도 되는 상태 확인 API다. RunPod 토큰·URL·내부 오류는 노출하지 않는다.

```bash
curl -fsS "http://<EC2-Elastic-IP>/health/"
```

| 상태 | 의미 |
| --- | --- |
| `status: "ok", ready: true` | 웹·RunPod 연동 정상 |
| `status: "not_ready", ready: false` | 웹은 동작하나 RunPod 준비/연결 문제 |

---

## 7. 장애 대응표

| 증상 | 가장 먼저 확인할 곳 | 조치 |
| --- | --- | --- |
| GitHub Actions 테스트 실패 | Actions의 빨간 job 로그 | 코드/테스트 오류를 수정 후 새 커밋 push |
| `Credentials could not be loaded` | GitHub Secrets | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` 이름·값 확인 |
| SSM `InvalidInstanceId` 또는 timeout | Fleet Manager | 운영 EC2가 Online인지, 역할에 `AmazonSSMManagedInstanceCore`가 있는지 확인 |
| ECR pull 권한 오류 | EC2 인스턴스 역할 | `aws-picare-ecr-pull-policy` 확인 |
| 컨테이너 `unhealthy` | EC2 Docker logs | `docker compose ... logs --tail 100 web` 실행, `.env`의 DB/RunPod 값 점검 |
| `/health/`가 `not_ready` | RunPod `/health/ready` | 모델 로딩 대기, Pod 실행 상태·토큰·Proxy URL 확인 |
| `401 authentication_failed` | EC2 `.env`, RunPod 환경 변수 | 양쪽 `AI_API_TOKEN`이 동일한지 확인 |
| `429 queue_full` | RunPod 작업량 | 기존 작업 완료/취소 후 재시도, 필요 시 `AI_MAX_QUEUED` 조정 |
| `manifest_v3.json`이 GitHub CI에서 없음 | GitHub test 로그 | RunPod 전용 모델/인덱스 파일은 Git에 넣지 않는다. CI에서는 `tests/test_deployment_assets.py`와 `verify_deployment_assets.py`를 실행하지 않는다. 실제 RunPod 준비는 `/health/ready`로 확인한다. |

---

## 8. 보안 체크리스트

- [ ] `.env`, `*.pem`, AWS Secret Access Key, RunPod 토큰은 Git에 커밋하지 않았다.
- [ ] GitHub에는 민감 값은 **Secrets**, 계정 ID/리전 같은 공개 가능 값은 **Variables**에 넣었다.
- [ ] EC2의 `/opt/picare/.env` 권한은 `600`이다.
- [ ] RDS는 Public access가 꺼져 있고, RDS 보안 그룹은 EC2 보안 그룹에서 오는 MySQL 3306만 허용한다.
- [ ] RunPod 작업 API는 Bearer 토큰 없이 호출되지 않는다.
- [ ] 배포 이미지는 `latest`가 아닌 불변 `sha-<commit>` 태그를 사용한다.
- [ ] GitHub Actions 전용 IAM 사용자/키로 단계적으로 분리한다.

## 9. 운영자가 기억할 명령어

```bash
# GitHub Actions가 아닌 EC2에서 특정 이미지 수동 재배포
cd /opt/picare
bash deploy/aws-release.sh <sha-태그> <AWS_ACCOUNT_ID> picare-web-kimqq

# EC2 컨테이너 상태
docker compose --project-name picare-aws -f deploy/compose.aws.yaml ps

# 웹 로그
docker compose --project-name picare-aws -f deploy/compose.aws.yaml logs --tail 100 web

# RunPod 준비 상태
curl -fsS "https://<runpod-host>/health/ready"

# Django와 RunPod 통합 상태
curl -fsS "http://127.0.0.1/health/"
```

---

## 10. 관련 문서

- [AWS 인프라 스펙 발표용](AWS-인프라-스펙-발표용.md)
- [이전 배포 문서 보관함](../archive/deployment/README.md)
