# PiCare AWS 수동 배포 — RDS + Docker Compose

이 문서는 PiCare 원본 저장소를 AWS에 **수동으로** 배포하는 절차다. GitHub Actions, OIDC, SSM 자동 배포는 포함하지 않는다.

## 구성

```text
브라우저 ── HTTP :80 ──> EC2 Elastic IP / Nginx ──> Django + Gunicorn
                                                    │
                                                    ├──> 비공개 RDS MySQL
                                                    └──> RunPod AI API (HTTPS)
Mac ── buildx linux/amd64 ──> ECR ── pull ──> EC2
```

- EC2: Ubuntu 24.04, `t3.small`, Elastic IP 연결
- RDS: MySQL 8.4, `db.t4g.micro`, Single-AZ, gp3 20 GiB, 퍼블릭 액세스 비활성화
- ECR 저장소 예시: `picare-web-kimqq`
- 공개 포트: EC2 보안 그룹의 HTTP `80`만 공개한다. SSH `22`는 관리자 IP만 허용하고, `8000`과 `3306`은 외부에 열지 않는다.
- RDS 보안 그룹의 MySQL `3306` 인바운드는 **PiCare EC2 보안 그룹만** 허용한다.

이 Compose 프로필은 Nginx와 Django만 실행한다. GPU 모델, LoRA, Chroma 인덱스는 RunPod에 두고 EC2 이미지에 넣지 않는다.

## 1. AWS 준비

1. 서울 리전(`ap-northeast-2`)에서 ECR 비공개 저장소를 만든다.
2. 같은 VPC에 EC2와 RDS를 만든다. EC2에는 ECR 읽기 권한이 있는 인스턴스 역할을 붙인다.
3. EC2에 Elastic IP를 연결한다.
4. RDS 마스터 계정으로 접속해 빈 앱 DB와 전용 계정을 만든다. 비밀번호는 실제 강한 값으로 교체한다.

```sql
CREATE DATABASE picare CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'picare_app'@'%' IDENTIFIED BY 'replace-with-a-strong-password';
GRANT ALL PRIVILEGES ON picare.* TO 'picare_app'@'%';
FLUSH PRIVILEGES;
```

이번 HTTP 검수 단계에서는 Django-RDS TLS 강제를 적용하지 않는다. RDS 퍼블릭 액세스를 끄고 VPC/보안 그룹으로 접근을 격리한다. 도메인과 HTTPS는 후속 단계에서 적용한다.

## 2. EC2 초기 준비

EC2에 Docker Engine, Docker Compose 플러그인, AWS CLI v2, Git, curl을 설치한다. 앱을 둘 경로에서 원본 저장소를 내려받는다.

```bash
git clone <PiCare-repository-url> ~/picare
cd ~/picare
cp deploy/aws.env.example .env
chmod 600 .env
```

`.env`에는 다음 값을 실제 값으로 채운다. 이 파일은 절대 Git에 올리지 않는다.

```dotenv
PICARE_AI_BACKEND=remote
AI_API_URL=https://<runpod-endpoint>
AI_API_TOKEN=<shared-runpod-token>
DJANGO_SECRET_KEY=<django-secret>

DJANGO_ALLOWED_HOSTS=<elastic-ip>,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=http://<elastic-ip>
DJANGO_SESSION_COOKIE_SECURE=false
DJANGO_CSRF_COOKIE_SECURE=false
DJANGO_SECURE_SSL_REDIRECT=false

DJANGO_DB_ENGINE=django.db.backends.mysql
DJANGO_DB_NAME=picare
DJANGO_DB_USER=picare_app
DJANGO_DB_PASSWORD=<rds-app-password>
DJANGO_DB_HOST=<rds-endpoint>
DJANGO_DB_PORT=3306
```

RunPod `/health/ready`가 `{"ready": true}`를 반환하는 상태에서 배포한다. 웹의 `/health/`는 이 원격 준비 상태를 기준으로 성공 여부를 반환한다.

## 3. Mac에서 이미지 빌드 및 ECR 업로드

Apple Silicon Mac에서도 EC2와 같은 아키텍처로 실행되도록 `linux/amd64` 이미지를 만든다.

```bash
cd /path/to/skn_33_4th_5team
bash deploy/aws-build-push.sh manual-v1 <AWS_ACCOUNT_ID> picare-web-kimqq
```

스크립트는 `Dockerfile.aws`를 사용하며 `.dockerignore`에 의해 로컬 GPU 모델, Chroma 인덱스, 파인튜닝 데이터는 이미지에서 제외된다. 제품 카탈로그와 인용 문서 데이터는 유지된다.

## 4. EC2에서 릴리스

업로드한 태그로 EC2에서 실행한다.

```bash
cd ~/picare
bash deploy/aws-release.sh manual-v1 <AWS_ACCOUNT_ID> picare-web-kimqq
```

릴리스 스크립트는 다음을 순서대로 수행한다.

1. ECR 로그인과 이미지 pull
2. Django migration 실행 및 Nginx/Django Compose 기동
3. Nginx를 통한 `/`, `/accounts/login/`, `/health/` 점검
4. 현재 ECR 이미지 태그를 `deploy/release.env`에 기록

외부 Elastic IP로 검수할 때는 다음처럼 실행한다.

```bash
PUBLIC_BASE_URL=http://<elastic-ip> \
  bash deploy/aws-release.sh manual-v1 <AWS_ACCOUNT_ID> picare-web-kimqq
```

## 5. 검수와 롤백

브라우저에서 `http://<elastic-ip>/`를 열어 CSS와 정적 자산이 보이는지 확인한다. 이어서 회원가입, 로그인, 커뮤니티 글/댓글 저장으로 RDS 읽기/쓰기를 확인하고, Q&A·제품 추천·미니 챌린지를 각각 실행해 RunPod 연동을 확인한다.

이전 이미지로 되돌릴 때는 이전 태그를 지정해 같은 명령을 다시 실행한다.

```bash
bash deploy/aws-release.sh <previous-tag> <AWS_ACCOUNT_ID> picare-web-kimqq
```

`deploy/previous-release.env`에는 직전 배포 이미지가 기록되므로, 해당 파일의 `PICARE_WEB_IMAGE` 태그를 확인해 롤백 태그로 사용한다.

## 운영 유의사항

- `deploy/release.env`, `deploy/previous-release.env`, 루트 `.env`는 Git 추적 대상이 아니다.
- EC2 IAM 역할은 ECR pull 권한만 가진다. GitHub OIDC와 SSM 권한은 CI/CD 단계에서 별도 구성한다.
- `GUNICORN_WORKERS=1`은 `t3.small` 기준의 안전한 시작값이다. 실제 트래픽과 메모리를 관찰한 뒤 조정한다.
