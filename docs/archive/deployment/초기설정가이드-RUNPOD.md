# PiCare 초기 설정 가이드 - RUNPOD

이 문서는 PiCare 4차 프로젝트를 RunPod GPU Pod의 AI 추론 API로 실행하고,
AWS Django가 해당 API를 호출하기까지의 실제 설정 순서를 정리한다.

## 1. 배포 구조

```text
브라우저 → AWS EC2 Django → HTTPS/Bearer Token → RunPod GPU API
          화면·인증·DB·상태                    Qwen·LoRA·Hybrid RAG
```

- AWS Django는 화면, 인증, MySQL, 작업 상태를 담당한다.
- RunPod는 Qwen 모델, LoRA adapter, RAG 검색 색인을 담당한다.
- `AI_API_TOKEN`은 OpenAI 키나 RunPod 플랫폼 API 키가 아니다.
- `AI_API_TOKEN`은 AWS와 RunPod 사이의 내부 인증용 공유 비밀값이다.

## 2. RunPod 프로젝트와 virtualenv

```bash
cd /workspace
git clone <프로젝트_Git_URL> skn_33_4th_5team
cd /workspace/skn_33_4th_5team

python3 -m venv /workspace/venvs/picare
source /workspace/venvs/picare/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-gpu.txt
python -m pip check
```

실행 전에는 전용 환경이 활성화됐는지 확인한다.

```bash
which python
python -m pip --version
```

프롬프트에 `(picare)`가 표시되어야 한다. `conda`가 없는 이미지에서는
`/workspace/venvs/picare/bin/activate`를 사용한다.

## 3. GPU와 배포 자산 확인

```bash
python -c "import torch; print('torch:', torch.__version__); print('CUDA:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '없음')"
```

RunPod의 `/workspace` 영속 볼륨에 다음 자산을 준비한다.

```text
/workspace/skn_33_4th_5team/document_pipeline/data/manifest_v3.json
/workspace/skn_33_4th_5team/data/indexed/chroma_official_v3/picare-index.json
/workspace/skn_33_4th_5team/data/indexed/chroma_official_v3/chroma.sqlite3
/workspace/skn_33_4th_5team/document_pipeline/data/media_manifest_v3.json
/workspace/skn_33_4th_5team/document_pipeline/data/media_chunk_map_v3.json
/workspace/skn_33_4th_5team/data/products/catalog.json
/workspace/models/picare-qwen3-4b-qlora/adapter_config.json
/workspace/models/picare-qwen3-4b-qlora/adapter_model.safetensors
```

자산을 모두 준비한 뒤 검증한다.

```bash
python scripts/verify_deployment_assets.py \
  --target runpod \
  --adapter-path /workspace/models/picare-qwen3-4b-qlora
```

정상 기준은 `ok: true`, 문서 23개, 청크 381개, 색인 청크 381개,
제품 5개 이상, adapter 설정과 safetensors 확인이다.

## 4. Hugging Face 의존성

`requirements-gpu.txt`에는 빠른 Hugging Face 다운로드를 위해 다음 항목이 포함되어야 한다.

```text
hf_transfer>=0.1.9,<1
```

현재 virtualenv에서 설치한다.

```bash
python -m pip install -r requirements-gpu.txt
```

`HF_HUB_ENABLE_HF_TRANSFER=1`인데 `hf_transfer`가 없으면 다음으로 해결한다.

```bash
python -m pip install hf_transfer
```

## 5. Secret과 RunPod 환경변수

인증 토큰은 한 번 생성하고 AWS와 RunPod에 같은 값을 사용한다.

```bash
openssl rand -hex 32
```

RunPod Secret 예시:

```text
Secret name: SKN_33_PICARE_AI_API_TOKEN
Description: PiCare AWS Django와 RunPod AI API 간 내부 인증용 토큰
Secret value: 생성한 64자리 난수
```

Environment Variables에서 위 Secret을 `AI_API_TOKEN`에 연결한다.

RunPod 기준 환경변수:

```text
AI_API_PORT=8000
AI_API_TOKEN=<RunPod Secret 연결>
AI_MAX_QUEUED=8
AI_JOB_TIMEOUT=300
AI_RESULT_RETENTION=1800
AI_STARTUP_SMOKE=true
PICARE_PROJECT_ROOT=/workspace/skn_33_4th_5team
HF_HOME=/workspace/.cache/huggingface
INFERENCE_DEVICE=cuda
ANSWER_GENERATOR=huggingface
ANSWER_MODEL_ID=Qwen/Qwen3-4B-Instruct-2507
ANSWER_MODEL_REVISION=main
ANSWER_LOAD_IN_4BIT=true
ANSWER_MAX_NEW_TOKENS=512
DOCUMENT_MANIFEST=/workspace/skn_33_4th_5team/document_pipeline/data/manifest_v3.json
CHROMA_PATH=/workspace/skn_33_4th_5team/data/indexed/chroma_official_v3
CHROMA_COLLECTION_NAME=rpi_official
E5_MODEL_NAME=intfloat/multilingual-e5-base
DENSE_MAX_DISTANCE=0.48
TOP_K=5
MEDIA_MANIFEST=/workspace/skn_33_4th_5team/document_pipeline/data/media_manifest_v3.json
MEDIA_CHUNK_MAP=/workspace/skn_33_4th_5team/document_pipeline/data/media_chunk_map_v3.json
PRODUCT_CATALOG=/workspace/skn_33_4th_5team/data/products/catalog.json
CONDITION_EXTRACTOR=lora
CONDITION_MODEL_ID=Qwen/Qwen3-4B-Instruct-2507
CONDITION_LOAD_IN_4BIT=true
LORA_ADAPTER_PATH=/workspace/models/picare-qwen3-4b-qlora
```

`AI_API_URL`은 RunPod에 넣지 않는다. RunPod API는 자기 자신에서 실행되므로
외부 주소가 필요하지 않다.

## 6. RunPod 포트 설정

Pod 설정에서 다음처럼 포트를 노출한다.

```text
Expose HTTP ports: 8888, 8000
Expose TCP ports: 22
```

- `8888`: JupyterLab
- `8000`: PiCare AI API
- `22`: SSH

실행 중인 Pod의 포트를 수정하면 Pod가 reset된다. `/workspace`의 프로젝트,
모델, virtualenv는 유지되지만 컨테이너 루트 파일시스템의 변경사항은 사라질 수 있다.

## 7. RunPod API 실행

Pod reset 이후에는 virtualenv를 다시 활성화한다.

```bash
source /workspace/venvs/picare/bin/activate
cd /workspace/skn_33_4th_5team
python -m src.runpod_api
```

정상 로그:

```text
Listening at: http://0.0.0.0:8000
Booting worker
```

실행 중인 터미널은 계속 열어 둔다.

## 8. 내부·외부 Health Check

RunPod 내부의 새 터미널에서 확인한다.

```bash
ss -lntp | grep ':8000'
curl -i http://127.0.0.1:8000/health/live
curl -i \
  -H "Authorization: Bearer $AI_API_TOKEN" \
  http://127.0.0.1:8000/health/ready
```

정상 완료 응답:

```json
{"ready": true, "message": "Qwen·LoRA·Hybrid RAG 런타임 준비 완료"}
```

첫 실행이나 reset 직후 `ready: false`가 수 분간 유지될 수 있다.
`Loading checkpoint shards: 3/3`은 캐시된 모델을 GPU에 로드하는 과정이다.
`torch_dtype`와 generation flags 메시지는 오류가 아닌 경고다.

Pod ID가 `d8a3br05bcorxj`라면 외부 URL은 다음과 같다.

```bash
curl -i https://d8a3br05bcorxj-8000.proxy.runpod.net/health/live
curl -i \
  -H "Authorization: Bearer $AI_API_TOKEN" \
  https://d8a3br05bcorxj-8000.proxy.runpod.net/health/ready
```

URL에서 `-8000`을 빼면 안 된다. SSH 외부 포트인 `22000`번대 포트도 API 주소에
사용하지 않는다.

`RUNPOD_POD_ID`가 제공되는 경우 현재 셸에서 주소를 만들 수 있다.

```bash
export AI_API_URL="https://${RUNPOD_POD_ID}-8000.proxy.runpod.net"
```

이 명령은 AWS `.env`까지 자동으로 수정하지 않는다.

## 9. 오류별 조치

| 증상 | 의미 | 조치 |
| --- | --- | --- |
| 내부 `live` 200 | API와 컨테이너 포트 정상 | 외부 HTTP 포트 확인 |
| 외부 `502 Waiting for service` | HTTP 8000 미노출 또는 API 미실행 | HTTP 8000 추가 후 API 실행 |
| 외부 `404`, URL에 `-8000` 없음 | 잘못된 Proxy 주소 | `https://<POD_ID>-8000.proxy.runpod.net` 사용 |
| 외부 `404`, 로그에 `GET /` | RunPod 연결 확인 요청 | `/health/live`로 확인 |
| `ready=false` 초기 메시지 | 모델·색인 로딩 중 | 수 분 대기 후 재확인 |
| `런타임 준비 실패: ValueError` | 런타임 초기화 실패 | 전체 traceback 확인 |
| `hf_transfer` ValueError | 빠른 다운로드 패키지 누락 | `pip install hf_transfer` |

전체 traceback이 필요하면 API 프로세스를 중지한 뒤 실행한다.

```bash
cd /workspace/skn_33_4th_5team
python -c "from pathlib import Path; from src.runpod_api.runtime import PiCareRuntime; PiCareRuntime(Path.cwd()).initialize()"
```

## 10. AWS Django 설정

AWS EC2 생성, 보안 그룹, Docker MySQL, Django·Gunicorn, Nginx 공개 설정은
[`초기설정가이드-AWS.md`](./초기설정가이드-AWS.md)에 실제 진행 순서대로
상세히 정리했다. 아래는 RunPod 연결에 필요한 핵심 설정이다.

AWS EC2에서 Django를 실행할 때 AWS 프로젝트의 `.env`에 설정한다. RunPod의
`.env`와 AWS의 `.env`는 역할이 다르다.

```env
PICARE_AI_BACKEND=remote
AI_API_URL=https://<POD_ID>-8000.proxy.runpod.net
AI_API_TOKEN=<RunPod Secret과 동일한 값>
AI_HTTP_TIMEOUT=10
AI_JOB_TIMEOUT=300
```

AWS `.env`는 GitHub에 commit하지 않는다. 초기에는 EC2에 직접 설정하고,
CI/CD에서는 GitHub Actions Secret이나 AWS Secrets Manager에서 주입한다.

EC2 배포 확인:

```bash
cd <AWS_DJANGO_PROJECT_ROOT>
python web_app/manage.py migrate
python web_app/manage.py collectstatic --noinput
gunicorn picare_web.wsgi:application \
  --chdir web_app \
  --bind 127.0.0.1:8000 \
  --workers 2 \
  --timeout 30
```

## 11. 재시작과 보안

- 같은 Pod에서 API만 재실행하면 Pod ID는 유지된다.
- 같은 Pod를 Stop → Start해도 보통 Pod ID는 유지된다.
- Pod를 삭제하고 새로 배포하면 Pod ID가 바뀌므로 AWS `AI_API_URL`을 수정한다.
- SSH 외부 포트는 바뀔 수 있지만 API URL의 `-8000`과는 별개다.
- `.env`, `.env_copy`, PEM 파일, API 키를 Git에 올리지 않는다.
- `OPENAI_API_KEY`, `HF_TOKEN`, `AI_API_TOKEN`을 서로 바꾸지 않는다.
- Jupyter 비밀번호나 Secret 값이 화면·로그에 노출되면 즉시 교체한다.
- `ready=true` 전에는 AWS에서 원격 AI 요청을 열지 않는다.

## 12. 최종 확인 순서

1. `python -m pip check` 통과
2. 배포 자산 검증 결과 `ok: true`
3. RunPod 내부 `/health/live`가 200
4. RunPod 내부 `/health/ready`가 `ready: true`
5. RunPod 외부 `/health/live`가 200
6. AWS `.env`에 실제 `AI_API_URL`과 동일한 `AI_API_TOKEN` 설정
7. AWS Django 재시작
8. 로그인, Q&A, 추천, 동적 미니 챌린지 순서로 smoke test
