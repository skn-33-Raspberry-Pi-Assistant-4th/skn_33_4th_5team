# PiCare AWS–RunPod 배포·복구 운영서

이 문서는 AWS EC2가 화면·인증·저장을 담당하고 RunPod Pod가 모든 AI 추론을 담당하는 팀 검수 환경을 다룬다. 도메인과 공개 웹 포트 없이 SSH 터널로 검수하는 구성이 기본이다.

## 1. 배포 전 확인

비밀값은 저장소나 Docker 이미지에 넣지 않는다. AWS와 RunPod에 동일한 `AI_API_TOKEN`을 각 호스트의 비밀 환경변수로 설정한다. 이 값은 RunPod 플랫폼 관리 API 키가 아니라 PiCare 서버끼리만 공유하는 충분히 긴 난수다.

RunPod 영속 볼륨에는 다음 자산이 있어야 한다.

- Qwen 기반 모델 캐시
- `/workspace/models/picare-qwen3-4b-qlora` LoRA 어댑터
- 공식 문서 23개·381개 청크의 manifest와 Chroma 색인
- 제품 카탈로그와 미디어 manifest

RunPod에서 모델을 시작하기 전에 전체 자산을 검증한다.

```bash
python scripts/verify_deployment_assets.py \
  --target runpod \
  --adapter-path /workspace/models/picare-qwen3-4b-qlora
```

AWS 배포 묶음은 다음 명령으로 명령어 실험실의 승인된 100개 템플릿과 Django 진입점을 확인한다.

```bash
python scripts/verify_deployment_assets.py --target aws
```

검증 실패 상태에서는 서비스를 시작하지 않는다. `--skip-adapter`는 CPU CI와 AWS 점검 전용이며 RunPod 배포 승인에 사용하지 않는다.

## 2. RunPod 시작과 확인

RunPod 환경변수의 기준값은 다음과 같다. 실제 모델·색인 경로는 영속 볼륨의 위치와 맞춘다.

```text
AI_API_TOKEN=<AWS와 공유한 32자 이상 난수>
AI_MAX_QUEUED=8
AI_JOB_TIMEOUT=300
AI_RESULT_RETENTION=1800
ANSWER_GENERATOR=huggingface
HF_HOME=/workspace/.cache/huggingface
INFERENCE_DEVICE=cuda
DOCUMENT_MANIFEST=/app/document_pipeline/data/manifest_v3.json
CHROMA_PATH=/app/data/indexed/chroma_official_v3
CHROMA_COLLECTION_NAME=rpi_official
E5_MODEL_NAME=intfloat/multilingual-e5-base
TOP_K=5
PRODUCT_CATALOG=/app/data/products/catalog.json
MEDIA_MANIFEST=/app/document_pipeline/data/media_manifest_v3.json
MEDIA_CHUNK_MAP=/app/document_pipeline/data/media_chunk_map_v3.json
CONDITION_EXTRACTOR=lora
CONDITION_MODEL_ID=Qwen/Qwen3-4B-Instruct-2507
CONDITION_LOAD_IN_4BIT=true
LORA_ADAPTER_PATH=/workspace/models/picare-qwen3-4b-qlora
```

`ANSWER_MODEL_ID`, `ANSWER_MODEL_REVISION`, `ANSWER_LOAD_IN_4BIT`,
`ANSWER_MAX_NEW_TOKENS`, `DENSE_MAX_DISTANCE`는 저장소의 `.env.example` 값을
`.env`로 복사해 주입하거나 Pod 환경변수로 지정한다. 어댑터·모델 캐시·색인을
영속 볼륨에 두는 경우 위 절대 경로만 해당 마운트 경로로 바꾼다.

컨테이너는 AI API를 기본 `0.0.0.0:8000`에 바인딩한다. RunPod Pod 설정에서 HTTP 포트 `8000`을 노출하고 AWS의 `AI_API_URL`에는 `https://<POD_ID>-8000.proxy.runpod.net`을 사용한다. 포트를 바꾸려면 RunPod의 `AI_API_PORT`, 노출 포트, AWS URL을 함께 바꾼다. 브라우저 코드에는 이 주소나 인증키를 넣지 않는다.

기동 직후 다음 순서로 확인한다.

```bash
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS -H "Authorization: Bearer $AI_API_TOKEN" \
  http://127.0.0.1:8000/health/ready
```

`live`는 HTTP 프로세스 상태, `ready`는 모델·LoRA·검색 색인을 실제로 사용할 수 있는 상태다. `ready=false`라면 AWS를 연결하지 않고 RunPod 로그에서 누락 자산이나 모델 로딩 오류를 해결한다.

## 3. AWS 시작과 SSH 터널 검수

기존 MySQL은 유지한다. 처음 배포할 때는 DB를 백업한 뒤 `AiJob` 추가 migration을 적용한다. migration은 기존 사용자·질문·추천 테이블을 변경하지 않는다.

AWS 필수 환경변수는 다음과 같다.

```text
PICARE_AI_BACKEND=remote
AI_API_URL=https://<POD_ID>-8000.proxy.runpod.net
AI_API_TOKEN=<RunPod와 공유한 32자 이상 난수>
AI_HTTP_TIMEOUT=10
AI_JOB_TIMEOUT=300
DJANGO_DEBUG=false
DJANGO_SECRET_KEY=<운영 난수>
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
```

DB 연결값은 기존 `DJANGO_DB_*` 또는 `MYSQL_*` 환경변수를 그대로 사용한다. 이후 migration과 정적 파일을 준비하고 운영 WSGI 서버를 시작한다.

```bash
python web_app/manage.py migrate
python web_app/manage.py collectstatic --noinput
gunicorn picare_web.wsgi:application \
  --chdir web_app --bind 127.0.0.1:8000 --workers 2 --timeout 30
```

EC2 보안 그룹은 SSH 22번만 검수자 IP에 허용하고 8000번을 외부에 열지 않는다. 검수자 PC에서 터널을 연결한다.

```bash
ssh -L 8000:127.0.0.1:8000 <EC2_USER>@<EC2_HOST>
```

브라우저에서 `http://127.0.0.1:8000`을 열어 회원가입·로그인 후 Q&A, 추천, 미니 챌린지를 순서대로 확인한다.

## 4. 로컬 모의 API로 AWS만 검증

RunPod가 준비되지 않아도 AWS 연결과 오류 화면을 확인할 수 있다.

```bash
AI_API_TOKEN=local-only-test-token-at-least-32-bytes \
python scripts/mock_ai_api.py --port 8081 --delay-seconds 2
```

AWS 테스트 환경의 `AI_API_URL`을 `http://127.0.0.1:8081`로 설정한다. 실패 흐름은 `--mode failure`, 장시간 실행과 취소는 큰 `--delay-seconds` 값으로 재현한다. 이 서버는 테스트용 메모리 저장소이므로 운영에 사용하지 않는다.

## 5. 재시작·장애·복구

RunPod를 재시작하면 메모리에 있던 대기·실행 작업은 사라진다. 모델과 색인은 영속 볼륨에서 다시 로드된다. AWS가 사라진 작업을 조회해 404를 받으면 해당 작업을 `expired`로 종료하고 사용자가 다시 요청하도록 안내한다. 사용자 기록과 이미 완료된 저장 결과는 MySQL에 남는다.

재시작은 다음 순서로 수행한다.

1. AWS에서 새 AI 요청 유입을 중지하고 현재 작업 ID와 상태를 기록한다.
2. 가능하면 실행 중 작업이 종료될 때까지 기다린 뒤 RunPod 컨테이너를 재시작한다.
3. `live`, 자산 검증, `ready` 순서로 확인한다. `ready=true` 전에는 요청 유입을 재개하지 않는다.
4. 재시작 전 `queued`·`running` 작업을 AWS에서 다시 조회한다. 404이면 동일 payload를 같은 ID로 자동 재제출하지 않고 `expired`로 종료한다.
5. Q&A·추천·퀴즈 smoke test를 각각 새 작업 ID로 실행한 뒤 요청 유입을 재개한다.

장애별 복구 순서는 다음과 같다.

| 증상 | 확인 | 복구 |
|---|---|---|
| `live` 실패 | 컨테이너 프로세스·포트 | AI 컨테이너 재시작 |
| `live=true`, `ready=false` | 자산 검증기·GPU 메모리·모델 로그 | 자산 복구 후 RunPod 재시작 |
| AWS에서 인증 실패 | 양쪽 `AI_API_TOKEN` | 키를 같은 새 값으로 교체 후 두 서비스 재시작 |
| 작업이 300초 초과 | RunPod 작업 로그 | 취소 종료 확인 후 다음 작업 smoke test |
| RunPod 재시작 뒤 진행 중 작업 만료 | AWS 상태 조회 | 사용자 재요청; DB 결과를 임의 복원하지 않음 |
| AWS만 장애 | Gunicorn·MySQL 연결 | AWS 앱 재시작; RunPod 작업은 같은 job ID로 재조회 |

배포본에 문제가 있으면 AWS와 RunPod 이미지를 직전 검증 태그로 각각 되돌린다. 이번 DB 변경은 새 `AiJob` 테이블 추가뿐이므로 즉시 역 migration해 사용자 데이터를 위험하게 만들 필요가 없다. 이전 앱은 추가 테이블을 무시한다. 복구 후 자산 검증과 세 기능 smoke test를 다시 수행한다.

## 6. 팀 검수 순서

1. 로그인하지 않은 세션과 로그인 사용자 각각 Q&A를 실행한다.
2. 같은 완료 상태를 반복 조회해 질문 기록이 한 번만 생기는지 확인한다.
3. 추천 완료 직후에는 기록이 없고 저장 버튼을 누른 뒤 한 번만 생기는지 확인한다.
4. 퀴즈 제출 전 응답과 브라우저 소스에 정답 필드가 없는지 확인한다.
5. 실행 중 작업을 취소하고 다음 작업이 정상 완료되는지 확인한다.
6. 다른 브라우저 세션에서 작업 ID를 직접 조회해 404가 반환되는지 확인한다.
7. RunPod를 재시작해 진행 중 작업은 만료되고 저장된 사용자 기록은 유지되는지 확인한다.
