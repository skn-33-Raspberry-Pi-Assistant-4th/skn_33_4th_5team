# B 명령어 실험실 및 E·D 연결 계약

명령어 실험실 로직은 `src/services/command_lab_service.py`에 있으며, Django 기본 UI와
기존 Streamlit 화면이 같은 검수 카탈로그를 사용한다. Django는 명령을 실행하지 않는
표시 계층이고, B 서비스는 Streamlit·Django 어느 쪽에도 의존하지 않는다. 회원가입·로그인과
DB 세션은 Django `accounts` 앱이 담당하며, 명령어 실험실 자체는 인증 없이 계속 사용할 수 있다.

## 실행

프로젝트 기본 의존성을 설치한 Python 환경에서 실행한다.

```bash
python -m src.services.command_lab_cli --audit
python -m src.services.command_lab_cli --command "ssh pi@192.168.0.12"
python web_app/manage.py runserver
```

브라우저에서 `http://127.0.0.1:8000/lab/`을 연다. 기존 Streamlit 검증 화면은
`streamlit run streamlit_app/app.py --server.port 8511`로 계속 사용할 수 있다.
실험실 자체에는 GPU·LoRA·Chroma가 필요하지 않지만 A의 공식 manifest는 필요하다.
Q&A 이동 후 질문 제출은 기존 QA 서비스를 호출하며, 제품 추천 이동은 기존 추천 화면을 사용한다.

새 환경에서는 `.env.example`을 `.env`로 복사하고 아래 명령으로 문서와 Chroma를 준비한다.
이미 동일 manifest를 생성했다면 QA CLI의 `--action index`로 색인만 생성할 수 있다.

```bash
python -m document_pipeline.ingestion.run_pipeline --commit 75331a79fbf32d2403b7547729ddccf553873b09
```

원문은 고정된 Raspberry Pi 공식 문서 commit에서 받는다. E5는 검색용 임베딩 모델이며
재색인은 해당 모델을 재학습하는 작업이 아니다. 생성 manifest와 Chroma, `.env`는 Git 제외 대상이다.
제품 추천의 실제 Qwen/LoRA 추론에는 별도로 실제 `LORA_ADAPTER_PATH`와 모델 실행 환경이 필요하다.
`.env.example`의 `/workspace/models/...`는 예시 경로이므로 로컬 준비 완료를 의미하지 않는다.

## B 서비스 호출

```python
from src.services.command_lab_service import CommandLabService, CommandLabError

lab = CommandLabService()
templates = lab.list_templates()  # approved + 근거 검증 통과 항목만
result = lab.compose(
    "cmd-remote-access-004",
    {"part-02": "pi@192.168.0.12"},
    product_id="raspberry-pi-5",
)
analyzed = lab.analyze("ssh pi@192.168.0.12")
```

`result`에는 재조합 명령, 부분별 설명, 사용 위치, 위험도·주의사항,
공식 근거 청크 및 선택한 제품 정보가 포함된다. 모든 결과는 `execution_policy=display_only`다.
명령 실행 함수는 없다. 알려진 템플릿에 일치하지 않으면 `CommandLabError`로 안내한다.
ID는 A의 `cmd-{topic}-{번호}` 형식을 그대로 유지한다. 92개 draft는 목록·직접 ID 접근 모두 차단한다.

HTTP API에서 E는 `CommandLabError`를 입력 오류 응답으로 변환한다. Django의 현재 경로는
목록 `GET /api/lab/templates`, 분석 `POST /api/lab/analyze`, 재조합 `POST /api/lab/compose`다.
POST API는 Django CSRF 보호를 받으며 JSON 요청 본문을 사용한다. 브라우저 응답에는 출처 제목·섹션·URL만
포함하고 manifest checksum은 반환하지 않는다.

## 서랍 및 제품 연결

```python
saved = lab.drawer_payload("cmd-remote-access-004", {"part-02": "pi@host"},
                           product_id="raspberry-pi-5")
# E: request.user 소유 레코드에 saved JSON 저장
# E: 조회 시에도 현재 사용자 소유권을 먼저 확인
restored = lab.restore_drawer(saved)
```

저장 데이터의 필드는 `schema_version`, `kind`, `template_id`, `catalog_version`, `values`,
`product_id`, `command_snapshot`, `command_checksum`, `evidence_ids`, `evidence_checksums`다.
이 JSON에는 사용자 ID를 넣지 않는다. E가 인증 세션에서 소유자를 결정해야 한다.
클라이언트가 보내는 명령·체크섬을 저장의 기준으로 삼지 말고 서버에서 `drawer_payload`로 재생성한다.
복원 시 버전·명령·근거 변경을 감지하면 재확인을 요구한다. 체크섬은 변경 탐지용이며 서명은 아니다.

제품 ID는 기존 `data/products/catalog.json`과 동일하다. E의 보유 제품에서 받은 ID를
`product_id`로 넘긴다. `document_scope_match`는 공식 문서의 제품 메타데이터 일치 여부이며
명령의 실행 가능 여부나 장치 상태 검증을 뜻하지 않는다.
현재 Streamlit에는 제품 선택, 브라우저 세션 임시 서랍 및 JSON 내보내기를 제공한다.
회원별 영구 저장은 E의 DB 연결 전까지 제공하지 않는다.

## 기존 AI 서비스 연결

```python
question = lab.qa_question("cmd-remote-access-004", {"part-02": "pi@host"},
                           product_id="raspberry-pi-5")
# 기존 RagQaService 인스턴스
response = qa_service.answer(request_id=request_id, question=question,
                             retrieval_mode="hybrid")
# 추천은 기존 RecommendationRagService.answer_form(form=RecommendationFormInput(...)) 사용
```

실험실은 명령 설명을 카탈로그에서 읽으며 LLM이 명령·출처·제품 ID를 만들지 않는다.
화면에서 Q&A 이동 시 변경한 입력값까지 전달하며 자동 제출하지 않는다.
이미 있는 추천·Q&A 응답 계약을 변경하지 않는다.

## A 데이터 보완

- 100개 명령·10개 챌린지의 ID 및 근거 checksum 검증을 통과했다.
- `<username>@<ip address>`를 하나의 구성 요소로 유지하도록 생성기 토큰화를 수정했다.
- 승인된 SSH·ssh-copy-id의 사용자명@주소를 편집 가능하게 만들었다.
- 승인 명령의 일반적인 반복 설명을 구성 요소별 설명으로 보완했다.
- 원격 접속용 `sudo raspi-config`의 근거를 NVMe 부팅 문단에서 SSH 활성화 문단으로 교정했다.
- 새 문서 5개 및 카테고리 7개의 한국어 출처 라벨을 추가했다.
- 승인 8개·초안 92개 상태와 기존 template ID를 유지했다. 수정 데이터 버전은 `2026-09-11-command-lab-v2.1`이다.
- 초안에는 카메라 빌드 명령이 OS 설치 주제로 묶이거나 일반적인 설명이 남은 항목이 있으므로
  구조 검증 통과를 의미 검수 완료로 간주하지 않는다. A 검수 후에만 승인해서 노출한다.

## 재학습 판단

A 커밋은 명령 카탈로그·문제은행·공식 문서 registry를 추가했으며 조건 추출 학습 데이터나
조건 JSON schema를 바꾸지 않았다. 새 `template_id`·`chunk_id`는 런타임 데이터 연결 키이고
기존 QLoRA 모델의 학습 출력이 아니다. 따라서 이번 변경에는 **문서 재생성 및 Chroma 재색인**이
필요하며 **QLoRA 재학습은 필요하지 않다**.

이전 `feat/sllm`의 긴 입력·추가 조건 필드에 대한 실제 모델 평가는 별도 문제다.
`docs/fourth-project-sllm.md`에 기록된 모델 평가 미완료 상태를 이번 색인 검증으로 해소했다고
주장하지 않는다. 검수된 새 조건 추출 학습·평가 데이터도 A의 명령어 카탈로그와 구분해야 한다.
