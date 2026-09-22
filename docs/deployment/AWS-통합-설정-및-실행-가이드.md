# PiCare AWS 통합 설정 및 실행 가이드

이 문서는 PiCare를 처음 AWS에 올리는 사람이 **AWS 콘솔 설정 → RunPod 연결 → ECR 이미지 업로드 → EC2 실행 → GitHub Actions 자동 배포**까지 따라 할 수 있도록 정리한 운영 가이드다.

비밀번호, `AWS_SECRET_ACCESS_KEY`, `AI_API_TOKEN`, Django Secret Key, PEM 개인키는 문서·Git·스크린샷·채팅에 저장하지 않는다. 아래에서 `<...>`로 보이는 값은 각자 실제 값으로 바꾼다.

## 0. 최종 구조와 역할

```text
사용자 브라우저
    │ HTTP :80
    ▼
Elastic IP → EC2 (Nginx → Django/Gunicorn)
                     │              │
                     │              └─ RDS MySQL :3306 (VPC 내부만)
                     │
                     └─ RunPod AI API :8000 (HTTPS + Bearer Token)

개발 PC → ECR (linux/amd64 이미지) → EC2가 Pull
GitHub Actions → ECR Push → SSM → EC2 릴리스
```

| 구성요소 | 담당 역할 | 외부 공개 여부 |
| --- | --- | --- |
| EC2 + Nginx | 웹 화면, 회원가입, 인증, 정적 파일 | HTTP 80 공개 |
| RDS MySQL | 사용자·게시글·추천 기록 | 비공개 |
| RunPod | Qwen/LoRA/RAG 기반 AI 추론 | RunPod 프록시 HTTPS만 EC2가 사용 |
| ECR | Django 웹 이미지 보관 | AWS IAM 인증 필요 |
| SSM | GitHub Actions가 EC2에 안전하게 배포 명령 전달 | 외부 SSH 불필요 |

## 1. 시작 전 메모할 값

먼저 아래 표를 개인 비밀 메모장 또는 팀 비밀 관리 도구에 채운다. `.env`와 IAM 키는 Git에 커밋하지 않는다.

```dotenv
# AWS 공통
AWS_REGION=ap-northeast-2
AWS_ACCOUNT_ID=<12자리 AWS 계정 ID>
VPC_ID=<vpc-...>
KEY_PAIR_NAME=picare-key

# EC2
EC2_INSTANCE_NAME=aws-picare
EC2_INSTANCE_ID=<i-...>
EC2_SECURITY_GROUP_ID=<sg-...>
EC2_SECURITY_GROUP_NAME=aws-picare-ec2-sg
ELASTIC_IP=<고정 공인 IPv4>
ELASTIC_IP_ALLOCATION_ID=<eipalloc-...>
EC2_AVAILABILITY_ZONE=<예: ap-northeast-2c>
EC2_SUBNET_ID=<subnet-...>

# RDS
RDS_INSTANCE_ID=aws-picare-mysql
RDS_ENDPOINT=<...ap-northeast-2.rds.amazonaws.com>
RDS_PORT=3306
RDS_DATABASE_NAME=picare
RDS_APP_USER=picare_app
RDS_APP_PASSWORD=<비밀값>
RDS_SECURITY_GROUP_ID=<sg-...>
RDS_SECURITY_GROUP_NAME=aws-picare-rds-sg

# ECR
ECR_REPOSITORY_NAME=picare-web-kimqq
ECR_REPOSITORY_URI=<AWS_ACCOUNT_ID>.dkr.ecr.ap-northeast-2.amazonaws.com/picare-web-kimqq

# 앱 비밀값
DJANGO_SECRET_KEY=<비밀값>
AI_API_URL=https://<RUNPOD_POD_ID>-8000.proxy.runpod.net
AI_API_TOKEN=<RunPod과 AWS가 공유하는 32자 이상 난수>
```

### 비밀값 생성

개발 PC에서 한 번 생성해 안전한 메모장에 보관한다.

**Bash (macOS/Linux)**

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(50))'
```

**PowerShell (Windows)**

```powershell
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

같은 명령을 두 번 실행하면 서로 다른 값을 만든다. `DJANGO_SECRET_KEY`와 `AI_API_TOKEN`은 **서로 다른 값**이어야 한다.

---

## 2. AWS 콘솔 공통 선택

1. AWS 콘솔 우측 상단 리전을 **서울 `ap-northeast-2`**로 맞춘다.
2. 이후 모든 EC2, RDS, ECR 리소스를 같은 리전에 만든다.
3. EC2와 RDS는 반드시 같은 VPC를 사용한다.

예시 이름 규칙:

| 대상 | 권장 이름 |
| --- | --- |
| EC2 | `aws-picare` |
| EC2 보안 그룹 | `aws-picare-ec2-sg` |
| RDS | `aws-picare-mysql` |
| RDS 보안 그룹 | `aws-picare-rds-sg` |
| ECR | `picare-web-kimqq` |
| EC2 ECR Pull 역할 | `aws-picare-ec2-ecr-pull-role` |
| GitHub Actions ECR Push 정책 | `aws-picare-ecr-push-policy` |

---

## 3. EC2 생성과 네트워크 설정

### 3.1 키 페어 만들기

**AWS 콘솔 경로:** `EC2 → 네트워크 및 보안 → 키 페어 → 키 페어 생성`

| 항목 | 값 |
| --- | --- |
| 이름 | `picare-key` |
| 키 페어 유형 | RSA 또는 ED25519 |
| 프라이빗 키 파일 형식 | macOS/Linux은 `.pem`, Windows OpenSSH도 `.pem` |

다운로드한 PEM은 한 번만 받을 수 있다. 예: `~/Downloads/picare-key.pem` 또는 `C:\Users\<사용자>\Downloads\picare-key.pem`에 보관한다.

**Bash 권한 설정**

```bash
chmod 400 ~/Downloads/picare-key.pem
```

Windows PowerShell에서는 파일 권한을 바꾸지 않아도 OpenSSH가 접속되는 경우가 많다. 권한 오류가 나면 PEM 파일을 본인 계정만 읽도록 Windows 파일 속성에서 제한한다.

### 3.2 EC2 보안 그룹 만들기

**AWS 콘솔 경로:** `EC2 → 네트워크 및 보안 → 보안 그룹 → 보안 그룹 생성`

| 항목 | 값 |
| --- | --- |
| 보안 그룹 이름 | `aws-picare-ec2-sg` |
| 설명 | `PiCare EC2 web and admin SSH access` |
| VPC | RDS와 사용할 동일 VPC |

인바운드 규칙은 다음 두 개만 둔다.

| 유형 | 포트 | 소스 | 이유 |
| --- | --- | --- | --- |
| SSH | 22 | **내 IP** (`<내_공인_IP>/32`) | 관리자 접속 |
| HTTP | 80 | `0.0.0.0/0` | 웹 서비스 |

`8000`, `3306`, Docker 포트를 `0.0.0.0/0`로 열지 않는다. 아웃바운드는 기본값인 모든 트래픽 허용을 유지한다.

### 3.3 인스턴스 시작

**AWS 콘솔 경로:** `EC2 → 인스턴스 → 인스턴스 시작`

| 항목 | 권장 값 |
| --- | --- |
| 이름 | `aws-picare` |
| AMI | Ubuntu Server 24.04 LTS, 64비트(x86) |
| 인스턴스 유형 | `t3.small` |
| 키 페어 | `picare-key` |
| 네트워크 | 위 VPC, 퍼블릭 IP 자동 할당 활성화 |
| 보안 그룹 | 기존 `aws-picare-ec2-sg` 선택 |
| 스토리지 | gp3 20 GiB 이상 |

인스턴스가 `실행 중`이 될 때까지 기다린다.

### 3.4 Elastic IP 발급 및 연결

인스턴스를 중지·시작해도 웹 주소가 바뀌지 않도록 고정 IP를 쓴다.

1. **AWS 콘솔 경로:** `EC2 → 네트워크 및 보안 → 탄력적 IP 주소 → 탄력적 IP 주소 할당`
2. `Amazon의 IPv4 주소 풀` 기본값을 유지하고 **할당**을 누른다.
3. 생성된 IP 행을 선택한다.
4. 상단 **작업 → 탄력적 IP 주소 연결**을 누른다.
5. 리소스 유형에서 `인스턴스`, 대상에서 `aws-picare`를 선택하고 연결한다.

할당 후의 IPv4 주소를 `ELASTIC_IP`로 메모한다. Elastic IP를 어떤 실행 중 인스턴스에도 연결하지 않은 상태로 오래 두면 요금이 발생할 수 있다.

### 3.5 SSH 접속

**Bash (macOS/Linux)**

```bash
ssh -i ~/Downloads/picare-key.pem ubuntu@<ELASTIC_IP>
```

**PowerShell (Windows)**

```powershell
$Key = "$env:USERPROFILE\Downloads\picare-key.pem"
ssh -i $Key ubuntu@<ELASTIC_IP>
```

Ubuntu 프롬프트가 `ubuntu@ip-...`처럼 보이면 접속 성공이다.

---

## 4. RDS MySQL 만들기

RDS는 외부 공개하지 않고 EC2 보안 그룹에서만 접근시킨다.

### 4.1 RDS 보안 그룹 만들기

**AWS 콘솔 경로:** `EC2 → 네트워크 및 보안 → 보안 그룹 → 보안 그룹 생성`

| 항목 | 값 |
| --- | --- |
| 이름 | `aws-picare-rds-sg` |
| 설명 | `PiCare RDS MySQL access from EC2 only` |
| VPC | EC2와 같은 VPC |

인바운드 규칙:

| 유형 | 포트 | 소스 |
| --- | --- | --- |
| MYSQL/Aurora | 3306 | **보안 그룹** `aws-picare-ec2-sg` |

CIDR `0.0.0.0/0`나 개인 PC의 IP를 MySQL 포트에 넣지 않는다. 소스는 반드시 EC2 보안 그룹 자체다.

### 4.2 RDS 생성

**AWS 콘솔 경로:** `RDS → 데이터베이스 → 데이터베이스 생성 → 전체 구성`

| 구역 | 선택값 |
| --- | --- |
| 엔진 유형 | MySQL |
| 템플릿 | 개발/테스트 |
| 가용성 및 내구성 | 단일 DB 인스턴스 / Single-AZ |
| DB 인스턴스 식별자 | `aws-picare-mysql` |
| 마스터 사용자 이름 | `labadmin` |
| 자격 증명 | 암호 인증, 강한 마스터 비밀번호 |
| DB 인스턴스 클래스 | 예: `db.t4g.micro` |
| 스토리지 | gp3, 20 GiB 이상 |
| VPC | EC2와 같은 VPC |
| DB 서브넷 그룹 | 같은 VPC의 2개 AZ가 포함된 서브넷 그룹 |
| 퍼블릭 액세스 가능 | **아니요** |
| VPC 보안 그룹 | 기존 `aws-picare-rds-sg` 선택 |
| 초기 데이터베이스 이름 | `picare` |
| 포트 | `3306` |
| 자동 백업 | 개발/테스트라면 보존 1일 |
| 고급 모니터링·CloudWatch 로그 | 필요 없으면 선택하지 않음 |

RDS는 DB 서브넷 그룹에 최소 두 서브넷/AZ가 필요하다. EC2가 속한 서브넷이 하나여도 RDS의 DB 서브넷 그룹은 두 서브넷을 고른다.

생성 완료 후 **RDS → 데이터베이스 → `aws-picare-mysql` → 연결 및 보안**에서 `엔드포인트`를 복사해 `RDS_ENDPOINT`에 저장한다.

### 4.3 앱 전용 DB 사용자 만들기

EC2에서 마스터 사용자로 연결한다.

```bash
mysql -h <RDS_ENDPOINT> -P 3306 -u labadmin -p picare
```

MySQL 프롬프트에서 실행한다. 실제 비밀번호를 코드나 명령 기록에 넣지 않는다.

```sql
CREATE DATABASE IF NOT EXISTS picare
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER 'picare_app'@'%' IDENTIFIED BY '<강한_앱_비밀번호>';
GRANT ALL PRIVILEGES ON picare.* TO 'picare_app'@'%';
FLUSH PRIVILEGES;
SHOW GRANTS FOR 'picare_app'@'%';
EXIT;
```

앱 계정 검증:

```bash
mysql -h <RDS_ENDPOINT> -P 3306 -u picare_app -p picare \
  -e "SELECT DATABASE(), CURRENT_USER();"
```

`picare`와 `picare_app@%`가 보이면 DB 네트워크·계정·권한 구성이 정상이다.

---

## 5. ECR 만들기와 IAM 권한

### 5.1 ECR 비공개 저장소

**AWS 콘솔 경로:** `Elastic Container Registry → 프라이빗 리포지토리 → 리포지토리 생성`

| 항목 | 값 |
| --- | --- |
| 리포지토리 이름 | `picare-web-kimqq` |
| 이미지 태그 변경 가능성 | Immutable(변경 불가) 권장 |
| 암호화 | AES-256 기본값 |

생성 후 URI는 다음 형태다.

```text
<AWS_ACCOUNT_ID>.dkr.ecr.ap-northeast-2.amazonaws.com/picare-web-kimqq
```

Immutable 저장소에서는 같은 태그를 다시 push할 수 없다. 매 배포마다 `v1`, `v2` 또는 `sha-커밋해시`처럼 새 태그를 사용한다.

### 5.2 EC2가 ECR 이미지를 Pull하도록 역할 연결

**AWS 콘솔 경로:** `IAM → 역할 → 역할 생성`

1. 신뢰할 수 있는 엔터티에서 **AWS 서비스 → EC2**를 선택한다.
2. 역할 이름을 `aws-picare-ec2-ecr-pull-role`로 지정한다.
3. ECR Pull 전용 정책을 연결한다.
4. EC2 콘솔에서 `aws-picare` 인스턴스를 선택하고 **작업 → 보안 → IAM 역할 수정**에서 이 역할을 연결한다.

ECR Pull 정책 예시(계정 ID와 리포지토리 이름을 실제 값으로 바꾼다):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage"
      ],
      "Resource": "arn:aws:ecr:ap-northeast-2:<AWS_ACCOUNT_ID>:repository/picare-web-kimqq"
    }
  ]
}
```

EC2에서 역할 확인:

```bash
aws sts get-caller-identity
```

결과 ARN에 `assumed-role/aws-picare-ec2-ecr-pull-role`가 보이면 정상이다.

### 5.3 개발 PC 또는 GitHub Actions의 ECR Push 권한

개발 PC에서 직접 이미지를 올리는 IAM 사용자는 ECR Push 권한이 필요하다. 최소 권한 정책 예시는 다음과 같다.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:CompleteLayerUpload",
        "ecr:InitiateLayerUpload",
        "ecr:PutImage",
        "ecr:UploadLayerPart"
      ],
      "Resource": "arn:aws:ecr:ap-northeast-2:<AWS_ACCOUNT_ID>:repository/picare-web-kimqq"
    }
  ]
}
```

**AWS 콘솔 경로:** `IAM → 사용자 → <배포 사용자> → 권한 → 권한 추가`에서 정책을 연결한다.

액세스 키는 **IAM → 사용자 → 보안 자격 증명 → 액세스 키 생성**에서 만든다. 생성 화면에서 보이는 Secret Access Key는 그 순간에만 복사·다운로드할 수 있다. 키를 잃어버리면 새 키를 만들고 이전 키를 비활성화한다.

---

## 6. EC2에 Docker, AWS CLI, 배포 파일 준비

아래 명령은 **EC2 Ubuntu SSH 터미널(Bash)**에서 실행한다.

### 6.1 필수 패키지 설치

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-v2 curl unzip git
sudo systemctl enable --now docker
sudo usermod -aG docker ubuntu

curl -fsSL https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o /tmp/awscliv2.zip
unzip -q /tmp/awscliv2.zip -d /tmp
sudo /tmp/aws/install --update
aws --version
```

그룹 권한을 반영하려면 SSH를 한 번 종료한 뒤 다시 접속한다.

```bash
exit
```

### 6.2 배포 디렉터리 준비

```bash
sudo install -d -o ubuntu -g ubuntu /opt/picare/deploy
```

개발 PC에서 다음 파일을 EC2로 올린다.

- `deploy/compose.aws.yaml`
- `deploy/nginx.aws.conf`
- `deploy/aws.env.example`
- `deploy/aws-release.sh`

**Bash (macOS/Linux)**

```bash
cd /path/to/skn_33_4th_5team
scp -i ~/Downloads/picare-key.pem \
  deploy/compose.aws.yaml \
  deploy/nginx.aws.conf \
  deploy/aws.env.example \
  deploy/aws-release.sh \
  ubuntu@<ELASTIC_IP>:/opt/picare/
```

**PowerShell (Windows)**

```powershell
Set-Location C:\path\to\skn_33_4th_5team
$Key = "$env:USERPROFILE\Downloads\picare-key.pem"
scp -i $Key `
  deploy\compose.aws.yaml `
  deploy\nginx.aws.conf `
  deploy\aws.env.example `
  deploy\aws-release.sh `
  ubuntu@<ELASTIC_IP>:/opt/picare/
```

다시 EC2에 접속해 파일을 정리한다.

```bash
mv /opt/picare/compose.aws.yaml /opt/picare/deploy/
mv /opt/picare/nginx.aws.conf /opt/picare/deploy/
mv /opt/picare/aws.env.example /opt/picare/deploy/
mv /opt/picare/aws-release.sh /opt/picare/deploy/
chmod +x /opt/picare/deploy/aws-release.sh

cp /opt/picare/deploy/aws.env.example /opt/picare/.env
chmod 600 /opt/picare/.env
```

### 6.3 EC2 `.env` 채우기

**주의:** `~/.env`가 아니라 반드시 `/opt/picare/.env`을 연다.

```bash
nano /opt/picare/.env
```

아래 항목을 실제 값으로 교체한다.

```dotenv
PICARE_AI_BACKEND=remote
AI_API_URL=https://<RUNPOD_POD_ID>-8000.proxy.runpod.net
AI_API_TOKEN=<RUNPOD와_공유할_32자_이상_난수>
AI_HTTP_TIMEOUT=10
AI_JOB_TIMEOUT=300

DJANGO_DEBUG=false
DJANGO_SECRET_KEY=<별도_생성한_Django_Secret>
DJANGO_ALLOWED_HOSTS=<ELASTIC_IP>,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=http://<ELASTIC_IP>
DJANGO_SESSION_COOKIE_SECURE=false
DJANGO_CSRF_COOKIE_SECURE=false
DJANGO_SECURE_SSL_REDIRECT=false

DJANGO_DB_ENGINE=django.db.backends.mysql
DJANGO_DB_NAME=picare
DJANGO_DB_USER=picare_app
DJANGO_DB_PASSWORD=<picare_app_비밀번호>
DJANGO_DB_HOST=<RDS_ENDPOINT>
DJANGO_DB_PORT=3306

GUNICORN_WORKERS=1
GUNICORN_TIMEOUT=30
```

다음 두 값은 글자 그대로 `ELASTIC_IP`로 두면 안 된다.

```dotenv
DJANGO_ALLOWED_HOSTS=<실제_Elastic_IP>,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=http://<실제_Elastic_IP>
```

비밀값을 출력하지 않는 안전한 확인 예시:

```bash
grep '^DJANGO_DB_HOST=' /opt/picare/.env
grep '^AI_API_URL=' /opt/picare/.env
stat -c '%a %n' /opt/picare/.env
```

권한은 `600 /opt/picare/.env`이어야 한다.

---

## 7. RunPod AI 서버 설정

### 7.1 포트와 접속 주소

RunPod Pod에서:

| 포트 | 용도 | AWS에서 사용할지 |
| --- | --- | --- |
| `8000` | PiCare AI API | **예** |
| `8888` | JupyterLab | 아니요, 관리용 |
| `22` 또는 Exposed TCP 포트 | SSH | 아니요, 관리용 |

RunPod 화면의 HTTP Service `8000`에 표시되는 URL을 EC2 `.env`의 `AI_API_URL`에 넣는다.

```dotenv
AI_API_URL=https://<POD_ID>-8000.proxy.runpod.net
```

브라우저로 URL의 루트(`/`)를 열어 `Not Found`가 나오는 것은 정상이다. API에 루트 화면이 없기 때문이다.

### 7.2 코드 갱신 및 서버 시작

RunPod Jupyter `8888`의 터미널 또는 SSH에서 실행한다.

```bash
cd /workspace/skn_33_4th_5team
git status --short
git pull --ff-only origin main

source /workspace/venvs/picare/bin/activate
python -m pip install -r requirements-gpu.txt
python -m pip check
```

기존 8000 서버가 이미 있다면 먼저 확인하고 종료한다.

```bash
ss -lntp | grep ':8000' || true
pkill -f 'python -m src.runpod_api' || true
```

서버를 시작한다.

```bash
cd /workspace/skn_33_4th_5team
source /workspace/venvs/picare/bin/activate
python -m src.runpod_api
```

다른 RunPod 터미널에서 준비 상태를 확인한다.

```bash
curl -i -H "Authorization: Bearer $AI_API_TOKEN" \
  http://127.0.0.1:8000/health/ready
```

다음 형태여야 AWS 웹을 연결한다.

```json
{"ready": true, "message": "...준비 완료"}
```

`ready: false`는 모델·LoRA·검색 색인이 아직 로딩 중이거나 실패했다는 의미다. RunPod 로그에서 자산 경로와 GPU 오류를 먼저 해결한다.

---

## 8. 개발 PC에서 ECR 이미지 빌드·업로드

### 8.1 AWS CLI 프로필 등록

개발 PC의 IAM Access Key를 등록한다. 키 값은 화면·명령 기록을 공유하지 않는다.

**Bash (macOS/Linux)**

```bash
aws configure --profile picare-ecr-push
# AWS Access Key ID: <입력>
# AWS Secret Access Key: <입력>
# Default region name: ap-northeast-2
# Default output format: json

aws sts get-caller-identity --profile picare-ecr-push
```

**PowerShell (Windows)**

```powershell
aws configure --profile picare-ecr-push
# AWS Access Key ID: <입력>
# AWS Secret Access Key: <입력>
# Default region name: ap-northeast-2
# Default output format: json

aws sts get-caller-identity --profile picare-ecr-push
```

`Account`와 IAM 사용자 ARN이 표시되면 설정 성공이다.

### 8.2 배포 스크립트 사용(Bash)

이 프로젝트의 표준 방법이다. Apple Silicon Mac에서도 EC2용 `linux/amd64` 이미지를 만든다.

```bash
cd /path/to/skn_33_4th_5team
AWS_PROFILE=picare-ecr-push \
  bash deploy/aws-build-push.sh v1 <AWS_ACCOUNT_ID> picare-web-kimqq
```

두 번째 배포부터는 새 태그를 쓴다.

```bash
AWS_PROFILE=picare-ecr-push \
  bash deploy/aws-build-push.sh v2 <AWS_ACCOUNT_ID> picare-web-kimqq
```

### 8.3 PowerShell에서 직접 빌드·업로드

PowerShell에서 Bash를 쓰지 않는 경우 다음 명령을 쓴다.

```powershell
Set-Location C:\path\to\skn_33_4th_5team
$Region = 'ap-northeast-2'
$AccountId = '<AWS_ACCOUNT_ID>'
$Repository = 'picare-web-kimqq'
$Tag = 'v1'
$Registry = "$AccountId.dkr.ecr.$Region.amazonaws.com"
$Image = "${Registry}/${Repository}:${Tag}"

aws ecr get-login-password --region $Region --profile picare-ecr-push |
  docker login --username AWS --password-stdin $Registry

docker buildx build --platform linux/amd64 --load -f Dockerfile.aws -t $Image .
docker push $Image
```

정상이라면 마지막에 `digest: sha256:...`과 Push 완료 메시지가 보인다.

---

## 9. EC2에서 수동 릴리스와 확인

EC2 SSH 터미널에서 실행한다.

```bash
cd /opt/picare
bash deploy/aws-release.sh v1 <AWS_ACCOUNT_ID> picare-web-kimqq
```

릴리스 스크립트는 ECR 로그인, 이미지 pull, migration, Nginx/Django 실행, `/`, 로그인 페이지, `/health/` 확인을 순서대로 진행한다.

성공 기준:

```text
Container picare-aws-web-1 Healthy
Container picare-aws-nginx-1 Healthy
Release is healthy: ...:v1
```

외부 브라우저에서 다음을 확인한다.

```text
http://<ELASTIC_IP>/
http://<ELASTIC_IP>/accounts/login/
http://<ELASTIC_IP>/health/
```

기능 검수 순서:

1. 회원가입과 로그인
2. 커뮤니티 글 또는 댓글 작성(RDS 쓰기 확인)
3. 제품 추천
4. Q&A
5. 미니 챌린지

### 장애 확인 명령

```bash
cd /opt/picare
docker compose --project-name picare-aws \
  --env-file .env --env-file deploy/release.env \
  -f deploy/compose.aws.yaml ps
docker logs picare-aws-web-1 --tail 200
docker logs picare-aws-nginx-1 --tail 100
curl -i http://127.0.0.1/health/
```

대표 증상과 원인:

| 증상 | 우선 확인 |
| --- | --- |
| `web is unhealthy` | `docker logs picare-aws-web-1 --tail 200` |
| RDS 호스트를 찾지 못함 | `/opt/picare/.env`의 `DJANGO_DB_HOST`가 예시값이 아닌 실제 RDS 엔드포인트인지 확인 |
| DB 인증 실패 | `DJANGO_DB_PASSWORD`와 `picare_app` 비밀번호 일치 여부 |
| `/health/`가 `ready: false` | RunPod `8000`의 `/health/ready`와 양쪽 `AI_API_TOKEN` 일치 여부 |
| RunPod 루트에서 404 | 정상; `/health/live` 또는 인증을 넣은 `/health/ready` 사용 |
| Docker 로그인 경고 | `~/.docker/config.json`의 자격 증명 저장 방식 경고이며 Pull/배포 성공과는 별개 |

### 롤백

직전 정상 태그를 지정해 다시 실행한다.

```bash
cd /opt/picare
bash deploy/aws-release.sh <이전_태그> <AWS_ACCOUNT_ID> picare-web-kimqq
```

`/opt/picare/deploy/previous-release.env`에서 직전 이미지 태그를 확인할 수 있다.

---

## 10. GitHub Actions CI/CD 설정

저장소에는 `.github/workflows/aws-cicd.yml`이 들어 있다. 동작은 다음과 같다.

1. Pull request와 `main` 푸시에서 Django 설정·마이그레이션·원격 AI 계약·배포 자산을 검사한다.
2. `main` 푸시 또는 수동 실행에서 `sha-<커밋해시>` 불변 태그 이미지를 ECR에 Push한다.
3. AWS Systems Manager(SSM)가 EC2에 `aws-release.sh` 실행을 전달한다.
4. EC2는 인스턴스 역할로 이미지를 Pull해 무중단에 가깝게 Compose를 갱신한다.

### 10.1 EC2 역할에 SSM 권한 추가

**AWS 콘솔 경로:** `IAM → 역할 → aws-picare-ec2-ecr-pull-role → 권한 추가 → 권한 추가`

AWS 관리형 정책 **`AmazonSSMManagedInstanceCore`**를 추가한다. 기존 ECR Pull 정책은 제거하지 않는다.

그리고 **AWS 콘솔 경로:** `Systems Manager → Fleet Manager → Managed nodes`에서 EC2가 `Online`인지 확인한다.

보이지 않으면 EC2에서 SSM Agent를 확인한다.

```bash
sudo systemctl status amazon-ssm-agent --no-pager || \
sudo systemctl status snap.amazon-ssm-agent.amazon-ssm-agent.service --no-pager
```

### 10.2 GitHub Secrets와 Variables 등록

**GitHub 웹 경로:** `저장소 → Settings → Secrets and variables → Actions`

#### Secrets 탭

`New repository secret`으로 아래 두 개를 만든다.

| 이름 | 넣을 값 |
| --- | --- |
| `AWS_ACCESS_KEY_ID` | ECR Push 및 SSM 실행 권한을 가진 IAM Access Key ID |
| `AWS_SECRET_ACCESS_KEY` | 같은 키의 Secret Access Key |

`AI_API_TOKEN`, RDS 비밀번호, Django Secret은 GitHub Secrets에 등록할 필요가 없다. 이 값들은 EC2의 `/opt/picare/.env`에서만 관리한다.

#### Variables 탭

`New repository variable`로 아래를 만든다.

| 이름 | 값 |
| --- | --- |
| `AWS_REGION` | `ap-northeast-2` |
| `AWS_ACCOUNT_ID` | 12자리 AWS 계정 ID |
| `ECR_REPOSITORY` | `picare-web-kimqq` |
| `EC2_INSTANCE_ID` | `i-...` |

### 10.3 GitHub Actions용 IAM SSM 권한

현재 IAM 사용자가 관리자 권한이면 첫 실행은 가능하다. 장기 운영에서는 GitHub 전용 IAM 사용자로 분리하고, 기존 ECR Push 권한에 다음 SSM 권한을 추가한다.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ssm:SendCommand",
      "Resource": [
        "arn:aws:ssm:ap-northeast-2::document/AWS-RunShellScript",
        "arn:aws:ec2:ap-northeast-2:<AWS_ACCOUNT_ID>:instance/<EC2_INSTANCE_ID>"
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

### 10.4 최초 실행

1. 위 Secrets/Variables를 모두 저장한다.
2. workflow 파일을 포함해 `main`에 push한다.
3. GitHub `Actions → AWS CI/CD`를 연다.
4. 필요하면 우측의 **Run workflow**를 눌러 수동 실행한다.
5. `Test and validate deployment image`, `Publish and release to EC2`가 모두 녹색인지 확인한다.

같은 저장소에서 코드만 바뀌면 다시 설정할 필요가 없다. 새 `main` push마다 자동 실행된다. 다만 저장소를 이전/복제하거나 AWS 계정·ECR·EC2를 바꾸면 GitHub Secrets/Variables를 새 환경에 다시 등록해야 한다.

---

## 11. 일상 배포 체크리스트

### 코드 변경 후

```bash
git status
git add <변경_파일>
git commit -m "설명"
git push origin main
```

GitHub Actions가 설정된 뒤에는 ECR Push와 EC2 릴리스를 수동으로 반복하지 않아도 된다.

### 배포 후

- [ ] GitHub Actions 두 작업이 모두 성공
- [ ] `http://<ELASTIC_IP>/health/`에서 `status: ok`, `ready: true`
- [ ] 회원가입/로그인 성공
- [ ] RDS에 쓰기 작업 성공
- [ ] 추천, Q&A, 미니 챌린지 각각 성공
- [ ] EC2/RDS/RunPod 비밀값이 Git에 없는지 확인

### 절대 하지 않을 것

- [ ] EC2 보안 그룹의 `22`, `3306`, `8000`을 `0.0.0.0/0`에 공개하지 않는다.
- [ ] `.env`, PEM, Access Key CSV를 Git에 커밋하지 않는다.
- [ ] ECR Immutable 저장소에 기존 태그를 재사용하지 않는다.
- [ ] RunPod의 8888(Jupyter) 또는 SSH 포트를 `AI_API_URL`로 넣지 않는다.
- [ ] `DJANGO_ALLOWED_HOSTS=ELASTIC_IP`처럼 자리표시어를 그대로 두지 않는다.
