# PiCare 초기 설정 가이드 - AWS

이 문서는 PiCare 4차 프로젝트의 Django 웹 서버를 AWS EC2에 배포하는 실제
절차를 정리한다. 수업 프로젝트 검수와 비용 절감을 위해 MySQL도 같은 EC2의
Docker 컨테이너로 실행한다. AI 추론은 AWS가 아닌 RunPod GPU API가 담당한다.

## 1. 구성과 역할

```text
인터넷 사용자
    │ HTTP 80 / 추후 HTTPS 443
    ▼
AWS EC2 Nginx
    │ 127.0.0.1:8000
    ▼
Django·Gunicorn 컨테이너
    ├─ Docker 내부망 → MySQL 컨테이너
    └─ HTTPS/Bearer Token → RunPod AI API
```

- Nginx는 외부 요청을 받고 Django로 전달한다.
- Django는 화면, 인증, 사용자 데이터와 AI 작업 상태를 관리한다.
- MySQL은 Docker named volume에 데이터를 저장한다.
- RunPod는 Qwen, LoRA, Hybrid RAG 추론만 담당한다.
- AWS에는 GPU 라이브러리나 모델 파일을 설치하지 않는다.
- 이 구성은 비용을 줄인 검수용이다. 운영 단계에서는 MySQL을 RDS로 분리할 수 있다.

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

기준 형식:

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

## 8. MySQL만 실행

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

## 9. AWS Django 이미지 빌드

```bash
docker build -f Dockerfile.aws -t picare-web:aws .
```

`pip`의 root 사용자 경고는 격리된 Docker 이미지 내부에서 설치하기 때문에 이
배포에서는 치명적인 오류가 아니다. 호스트 Python 환경을 변경하지 않는다.

빌드 결과를 확인한다.

```bash
docker image ls picare-web:aws
```

## 10. Django·Gunicorn 컨테이너 실행

MySQL 컨테이너가 속한 Compose 네트워크 이름을 가져온다.

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

`picare-web`은 `Up`, `picare-mysql`은 `Up ... (healthy)`여야 한다.

## 11. EC2 내부 웹 확인

```bash
curl -sS -o /dev/null \
  -w 'root=%{http_code}\n' \
  http://127.0.0.1:8000/

curl -sS -o /dev/null \
  -w 'login=%{http_code}\n' \
  http://127.0.0.1:8000/accounts/login/
```

두 요청 모두 `200`이면 Django와 MySQL이 정상 연결된 것이다. RunPod를 중지한
상태라면 AI 준비 상태만 실패하는 것은 정상이다.

## 12. Nginx 설치와 공개

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

## 13. RunPod 연동 확인

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

APP_NETWORK=$(docker inspect picare-mysql \
  --format '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{end}}')

docker run -d \
  --name picare-web \
  --restart unless-stopped \
  --network "$APP_NETWORK" \
  --env-file .env \
  -p 127.0.0.1:8000:8000 \
  picare-web:aws
```

## 14. 자주 발생하는 오류

| 증상 | 원인 | 확인·조치 |
| --- | --- | --- |
| SSH timeout | 22번 규칙의 관리자 IP 불일치 | 보안 그룹에서 현재 IP `/32`로 갱신 |
| `MYSQL_PASSWORD is missing` | `.env`에 정확한 변수가 없거나 빈 값 | 세 DB 비밀번호 변수 확인 |
| MySQL `starting` | 최초 DB·사용자 생성 중 | 수십 초 후 재확인 |
| MySQL `unhealthy` | 비밀번호·볼륨·초기화 실패 | MySQL 로그 확인 |
| Django `Can't connect ... 127.0.0.1` | 컨테이너에서 잘못된 DB 호스트 사용 | `DJANGO_DB_HOST=picare-mysql` |
| 웹 컨테이너가 즉시 종료 | migration 또는 DB 인증 실패 | `docker logs picare-web` |
| Nginx 502 | Django 미실행 또는 8000 바인딩 실패 | `docker ps`, 내부 curl 확인 |
| Django 400 | 퍼블릭 IP가 `DJANGO_ALLOWED_HOSTS`에 없음 | `.env` 수정 후 컨테이너 재생성 |
| AI 인증 실패 | AWS·RunPod 토큰 불일치 | 동일 토큰으로 교체 후 양쪽 재시작 |
| AI 연결 실패 | RunPod 중지·로딩 중·URL 오류 | `live`, `ready`, `-8000` URL 확인 |

## 15. 재부팅·업데이트·비용 관리

- MySQL과 Django는 `restart: unless-stopped`로 EC2 재부팅 후 다시 시작한다.
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

그다음 10절의 네트워크 확인과 `docker run` 명령을 다시 실행한다. CI/CD를 붙일
때도 같은 빌드·교체 절차를 자동화하되 `.env`와 PEM을 저장소에 넣지 않는다.

## 16. 최종 체크리스트

1. EC2 보안 그룹은 22를 관리자 IP에만, 80·443을 공개한다.
2. 8000과 3306은 외부에 공개하지 않는다.
3. `.env` 권한은 600이며 Git 추적 대상이 아니다.
4. MySQL 컨테이너가 `healthy`다.
5. Django 컨테이너가 `Up`이고 migration이 완료됐다.
6. `127.0.0.1:8000` 내부 요청이 200이다.
7. Nginx를 통한 `http://<EC2_PUBLIC_IP>` 접속이 성공한다.
8. RunPod를 켰을 때 외부 `ready`가 `true`다.
9. 회원가입·로그인·Q&A·추천·미니 챌린지를 순서대로 확인한다.
10. 검수 후 RunPod와 불필요한 AWS 자원을 중지한다.
