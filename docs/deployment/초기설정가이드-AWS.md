# PiCare 초기 설정 가이드 - AWS

이 문서는 PiCare 4차 프로젝트의 Django 웹 서버를 AWS에 배포하는 실제
절차를 정리한다. 웹 서버는 EC2에서, AI 추론은 RunPod GPU API에서 실행한다.
데이터베이스는 비용 검수용 **EC2 Docker MySQL** 또는 관리형 **Amazon RDS for
MySQL** 중 하나를 선택한다.

## 1. 구성과 역할

```text
인터넷 사용자
    │ HTTP 80 / 추후 HTTPS 443
    ▼
AWS EC2 Nginx
    │ 127.0.0.1:8000
    ▼
Django·Gunicorn 컨테이너
    ├─ 선택 A: Docker 내부망 → MySQL 컨테이너
    ├─ 선택 B: 같은 VPC 내부망 → Amazon RDS for MySQL
    └─ HTTPS/Bearer Token → RunPod AI API
```

- Nginx는 외부 요청을 받고 Django로 전달한다.
- Django는 화면, 인증, 사용자 데이터와 AI 작업 상태를 관리한다.
- DB 선택 A는 MySQL을 Docker named volume에 저장하는 가장 저렴한 검수 방식이다.
- DB 선택 B는 MySQL을 Amazon RDS에 분리하는 관리형 DB 방식이다.
- RunPod는 Qwen, LoRA, Hybrid RAG 추론만 담당한다.
- AWS에는 GPU 라이브러리나 모델 파일을 설치하지 않는다.
- RDS는 외부 인터넷에 공개하지 않으며 EC2 보안 그룹만 3306에 연결한다.

## 2. EC2 생성

AWS 콘솔에서 서울 리전 `ap-northeast-2`를 선택한 뒤 EC2 인스턴스를 생성한다.

| 항목 | 설정값 |
| --- | --- |
| 이름 | `picare-web` |
| AMI | Ubuntu Server 24.04 LTS |
| 아키텍처 | 64-bit x86/amd64 |
| 인스턴스 유형 | `t3.small` |
| 루트 볼륨 | 20 GiB gp3 |
| 인스턴스 개수 | 1 |
| 퍼블릭 IPv4 | 활성화 |

`t3.small`은 메모리 약 2 GiB다. Django, Nginx, MySQL을 한 인스턴스에서
실행하는 검수 환경의 기준값이다. 비용을 더 줄이기 위해 `t3.micro`를 사용할
수도 있지만 이미지 빌드와 MySQL 동시 실행 중 메모리가 부족할 수 있다.

### 키 페어

```text
이름: picare-aws-key
유형: RSA
형식: .pem
```

PEM 파일은 다시 다운로드할 수 없으므로 안전하게 보관한다. 저장소, 팀 채팅,
문서 첨부 파일에 PEM을 올리지 않는다.

### 보안 그룹

| 용도 | 프로토콜·포트 | 소스 |
| --- | --- | --- |
| 서버 관리 | TCP 22 | 관리자 현재 IP `/32` |
| 공개 웹 | TCP 80 | `0.0.0.0/0` |
| 공개 HTTPS | TCP 443 | `0.0.0.0/0` |

다음 포트는 외부에 열지 않는다.

```text
8000  Django·Gunicorn 내부 포트
3306  MySQL 내부 포트
```

웹사이트를 누구나 이용하도록 공개하는 것과 SSH를 누구나 이용하도록 공개하는
것은 다르다. 80·443만 공개하고 22는 관리자 IP로 제한한다. 관리자 공인 IP가
바뀌면 보안 그룹의 SSH 소스를 현재 IP로 갱신한다.

## 3. SSH 접속

인스턴스가 `실행 중`이고 상태 검사가 통과한 뒤 현재 퍼블릭 IPv4를 복사한다.

macOS 또는 Linux에서 PEM 권한을 제한한다.

```bash
chmod 400 ~/Downloads/picare-aws-key.pem
```

Ubuntu AMI의 기본 계정으로 접속한다.

```bash
ssh -i ~/Downloads/picare-aws-key.pem ubuntu@<EC2_PUBLIC_IP>
```

처음 접속할 때 호스트 확인 질문에는 `yes`를 입력한다.

## 4. Git과 Docker 설치

EC2에서 실행한다.

```bash
sudo apt-get update
sudo apt-get install -y git docker.io ca-certificates curl
sudo systemctl enable --now docker
sudo usermod -aG docker ubuntu
```

Docker 그룹 권한은 다음 로그인부터 반영된다.

```bash
exit
ssh -i ~/Downloads/picare-aws-key.pem ubuntu@<EC2_PUBLIC_IP>
```

확인한다.

```bash
git --version
docker --version
docker ps
```

Docker Compose v2도 설치한다.

```bash
sudo apt-get update
sudo apt-get install -y docker-compose-v2
docker compose version
```

## 5. 프로젝트 clone

```bash
cd /home/ubuntu
git clone https://github.com/skn-33-Raspberry-Pi-Assistant-4th/skn_33_4th_5team.git
cd /home/ubuntu/skn_33_4th_5team
```

저장소가 비공개라 GitHub 인증을 요청하면 계정 비밀번호가 아닌 Personal Access
Token 또는 SSH Deploy Key를 사용한다. 토큰을 clone URL에 직접 넣지 않는다.

```bash
git remote -v
git branch --show-current
ls
```

`Dockerfile.aws`, `compose.yaml`, `requirements-web.txt`, `web_app`이 보이면 된다.

## 6. 스왑 메모리 설정

Docker 이미지 빌드 중 메모리 부족을 예방하기 위해 2 GiB 스왑을 추가한다.

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

확인한다.

```bash
free -h
```

정상 기준:

```text
Swap: 2.0Gi
```

위 명령은 새 인스턴스에서 한 번만 실행한다. `/etc/fstab`에 같은 줄을 반복해서
추가하지 않는다.

## 7. AWS 전용 환경변수

AWS `.env`에는 웹 서버와 DB에 필요한 최소 설정만 넣는다. 로컬·RunPod `.env`의
OpenAI, Hugging Face, CUDA, 모델 경로를 그대로 복사하지 않는다.

```bash
cd /home/ubuntu/skn_33_4th_5team
nano .env
```

아래 값은 **선택 A(EC2 Docker MySQL)** 기준 형식이다. 선택 B(RDS)는 13절에서
`DJANGO_DB_*` 다섯 값을 RDS 값으로 교체한다.

```env
PICARE_AI_BACKEND=remote
AI_API_URL=https://<POD_ID>-8000.proxy.runpod.net
AI_API_TOKEN=<RunPod와 공유한 동일한 32자 이상 토큰>
AI_HTTP_TIMEOUT=10
AI_JOB_TIMEOUT=300

DJANGO_DEBUG=false
DJANGO_SECRET_KEY=<운영용 난수>
DJANGO_ALLOWED_HOSTS=<EC2_PUBLIC_IP>,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=http://<EC2_PUBLIC_IP>
DJANGO_SESSION_COOKIE_SECURE=false
DJANGO_CSRF_COOKIE_SECURE=false
DJANGO_SECURE_SSL_REDIRECT=false

MYSQL_DATABASE=picare
MYSQL_USER=picare_app
MYSQL_PASSWORD=<애플리케이션 DB 비밀번호>
MYSQL_ROOT_PASSWORD=<MySQL 루트 비밀번호>
MYSQL_HOST=picare-mysql
MYSQL_PORT=3306

DJANGO_DB_ENGINE=django.db.backends.mysql
DJANGO_DB_NAME=picare
DJANGO_DB_USER=picare_app
DJANGO_DB_PASSWORD=<MYSQL_PASSWORD와 동일한 값>
DJANGO_DB_HOST=picare-mysql
DJANGO_DB_PORT=3306

GUNICORN_WORKERS=1
GUNICORN_TIMEOUT=30
```

비밀값은 필요하면 다음으로 생성한다.

```bash
openssl rand -hex 32
```

중요한 일치 조건:

- AWS와 RunPod의 `AI_API_TOKEN`이 같아야 한다.
- `MYSQL_PASSWORD`와 `DJANGO_DB_PASSWORD`가 같아야 한다.
- `MYSQL_USER`와 `DJANGO_DB_USER`가 `picare_app`으로 같아야 한다.
- `DJANGO_SECRET_KEY`와 DB 비밀번호는 서로 다른 값을 권장한다.
- 실제 파일에 `<`, `>`, 설명 문구를 넣지 않는다.

권한을 제한한다.

```bash
chmod 600 .env
```

비밀값을 노출하지 않고 존재 여부를 확인한다.

```bash
awk -F= '
/^(AI_API_TOKEN|DJANGO_SECRET_KEY|MYSQL_PASSWORD|MYSQL_ROOT_PASSWORD|DJANGO_DB_PASSWORD)=/ {
  print $1 ": " length(substr($0, index($0, "=") + 1)) " chars"
}' .env
```

Compose 보간을 검증한다.

```bash
unset MYSQL_PASSWORD MYSQL_ROOT_PASSWORD DJANGO_DB_PASSWORD
docker compose config --quiet
```

아무 출력 없이 끝나면 정상이다.

### `MYSQL_PASSWORD is missing` 오류

다음 오류는 비밀번호가 틀렸다는 뜻이 아니라 정확한 변수 이름이 없거나 값이
비었다는 뜻이다.

```text
required variable MYSQL_PASSWORD is missing a value
```

값을 숨긴 채 세 변수를 확인한다.

```bash
grep -nE '^(MYSQL_PASSWORD|MYSQL_ROOT_PASSWORD|DJANGO_DB_PASSWORD)=' .env \
  | sed -E 's/=.*/=<hidden>/'
```

세 줄이 모두 있어야 한다. `DJANGO_DB_PASSWORD`만으로는 MySQL 이미지가 시작되지
않는다.

## 8. 데이터베이스 방식 선택

둘 중 **한 가지**만 선택해 다음 단계로 진행한다.

| 선택 | 용도 | DB 위치 | 다음에 진행할 절 |
| --- | --- | --- | --- |
| A. EC2 Docker MySQL | 가장 저렴한 수업·기능 검수 | 같은 EC2의 Docker named volume | 14절 |
| B. Amazon RDS for MySQL | DB를 웹 서버와 분리한 관리형 구성 | 같은 VPC의 비공개 RDS | 9~13절 |

선택 B에서는 7절의 `MYSQL_*` 값이 Compose 검증용으로 남아 있어도 되지만,
Django가 실제로 사용할 값은 `DJANGO_DB_*`다. 현재 코드에서는 `DJANGO_DB_*`가
`MYSQL_*`보다 우선한다.

## 9. RDS용 EC2 정보 기록

선택 B만 진행한다. AWS 콘솔에서 **EC2 → 인스턴스 → PiCare 인스턴스**를 열고
다음 값을 기록한다.

| 필요한 값 | 확인 위치 | RDS에서 사용할 곳 |
| --- | --- | --- |
| VPC ID (`vpc-...`) | 네트워킹 → VPC ID | RDS 보안 그룹·DB 서브넷 그룹·DB 생성 |
| 가용 영역 | 네트워킹 → 가용 영역 | DB 서브넷 선택 참고 |
| EC2 보안 그룹 ID (`sg-...`) | 보안 → 보안 그룹 | RDS 인바운드 규칙의 소스 |

보안 그룹 이름이 아니라 **현재 EC2 인스턴스에 실제로 연결된 보안 그룹 ID**를
사용한다. RDS와 EC2는 반드시 같은 VPC에 있어야 한다.

## 10. RDS 보안 그룹과 DB 서브넷 그룹

### 10.1 RDS 보안 그룹

AWS 콘솔에서 **EC2 → 네트워크 및 보안 → 보안 그룹 → 보안 그룹 생성**을 선택한다.

| 항목 | 값 |
| --- | --- |
| 보안 그룹 이름 | `picare-rds` |
| 설명 | `MySQL from PiCare EC2 only` |
| VPC | 9절에서 확인한 PiCare EC2와 같은 `vpc-...` |

인바운드 규칙은 아래 한 줄만 추가한다.

| 유형 | 프로토콜 | 포트 | 소스 유형 | 소스 |
| --- | --- | --- | --- | --- |
| MySQL/Aurora | TCP | 3306 | 사용자 지정 | PiCare EC2 보안 그룹의 실제 `sg-...` |

RDS 3306을 `0.0.0.0/0`, 내 IP, EC2 공인 IP 또는 RDS 보안 그룹 자신에게 열지
않는다. EC2 인바운드에 3306을 추가할 필요도 없다. EC2의 기본 아웃바운드가
모든 트래픽을 허용한다면 3306 아웃바운드 규칙을 별도로 만들 필요가 없다.

### 10.2 DB 서브넷 그룹

RDS는 서로 다른 가용 영역의 서브넷을 최소 두 개 필요로 한다. AWS 콘솔에서
**Aurora and RDS → 서브넷 그룹 → DB 서브넷 그룹 생성**을 선택한다.

| 항목 | 값 |
| --- | --- |
| 이름 | `picare-rds-subnets` |
| 설명 | `Subnets for PiCare RDS` |
| VPC | PiCare EC2와 같은 `vpc-...` |

서로 다른 두 가용 영역을 고르고 각 영역에서 기존 서브넷을 하나씩 선택한다.
이것은 Single-AZ RDS에도 필요한 배치 후보 목록이며 Multi-AZ 설정을 뜻하지는
않는다.

## 11. RDS MySQL 생성

AWS 콘솔에서 **Aurora and RDS → 데이터베이스 → 데이터베이스 생성 → 전체 구성**을
선택한다.

| 화면 구역 | 항목 | PiCare 권장값 |
| --- | --- | --- |
| 엔진 옵션 | 엔진 유형 / 버전 | MySQL / 제공되는 MySQL 8.4 마이너 버전 |
| 템플릿 | 사용 목적 | 개발/테스트 |
| 가용성 | 배포 옵션 | 단일 DB 인스턴스 / Single-AZ |
| 설정 | DB 인스턴스 식별자 | `picare-mysql-rds` |
| 설정 | 마스터 사용자 이름 | `picare_admin` |
| 자격 증명 | 관리 방식 | 자체 관리 |
| 인스턴스 구성 | DB 인스턴스 클래스 | `db.t4g.micro` 또는 예산에 맞는 개발용 클래스 |
| 스토리지 | 유형 / 할당 | gp3 / 20 GiB |
| 연결 | VPC | PiCare EC2와 같은 VPC |
| 연결 | DB 서브넷 그룹 | `picare-rds-subnets` |
| 연결 | 퍼블릭 액세스 | 아니요 |
| 연결 | VPC 보안 그룹 | 기존 항목 선택 → `picare-rds`만 선택 |
| 연결 | DB 포트 | 3306 |
| 추가 구성 | 초기 데이터베이스 이름 | `picare` |
| 추가 구성 | 자동 백업 보존 | 1일 이상, 과제 정책에 맞게 설정 |

자동 선택된 `default` 보안 그룹은 해제한다. 마스터 비밀번호는 AWS 로그인 비밀번호,
`DJANGO_SECRET_KEY`, RunPod 토큰과 모두 다른 값으로 정하고 Git에 기록하지 않는다.
예상 요금을 확인한 뒤 생성한다.

상태가 **사용 가능**이 된 뒤 RDS 상세 화면에서 다음을 확인한다.

- VPC는 EC2와 같다.
- VPC 보안 그룹은 `picare-rds`다.
- 퍼블릭 액세스 가능은 `아니요`다.
- 엔드포인트는 `...ap-northeast-2.rds.amazonaws.com` 형식이다.

엔드포인트는 주소만 복사한다. `https://`나 포트 번호를 붙이지 않는다.

## 12. RDS 접속·앱 계정 확인

선택 B에서는 TLS로 RDS 관리자 접속을 확인한다. EC2에서 인증서를 받는다.

```bash
cd /home/ubuntu/skn_33_4th_5team
mkdir -p certs
curl -fsSL --connect-timeout 10 --max-time 60 \
  https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem \
  -o certs/global-bundle.pem
ls -lh certs/global-bundle.pem
```

RDS 엔드포인트를 넣어 접속한다.

```bash
export RDS_ENDPOINT='<RDS 엔드포인트만 입력>'

sudo docker run --rm -it \
  -v "$PWD/certs:/certs:ro" \
  mysql:8.4 mysql \
  --host="$RDS_ENDPOINT" \
  --port=3306 \
  --user=picare_admin \
  --password \
  --ssl-ca=/certs/global-bundle.pem \
  --ssl-mode=VERIFY_IDENTITY
```

`mysql>` 프롬프트가 나오면 아래 SQL로 Django 전용 계정을 만든다. 실제 비밀번호로
`<강력한 앱 DB 비밀번호>`만 교체하고 꺾쇠괄호는 제거한다.

```sql
CREATE DATABASE IF NOT EXISTS picare
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER 'picare_app'@'%'
  IDENTIFIED BY '<강력한 앱 DB 비밀번호>';

GRANT ALL PRIVILEGES ON picare.* TO 'picare_app'@'%';
SHOW GRANTS FOR 'picare_app'@'%';
EXIT;
```

`%`는 보안 그룹으로 EC2만 실제 연결을 허용하므로 바꾸지 않는다. 이 앱 계정은
`picare.*` 데이터베이스 범위에만 권한을 가진다.

### TLS 강제 적용 전 주의

Notion 원본의 `REQUIRE SSL`은 현재 바로 적용하지 않는다. PiCare의
`web_app/picare_web/settings.py::_database_config()`은 아직 CA 경로 또는 Django
MySQL `OPTIONS["ssl"]`을 읽지 않으므로, 앱 계정에 TLS를 강제하면 Django 연결이
실패할 수 있다. 운영에서 TLS 강제를 적용하려면 Django SSL 설정을 먼저 구현하고
검증한 뒤 `REQUIRE SSL`을 추가한다.

## 13. RDS용 `.env` 설정

선택 B에서는 EC2의 `.env`에서 실제 Django DB 연결값을 아래처럼 바꾼다.

```env
DJANGO_DB_ENGINE=django.db.backends.mysql
DJANGO_DB_NAME=picare
DJANGO_DB_USER=picare_app
DJANGO_DB_PASSWORD=<12절에서 정한 앱 DB 비밀번호>
DJANGO_DB_HOST=<RDS 엔드포인트>
DJANGO_DB_PORT=3306
```

- `DJANGO_DB_PASSWORD`에는 RDS 마스터 비밀번호가 아니라 `picare_app` 비밀번호를 넣는다.
- 기존 `MYSQL_HOST=picare-mysql`은 Docker MySQL용이다. RDS에서는
  `DJANGO_DB_HOST`가 우선한다.
- `.env`를 수정한 뒤 웹 컨테이너는 반드시 재생성해야 한다.
- RDS 전환이 성공하고 로그인·저장 기능을 확인하기 전에는 기존 `picare-mysql`
  컨테이너나 named volume을 삭제하지 않는다.

## 14. 선택 A: MySQL만 실행

기존 `compose.yaml`에는 GPU용 개발 웹과 worker도 있다. AWS에서는 전체 Compose를
실행하지 말고 MySQL 서비스만 실행한다.

```bash
docker compose up -d mysql
```

상태를 확인한다.

```bash
docker compose ps mysql
docker inspect --format='{{.State.Health.Status}}' picare-mysql
```

최초 생성 중에는 `starting`이 정상이다. 보통 수십 초 후 `healthy`로 바뀐다.
2분 이상 `starting`이거나 `unhealthy`이면 로그를 확인한다.

```bash
docker compose logs --tail=50 mysql
```

MySQL이 루프백에만 연결됐는지 확인한다.

```bash
docker port picare-mysql
```

기준 형식:

```text
3306/tcp -> 127.0.0.1:<HOST_MYSQL_PORT>
```

`MYSQL_PORT`를 33065처럼 지정했더라도 Docker 내부의 MySQL 포트는 3306이다.
Django는 Docker 네트워크에서 `picare-mysql:3306`으로 접속한다.

## 15. AWS Django 이미지 빌드

```bash
docker build -f Dockerfile.aws -t picare-web:aws .
```

`pip`의 root 사용자 경고는 격리된 Docker 이미지 내부에서 설치하기 때문에 이
배포에서는 치명적인 오류가 아니다. 호스트 Python 환경을 변경하지 않는다.

빌드 결과를 확인한다.

```bash
docker image ls picare-web:aws
```

## 16. Django·Gunicorn 컨테이너 실행

선택 A는 MySQL 컨테이너가 속한 Compose 네트워크 이름을 가져온다.

```bash
APP_NETWORK=$(docker inspect picare-mysql \
  --format '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{end}}')
echo "$APP_NETWORK"
```

Django를 같은 네트워크에서 실행한다.

```bash
docker run -d \
  --name picare-web \
  --restart unless-stopped \
  --network "$APP_NETWORK" \
  --env-file .env \
  -p 127.0.0.1:8000:8000 \
  picare-web:aws
```

선택 B(RDS)는 Docker MySQL 네트워크가 필요 없으므로 아래 명령으로 실행한다.
RDS는 EC2의 기본 Docker 네트워크를 통해 VPC 내부 주소로 연결된다.

```bash
docker run -d \
  --name picare-web \
  --restart unless-stopped \
  --env-file .env \
  -p 127.0.0.1:8000:8000 \
  picare-web:aws
```

8000번을 `127.0.0.1`에만 바인딩하므로 인터넷에서 Gunicorn으로 직접 접속할 수
없다. 외부 요청은 다음 절의 Nginx만 받는다.

```bash
docker logs -f picare-web
```

정상 로그:

```text
Apply all migrations: ...
No migrations to apply.
Starting gunicorn
Listening at: http://0.0.0.0:8000
Booting worker
```

`Ctrl+C`는 로그 팔로우만 끝내며 컨테이너는 종료하지 않는다.

```bash
docker ps
```

`picare-web`은 `Up`이어야 한다. 선택 A라면 `picare-mysql`도 `Up ... (healthy)`여야
하고, 선택 B라면 RDS 콘솔 상태가 `사용 가능`이어야 한다.

## 17. EC2 내부 웹 확인

```bash
curl -sS -o /dev/null \
  -w 'root=%{http_code}\n' \
  http://127.0.0.1:8000/

curl -sS -o /dev/null \
  -w 'login=%{http_code}\n' \
  http://127.0.0.1:8000/accounts/login/
```

두 요청 모두 `200`이면 Django와 선택한 DB가 정상 연결된 것이다. RunPod를 중지한
상태라면 AI 준비 상태만 실패하는 것은 정상이다.

## 18. Nginx 설치와 공개

```bash
sudo apt-get update
sudo apt-get install -y nginx
sudo systemctl enable --now nginx
```

설정 파일을 만든다.

```bash
sudo nano /etc/nginx/sites-available/picare
```

```nginx
server {
    listen 80 default_server;
    listen [::]:80 default_server;

    server_name _;
    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8000;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

활성화하고 기본 사이트를 해제한다.

```bash
sudo ln -s /etc/nginx/sites-available/picare /etc/nginx/sites-enabled/picare
sudo unlink /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

`nginx -t`가 `syntax is ok`, `test is successful`을 출력해야 한다.

```bash
curl -sS -o /dev/null \
  -w 'nginx=%{http_code}\n' \
  http://127.0.0.1/
```

브라우저에서 확인한다.

```text
http://<EC2_PUBLIC_IP>
```

## 19. RunPod 연동 확인

RunPod가 중지돼 있어도 AWS 웹·DB는 실행할 수 있지만 Q&A, 추천, 동적 퀴즈의
AI 요청은 완료되지 않는다. AI 기능을 검수할 때만 Pod를 시작하고 API를 실행한다.

RunPod API 준비 확인:

```bash
curl -s \
  -H "Authorization: Bearer $AI_API_TOKEN" \
  https://<POD_ID>-8000.proxy.runpod.net/health/ready
```

정상 기준:

```json
{"ready": true, "message": "Qwen·LoRA·Hybrid RAG 런타임 준비 완료"}
```

AWS 컨테이너는 시작할 때 `.env`를 읽는다. `AI_API_URL`이나 토큰을 수정했다면
컨테이너를 재생성해야 한다.

```bash
docker stop picare-web
docker rm picare-web

if docker inspect picare-mysql >/dev/null 2>&1; then
  APP_NETWORK=$(docker inspect picare-mysql \
    --format '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{end}}')
  NETWORK_OPTION=(--network "$APP_NETWORK")
else
  NETWORK_OPTION=()
fi

docker run -d \
  --name picare-web \
  --restart unless-stopped \
  "${NETWORK_OPTION[@]}" \
  --env-file .env \
  -p 127.0.0.1:8000:8000 \
  picare-web:aws
```

## 20. 자주 발생하는 오류

| 증상 | 원인 | 확인·조치 |
| --- | --- | --- |
| SSH timeout | 22번 규칙의 관리자 IP 불일치 | 보안 그룹에서 현재 IP `/32`로 갱신 |
| `MYSQL_PASSWORD is missing` | `.env`에 정확한 변수가 없거나 빈 값 | 세 DB 비밀번호 변수 확인 |
| MySQL `starting` | 최초 DB·사용자 생성 중 | 수십 초 후 재확인 |
| MySQL `unhealthy` | 비밀번호·볼륨·초기화 실패 | MySQL 로그 확인 |
| Django `Can't connect ... 127.0.0.1` | 컨테이너에서 잘못된 DB 호스트 사용 | 선택 A는 `picare-mysql`, 선택 B는 RDS 엔드포인트 |
| RDS 연결 timeout | RDS 보안 그룹 또는 VPC 불일치 | 3306 소스를 EC2 보안 그룹 ID로, 같은 VPC인지 확인 |
| RDS Access denied | 앱 계정·비밀번호·권한 불일치 | `picare_app` 권한과 `DJANGO_DB_*` 확인 |
| 웹 컨테이너가 즉시 종료 | migration 또는 DB 인증 실패 | `docker logs picare-web` |
| Nginx 502 | Django 미실행 또는 8000 바인딩 실패 | `docker ps`, 내부 curl 확인 |
| Django 400 | 퍼블릭 IP가 `DJANGO_ALLOWED_HOSTS`에 없음 | `.env` 수정 후 컨테이너 재생성 |
| AI 인증 실패 | AWS·RunPod 토큰 불일치 | 동일 토큰으로 교체 후 양쪽 재시작 |
| AI 연결 실패 | RunPod 중지·로딩 중·URL 오류 | `live`, `ready`, `-8000` URL 확인 |

## 21. 재부팅·업데이트·비용 관리

- 선택 A의 MySQL과 Django는 `restart: unless-stopped`로 EC2 재부팅 후 다시 시작한다.
- 선택 B의 RDS는 EC2와 별도 과금 대상이다. 과제 종료 후 최종 스냅샷 필요 여부를
  결정하고, 필요 없으면 RDS도 삭제한다.
- Nginx는 systemd에 enable돼 재부팅 후 다시 시작한다.
- EC2를 Stop하면 컴퓨팅 비용은 멈추지만 EBS와 공인 IPv4 등 별도 자원 비용은
  남을 수 있다.
- Elastic IP나 도메인이 없으면 EC2 Stop → Start 후 퍼블릭 IP가 바뀔 수 있다.
- IP가 바뀌면 보안 그룹 SSH 소스, `DJANGO_ALLOWED_HOSTS`,
  `DJANGO_CSRF_TRUSTED_ORIGINS`, 접속 URL을 갱신한다.
- RunPod는 AI 검수 때만 시작하고 `ready=true` 이후 기능을 테스트한다.
- MySQL named volume은 컨테이너를 다시 만들어도 유지되지만 EC2 삭제 전에는
  반드시 백업한다.

코드 업데이트 절차:

```bash
cd /home/ubuntu/skn_33_4th_5team
git pull
docker build -f Dockerfile.aws -t picare-web:aws .
docker stop picare-web
docker rm picare-web
```

그다음 16절의 DB 방식별 `docker run` 명령을 다시 실행한다. CI/CD를 붙일
때도 같은 빌드·교체 절차를 자동화하되 `.env`와 PEM을 저장소에 넣지 않는다.

## 22. 최종 체크리스트

1. EC2 보안 그룹은 22를 관리자 IP에만, 80·443을 공개한다.
2. 8000과 3306은 외부에 공개하지 않는다.
3. `.env` 권한은 600이며 Git 추적 대상이 아니다.
4. 선택 A는 MySQL 컨테이너가 `healthy`고, 선택 B는 RDS가 `사용 가능`이며
   퍼블릭 액세스가 꺼져 있다.
5. Django 컨테이너가 `Up`이고 migration이 완료됐다.
6. `127.0.0.1:8000` 내부 요청이 200이다.
7. Nginx를 통한 `http://<EC2_PUBLIC_IP>` 접속이 성공한다.
8. RunPod를 켰을 때 외부 `ready`가 `true`다.
9. 회원가입·로그인·Q&A·추천·미니 챌린지를 순서대로 확인한다.
10. 검수 후 RunPod와 불필요한 AWS 자원을 중지한다.
