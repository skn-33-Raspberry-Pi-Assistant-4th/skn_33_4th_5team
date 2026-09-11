# RunPod Pod: Qwen3-4B RAG QA·제품 추천 실행

이 문서는 HTTP endpoint나 vLLM 없이 RunPod Pod 안에서 RAG와 Qwen3-4B Base
Instruct를 같은 Python 프로세스로 실행하는 절차다. 일반 QA에서는 조건 JSON 추출용
LoRA adapter를 사용하지 않지만, 제품 추천 CLI에서는 같은 계열 모델의 LoRA adapter로
조건만 추출한다.

## Pod 준비

1. CUDA PyTorch가 포함된 RunPod Pod와 24GB 이상 GPU를 선택한다.
2. 프로젝트와 실제 corpus/manifest를 `/workspace/skn_33_3rd_5team`에 둔다.
   `data/`는 Git에 포함되지 않을 수 있으므로 volume 또는 팀 공유 저장소에서 별도로
   복사한다.
3. Hugging Face 모델 cache는 Pod 종료 후에도 유지되도록 `/workspace`에 둔다.

```bash
cd /workspace/skn_33_3rd_5team
pip install -r requirements-gpu.txt
export HF_HOME=/workspace/.cache/huggingface
```

모델 접근 권한이 필요한 경우에만 `HF_TOKEN`을 Pod의 비밀 환경변수로 설정한다. API
Key, token, corpus 원문은 Git과 프로젝트 `.env.example`에 넣지 않는다.

## 설정과 실행

Pod의 프로젝트 최상위 `.env`에는 RAG 경로와 아래 생성기 설정을 둔다.

```env
# Django: SSH 터널 사용 시 아래 호스트 설정 그대로 사용한다.
# RunPod HTTP 프록시 사용 시 실제 프록시 호스트를 DJANGO_ALLOWED_HOSTS에 추가한다.
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

# Hugging Face 모델 캐시를 RunPod 영속 volume에 보관한다.
HF_HOME=/workspace/.cache/huggingface

# Q&A 답변 생성기: RunPod GPU에서 실제 Qwen을 사용한다.
ANSWER_GENERATOR=huggingface
ANSWER_MODEL_ID=Qwen/Qwen3-4B-Instruct-2507
ANSWER_MODEL_REVISION=main
ANSWER_LOAD_IN_4BIT=true
ANSWER_MAX_NEW_TOKENS=512
INFERENCE_DEVICE=cuda

# v3 공식 corpus·검색 색인·제품 데이터
DOCUMENT_MANIFEST=document_pipeline/data/manifest_v3.json
CHROMA_PATH=data/indexed/chroma_official_v3
CHROMA_COLLECTION_NAME=rpi_official
PRODUCT_CATALOG=data/products/catalog.json
MEDIA_MANIFEST=document_pipeline/data/media_manifest_v3.json
MEDIA_CHUNK_MAP=document_pipeline/data/media_chunk_map_v3.json
E5_MODEL_NAME=intfloat/multilingual-e5-base
DENSE_MAX_DISTANCE=0.48
TOP_K=5

# Django 명령어 실험실·미니 챌린지 데이터 경로
COMMAND_CATALOG=data/products/command_catalog.json
CHALLENGE_BANK=data/products/challenge_bank.json

# 제품 추천 조건 추출기: 학습 완료 QLoRA adapter를 사용한다.
CONDITION_EXTRACTOR=lora
CONDITION_MODEL_ID=Qwen/Qwen3-4B-Instruct-2507
LORA_ADAPTER_PATH=/workspace/models/picare-qwen3-4b-qlora
CONDITION_LOAD_IN_4BIT=true
```

`data/products/catalog.json`, `manifest_v3.json`, LoRA adapter는 Git 대상이 아니다.
Pod의 영속 `/workspace` volume 또는 팀 공유 경로에서 받은 동일 버전을 사용한다.
Manifest 1.1만 지원하므로 v3 corpus를 생성·배치한 뒤 Chroma를 반드시 `--reset`으로
재색인하고 QA 또는 제품 추천을 실행한다.

```bash
python3 -m src.services.rag_qa_cli --action index --reset
python3 -m src.services.rag_qa_cli \
  --query "SSH를 활성화하려면?" \
  --trace

# sLLM LoRA 조건 추출 + catalog + Hybrid RAG + Qwen 답변
python3 -m src.services.recommendation_rag_cli \
  --query "작은 스마트팜을 만들고 싶은데 어떤 모델이 좋을까?" \
  --trace
```

`--trace` 출력에는 검색 근거 수, `huggingface` provider, Qwen 모델명, 생성 시간,
생성 시도 횟수와 인용 검증 결과가 표시된다. 최초 Qwen 출력이 인용 형식만 어기면 공식
근거와 허용된 citation ID를 그대로 사용해 한 번만 형식 수정 재생성한다. 두 번째도 실패하면
원문 답변은 노출하지 않고 `error`로 보류한다. 근거 부족·가격·재고·프롬프트 인젝션 요청은 Qwen을 로드하거나
호출하지 않고 기존 보류·차단 정책을 따른다.

제품 추천에서는 후보를 catalog 규칙으로 먼저 확정하고, 그 후보가 참조한 `document_id`만
BM25와 Chroma 검색에 전달한다. 검색된 근거가 없는 후보는 카드와 답변에서 제외한다.
