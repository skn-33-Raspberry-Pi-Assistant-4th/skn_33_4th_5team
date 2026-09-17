# RunPod에서 PiCare Django 실행

이 문서는 Django 화면과 기존 Q&A·제품 추천의 Qwen/LoRA 경로를 같은 RunPod GPU Pod에서 실행하는 기준이다.
기존 `docs/runpod-streamlit-setup.md`는 이전 Streamlit 기준 문서이므로, 새 Django 실행은 이 문서를 따른다.

## 1. 프로젝트와 전용 가상환경

RunPod의 공용 Python 환경에는 다른 프로젝트의 `diffusers`가 설치돼 있을 수 있다. PiCare의
`transformers<5`와 `diffusers`가 요구하는 `huggingface-hub` 버전이 충돌할 수 있으므로 전용 venv를 사용한다.

```bash
cd /workspace
git clone https://github.com/skn-33-Raspberry-Pi-Assistant/skn_33_4th_5team.git
cd skn_33_4th_5team

python3 -m venv /workspace/venvs/picare-django
source /workspace/venvs/picare-django/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-gpu.txt
python -m pip check
```

`pip check`가 통과하지 않으면 공용 환경을 고치지 말고, 활성화된 venv의 `which python`과 `python -m pip --version`을 다시 확인한다.

## 2. 환경 설정, MySQL, 데이터 확인

```bash
cp .env.example .env

# .env에서 MYSQL_PASSWORD, MYSQL_ROOT_PASSWORD, DJANGO_SECRET_KEY를 강한 값으로 설정한다.

test -f document_pipeline/data/manifest_v3.json
test -f data/indexed/chroma_official_v3/picare-index.json
test -f data/products/catalog.json
test -f data/products/command_catalog.json
```

모델·색인·adapter·manifest는 Pod의 영속 `/workspace` volume에 준비한다. `LORA_ADAPTER_PATH`는 실제 adapter 위치와 일치해야 한다.

회원가입·로그인용 MySQL과 Redis 데이터는 Docker named volume에 보관된다. Pod를 종료·재생성할
때도 같은 Docker volume을 보존해야 가입 사용자와 세션이 유지된다. MySQL 포트는 로컬
`127.0.0.1`에만 열리며, Django 컨테이너는 Compose 내부 네트워크로 접속한다.

RunPod HTTP 프록시를 사용할 경우 `.env`의 `DJANGO_ALLOWED_HOSTS`에 실제 프록시 호스트를 추가한다. SSH 터널 방식이면 기본 `localhost,127.0.0.1`을 유지한다.

## 3. Django와 취소 가능한 Quiz worker 실행

실제 취소는 별도 GPU Celery 프로세스를 종료하는 방식이므로 Docker와 NVIDIA Container
Toolkit이 필요하다. `.env`에 MySQL 비밀번호와 Django Secret을 설정한 뒤 다음을 실행한다.

```bash
docker compose up --build
```

Compose는 MySQL, Redis, Django `web`, 단일 prefork GPU `quiz-worker`를 실행한다. web과
worker는 각각 Qwen을 로드하므로 GPU 메모리를 모두 합산해 확보한다. Quiz 생성 취소 시
Celery가 worker의 실행 프로세스에 `SIGTERM`을 보내고, prefork worker가 다음 task를 위해
새 프로세스를 띄운다.

처음 한 번은 다른 터미널에서 관리자를 만든다.

```bash
docker compose exec web python web_app/manage.py createsuperuser
```

Q&A 화면만 점검하는 경우에는 아래 직접 실행도 가능하다. 이 경우 Redis/Celery worker가
없으므로 동적 Quiz 시작 API는 `queue_unavailable`을 반환한다.

```bash
python web_app/manage.py check
python web_app/manage.py runserver 0.0.0.0:8000 --noreload
```

Mac에서 SSH 터널로 접속하려면 다음을 실행하고 브라우저에서 `http://127.0.0.1:8000/`을 연다.

```bash
ssh -p <RUNPOD_SSH_PORT> -L 8000:127.0.0.1:8000 root@<RUNPOD_IP>
```

## 기능별 설정 필요 범위

| 기능 | Qwen/LoRA | Chroma | 필수 데이터 |
| --- | --- | --- | --- |
| 명령어 실험실 | 필요 없음 | 필요 없음 | command catalog, v3 manifest, product catalog |
| 동적 미니 챌린지 | 필요 | Q&A와 동일 | 최신 Q&A 답변과 citation, Qwen worker |
| Q&A | `ANSWER_GENERATOR=huggingface`일 때 필요 | 필요 | manifest, Chroma |
| 제품 추천 | 필요 | 필요 | manifest, Chroma, product catalog, LoRA adapter |

명령어 실험실은 Qwen 장애 중에도 검수된 데이터로 동작한다. 동적 미니 챌린지는 Q&A web과
분리된 GPU Quiz worker를 사용한다.

회원가입은 `/accounts/signup/`, 로그인은 `/accounts/login/`에서 제공한다. RunPod HTTP 프록시를
쓴다면 `.env`의 `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`에 프록시 호스트를 추가하고,
HTTPS가 종료되는 프록시 환경에서는 `DJANGO_SESSION_COOKIE_SECURE=true`,
`DJANGO_CSRF_COOKIE_SECURE=true`를 설정한다.
