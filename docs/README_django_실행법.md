# 로컬 Django + MySQL 실행

PiCare의 회원가입·로그인·서버 세션은 MySQL을 사용한다. 로컬에서는 Docker Compose로
MySQL 8.4만 실행하고, Django는 호스트의 전용 Python 가상환경에서 실행한다.

## 빠른 초기 설정

새 팀원은 Docker Desktop을 실행한 뒤 저장소 루트에서 아래 명령 하나로 로컬 개발 환경을 준비할 수 있다.

```bash
python scripts/init.py
```

스크립트는 `.env`가 없을 때만 개발용 비밀번호·Django Secret을 생성하고, `.venv`와 의존성을
준비한 뒤 MySQL이 healthy 상태가 될 때까지 기다리고 `migrate`를 실행한다. 기존 `.env` 및
Docker volume은 변경하거나 삭제하지 않는다. RunPod 환경에서는 이 스크립트 대신
`scripts/runpod/start_mysql.sh`를 사용한다.

## 1. 환경 변수와 MySQL 시작

```bash
cd /path/to/skn_33_4th_5team
cp .env.example .env
```

`.env`에서 아래 두 값을 서로 다른 강한 비밀번호로 설정한다. `.env`는 Git에 포함하지 않는다.

```env
MYSQL_PASSWORD=<PiCare 앱 계정 비밀번호>
MYSQL_ROOT_PASSWORD=<로컬 MySQL 관리자 비밀번호>
DJANGO_SECRET_KEY=<개발용 랜덤 문자열>
```

MySQL을 시작하고 준비 상태를 확인한다.

```bash
docker compose up -d mysql
docker compose ps
```

DB는 Docker named volume `picare_mysql_data`에 보관된다. 로컬 DB를 초기화해야 할 때만
`docker compose down -v`를 사용한다. 이 명령은 가입 사용자와 세션을 포함한 로컬 DB를 지운다.

## 2. Django 마이그레이션과 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python web_app/manage.py migrate
python web_app/manage.py createsuperuser
python web_app/manage.py runserver
```

`migrate`는 기본 Django `User`·권한·DB 세션 테이블을 생성한다. 회원가입 화면은
`http://127.0.0.1:8000/accounts/signup/`, 로그인 화면은
`http://127.0.0.1:8000/accounts/login/`이다.

## 3. 테스트

자동 테스트는 Django 테스트 러너가 만드는 별도 테스트 데이터베이스에서 실행한다.

```bash
python web_app/manage.py test tests.test_django_auth tests.test_django_web
```

MySQL 연결을 확인할 때는 Compose가 준비된 상태에서 `python web_app/manage.py migrate`와
회원가입·로그인 흐름을 직접 확인한다.
