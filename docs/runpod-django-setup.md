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

## 2. 환경 설정과 데이터 확인

```bash
cp .env.example .env

test -f document_pipeline/data/manifest_v3.json
test -f data/indexed/chroma_official_v3/picare-index.json
test -f data/products/catalog.json
test -f data/products/command_catalog.json
test -f data/products/challenge_bank.json
```

모델·색인·adapter·manifest는 Pod의 영속 `/workspace` volume에 준비한다. `LORA_ADAPTER_PATH`는 실제 adapter 위치와 일치해야 한다.

RunPod HTTP 프록시를 사용할 경우 `.env`의 `DJANGO_ALLOWED_HOSTS`에 실제 프록시 호스트를 추가한다. SSH 터널 방식이면 기본 `localhost,127.0.0.1`을 유지한다.

## 3. Django 실행

```bash
python web_app/manage.py check
python web_app/manage.py runserver 0.0.0.0:8000 --noreload
```

`--noreload`는 Qwen 모델이 자동 재로더 프로세스에서 중복 로드되는 것을 막는다.

Mac에서 SSH 터널로 접속하려면 다음을 실행하고 브라우저에서 `http://127.0.0.1:8000/`을 연다.

```bash
ssh -p <RUNPOD_SSH_PORT> -L 8000:127.0.0.1:8000 root@<RUNPOD_IP>
```

## 기능별 설정 필요 범위

| 기능 | Qwen/LoRA | Chroma | 필수 데이터 |
| --- | --- | --- | --- |
| 명령어 실험실 | 필요 없음 | 필요 없음 | command catalog, v3 manifest, product catalog |
| 미니 챌린지 | 필요 없음 | 필요 없음 | challenge bank, v3 manifest |
| Q&A | `ANSWER_GENERATOR=huggingface`일 때 필요 | 필요 | manifest, Chroma |
| 제품 추천 | 필요 | 필요 | manifest, Chroma, product catalog, LoRA adapter |

명령어 실험실과 미니 챌린지는 Qwen 장애 중에도 검수된 데이터로 동작하도록 구현한다. Qwen/LoRA 설정은 Django 전체 서비스에서 기존 Q&A·제품 추천도 함께 제공할 때 사용한다.
