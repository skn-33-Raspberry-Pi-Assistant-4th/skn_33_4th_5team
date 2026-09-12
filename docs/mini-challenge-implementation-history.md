# Dynamic Mini Challenge 구현·검증 기록

> 기준: `feat/mini_challenge`의 현재 추적 코드와 Git 이력(2026-09-12)을 바탕으로 작성했다. 이 문서는 RAG 검색 품질이 아니라, 이미 완성된 Q&A의 final citation을 재사용하는 Quiz 파이프라인을 대상으로 한다.

## 1. 기능 도입 배경

초기 기획은 Q&A topic별 사전 문제은행에서 3문항을 골라 제공하는 방식이었다. 그러나 같은 주제라도 사용자의 질문 표현, 검색된 chunk, 최종 답변은 달라질 수 있다. 따라서 사전 문제은행의 문항이 사용자가 방금 읽은 답변에 없는 내용을 물을 위험이 있었다.

이를 해결하기 위해 Mini Challenge는 새 RAG를 만들지 않고, 최종 Q&A가 실제로 사용한 `ChatResponse.answer`와 inline citation에 대응되는 `ChatResponse.citations`만 재사용하도록 설계했다. 목표는 “주제 일반 지식”이 아닌 “방금 답변한 내용의 이해 확인”이다.

제외 범위는 Retriever/Chroma/embedding/corpus 변경, LoRA·sLLM 재학습, DB·랭킹·배지, Django API·완성형 UI다.

## 2. 초기 설계

초기 MVP 경계는 [mini-challenge-dynamic-mvp.md](mini-challenge-dynamic-mvp.md)에 기록했다.

- 입력: `ChatResponse.answer + ChatResponse.citations`
- evidence 본문: final citation의 `ChatCitation.quote`
- Retriever 재호출 금지
- 최대 3문항, 근거가 부족하면 1~2문항 또는 `insufficient_content`
- 문항마다 evidence ID와 supporting quote를 반환
- Q&A 실패와 Quiz 실패를 분리

초기에는 LLM이 `supporting_quotes` 원문 자체를 JSON에 직접 출력하고, 애플리케이션이 길이·포함 여부를 검증하는 형태였다. 이후 실제 모델 평가에서 이 인용문 생성이 가장 불안정한 지점임을 확인했고, 최종 구조에서는 모델이 원문 대신 후보 ID를 선택하도록 변경했다.

## 3. 전체 아키텍처

```text
사용자 질문
  → 기존 RAG / Q&A
  → ChatResponse(answer + final citations)
  → chat_response_to_quiz_request()
  → QuizGenerationRequest(evidence + quote_candidates)
  → build_quiz_generation_messages()
  → HuggingFaceAnswerGenerator.generate_structured()
  → parse_quiz_draft_response()
  → quote 후보 ID를 실제 원문으로 materialize
  → 구조 / evidence / quote 검증
  → finalize_questions()
  → QuizResponse
```

핵심 연결은 `src/services/quiz_generator.py`의 `QuizGenerator.generate_from_chat_response()`다. adapter는 answer 안의 `[C1]` 같은 citation ID를 `src.lang.extract_citation_ids()`로 확인한 뒤, 실제로 답변에 인용된 citation만 evidence로 전환한다. 검색 결과 전체나 답변에 쓰이지 않은 citation은 Quiz에 전달하지 않는다.

## 4. Commit별 구현 과정

### [Commit 0 — `14f6db4`] MVP 경계 문서화

**목적:** 구현 전에 동적 생성 범위와 제외 범위를 고정했다.

**변경 파일:**

- `docs/mini-challenge-dynamic-mvp.md`

**왜 이렇게 설계했는지:** Quiz가 기존 RAG를 침범하지 않고, UI와 무관한 service 계층으로 Django에서도 재사용되도록 범위를 제한했다.

**다음 단계와의 연결:** Q&A final citation을 Quiz evidence 입력으로 삼는 contract 작업의 기준이 됐다.

### [Commit 1 — `1d3b4e6`] Quiz evidence 입력 contract

**목적:** final citation을 Quiz가 안전하게 받을 최소 데이터 계약을 만들었다.

**변경 파일:**

- `src/contracts/models.py`
- `src/contracts/__init__.py`
- `tests/test_quiz_contracts.py`

**주요 클래스:** `QuizEvidence`

```python
QuizEvidence(citation_id, document_id, chunk_id, content)
```

`citation_id`는 `C1` 형식, 나머지 문자열은 비어 있지 않아야 한다. `content`는 이후 `ChatCitation.quote`를 보존한다.

**테스트:** 정상 생성, blank content, 잘못된 citation ID, 미정의 필드 거부를 계약 테스트로 추가했다.

### [Commit 2 — `84fedaa`] 생성 요청·응답 contract

**목적:** Quiz 서비스의 입출력 API를 UI와 독립적으로 고정했다.

**변경 파일:**

- `src/contracts/models.py`
- `src/contracts/__init__.py`
- `tests/test_quiz_contracts.py`

**주요 클래스:** `QuizGenerationRequest`, `QuizChoice`, `QuizQuestion`, `QuizResponse`

`QuizGenerationRequest.max_questions`는 1~3으로 제한했다. `QuizResponse.status`는 `available`, `insufficient_content`, `generation_failed` 세 상태이며, Pydantic model validator가 `available`에는 문항이 있고 그 외 상태에는 문항이 없도록 강제한다.

**다음 단계와의 연결:** adapter와 parser, backend API가 동일한 계약을 공유하게 됐다.

### [Commit 3 — `e3f77ed`] final Q&A citation adapter

**목적:** Retriever를 다시 부르지 않고 final Q&A를 Quiz 입력으로 바꿨다.

**변경 파일:**

- `src/services/quiz_adapters.py`
- `tests/test_quiz_adapters.py`

**주요 함수:** `chat_response_to_quiz_request(response, max_questions=3)`

`answered`가 아니거나 citation이 없으면 `None`을 반환한다. 그렇지 않으면 `response.answer`에서 실제 citation ID를 추출해, 해당 citation의 `citation_id`, `document_id`, `chunk_id`, `quote`를 `QuizEvidence`로 보존한다.

**왜 이렇게 설계했는지:** “검색되었지만 답변에는 쓰이지 않은 문서”를 문제 근거로 쓰지 않기 위해서다.

**테스트:** citation 순서와 ID·chunk ID 보존, `quote → content` 복사, Retriever 미호출을 확인했다.

### [Commit 4~7 — `7596174`, `0cb6759`, `269b788`, 이후 보완 commit] deterministic validation 계층

**목적:** LLM이 만든 JSON을 그대로 서비스에 노출하지 않고, 코드로 검증 가능한 오류를 제거했다.

**변경 파일:**

- `src/services/quiz_validation.py`
- `tests/test_quiz_validation.py`

**주요 함수와 규칙:**

| 함수 | 책임 |
| --- | --- |
| `validate_question_structure()` | 정확히 4개 선택지, A/B/C/D 한 번씩, 빈 값·중복 선택지 금지, 정답 ID·문제·해설 확인 |
| `validate_question_evidence()` | evidence ID 정확히 1개, allowlist 내 ID, supporting quote 정확히 1개, 15~240자, 원문 포함 확인 |
| `supporting_quote_matches()` | 공백 정규화와 한 번의 HTML unescape 후 evidence 원문 포함 여부 확인 |
| `finalize_questions()` | 빈 결과면 `insufficient_content`, 중복 제거 후 최대 `max_questions` 반환 |

중복은 정규화한 문제 문구, 문제+정답 문구, 동일 evidence+supporting quote 조합으로 판정한다.

**왜 이렇게 설계했는지:** “LLM이 JSON을 만들었다”와 “서비스에 안전한 근거 기반 문항이다”를 분리하기 위해서다. allowlist와 quote 원문 검증은 통과율을 올리기 위해 완화하지 않았다.

### [Commit 8 — `729e33c`] grounded prompt

**목적:** 모델에 answer·evidence·허용 citation을 명시하고 JSON-only 출력을 요구했다.

**변경 파일:**

- `src/lang/quiz_prompts.py`
- `src/lang/__init__.py`
- `tests/test_quiz_prompts.py`

**주요 함수:** `build_quiz_generation_messages(request)`

answer와 evidence는 XML 형태로 렌더링하되 `html.escape()` 처리한다. 따라서 evidence 내부의 텍스트가 prompt 지시처럼 동작하지 않도록 한다. prompt는 answer와 evidence의 교집합만 출제, evidence ID 하나, 4지선다, 단일 정답, JSON-only를 요구한다.

### [Commit 9 — `3b0468f`] strict JSON parser

**목적:** 모델 출력 복구가 아닌 명확한 실패 경계를 만들었다.

**변경 파일:**

- `src/services/quiz_parser.py`
- `tests/test_quiz_parser.py`

**주요 함수:** `parse_quiz_response()`, 최종 구조에서는 `parse_quiz_draft_response()`

순수 JSON과 전체 Markdown code fence만 허용한다. 자연어 앞뒤 문장, 잘린 JSON, trailing comma 자동 보정, regex 추출, scalar를 배열로 바꾸는 복구는 의도적으로 하지 않는다. 실패하면 `QuizOutputError`이며 서비스는 `generation_failed`를 반환한다.

### [Commit 10~11 — `6428f01`, `ddb04d1`] framework-independent QuizGenerator와 Q&A 진입점

**목적:** Streamlit/Django에 묶이지 않은 orchestration 계층을 만들었다.

**변경 파일:**

- `src/services/quiz_generator.py`
- `tests/test_quiz_generator.py`

**주요 클래스와 함수:**

- `QuizTextGenerator(Protocol)`: messages를 받아 raw text 하나를 반환하는 모델 경계
- `QuizGenerator.generate(request)`: prompt → 1회 모델 호출 → parser → validation → finalizer
- `QuizGenerator.generate_from_chat_response(response, max_questions=3)`: adapter를 재사용하는 편의 진입점

`answered`가 아니거나 citation이 없으면 모델 호출 없이 `insufficient_content`를 즉시 반환한다. parser 실패만 `generation_failed`로 구분하고, parser 성공 후 문항들이 validation에서 모두 탈락하면 `insufficient_content`가 된다.

### [Commit 12A — `c3bec40`] 기존 Qwen structured generation 경로

**목적:** Quiz를 위해 Qwen을 새로 로드하거나 Q&A generator의 검증 흐름을 바꾸지 않고 raw structured generation을 열었다.

**변경 파일:**

- `src/rag_to_llm/answer_generator.py`
- `tests/test_huggingface_answer_generator.py`

**주요 함수:** `HuggingFaceAnswerGenerator.generate_structured(messages, max_new_tokens)`

이 함수는 기존 `_load_model()`과 `_generate_text()`를 재사용하고 `do_sample=False`로 한 번만 생성한다. Q&A 전용 citation normalizer, citation validator, repair/retry는 호출하지 않는다. Quiz JSON parser와 evidence validator 역시 이 계층에 넣지 않았다.

**왜 이렇게 설계했는지:** 하나의 이미 로드된 Qwen runtime을 Q&A와 Quiz가 공유하되, Q&A의 기존 `generate()` 동작은 그대로 보존하기 위해서다.

### [Commit 13 — `e4a9855`] 실제 Qwen smoke test

**목적:** GPU에서 `answer + evidence → Qwen → QuizResponse` 경로를 짧은 고정 fixture로 검증했다.

**변경 파일:**

- `src/rag_to_llm/quiz_text_generator.py`
- `src/rag_to_llm/__init__.py`
- `tests/test_huggingface_quiz_text_generator.py`
- `tests/test_quiz_qwen_smoke.py`
- `docs/quiz-qwen-smoke-test.md`

**주요 클래스:** `HuggingFaceQuizTextGenerator`

주입받은 `HuggingFaceAnswerGenerator.generate_structured()`만 호출하는 thin adapter다. prompt·parser·validator 책임은 `QuizGenerator`에 유지한다.

기록된 RunPod A40 / `Qwen/Qwen3-4B-Instruct-2507` 4-bit smoke 결과는 parser 10/10, allowlist 위반 0, quote 매칭 10/10, 유효 문항 10/10이었다. 첫 로딩 포함 22.8초, 이후 9건 평균 10.2초였다.

### [Commit 14~15 — `6432af5`, `261c96f`] 평가셋과 검증 문서

**목적:** 단순 unit test를 넘어 실제 Qwen 출력의 실패 유형을 기록했다.

**변경 파일:**

- `eval/quiz_generation_cases.v1.jsonl`
- `docs/validation/mini-challenge-mvp.md`

평가셋은 OS 설치, SSH/원격 접속, 카메라, 근거 부족 fixture로 구성됐다. fixed `answer + evidence`를 사용해 RAG 재호출 없이 Quiz 계층만 평가했다. `docs/validation/mini-challenge-mvp.md`는 개선 전·후 수치를 구분해 기록한다.

### [후속 보완 — `e4ad88c`, `4220f0d`, `34cfbbe`, `c599755`] 실제 모델 실패를 반영한 구조 개선

이 단계는 parser/validator를 느슨하게 하는 대신, 원인이 확인된 generation budget과 quote 생성 책임을 고쳤다.

**변경 파일:**

- `src/rag_to_llm/answer_generator.py`
- `src/rag_to_llm/quiz_text_generator.py`
- `src/lang/quiz_prompts.py`
- `src/contracts/models.py`
- `src/contracts/__init__.py`
- `src/services/quiz_adapters.py`
- `src/services/quiz_generator.py`
- `src/services/quiz_parser.py`
- `src/services/quiz_quote_candidates.py`
- `eval/quiz_generation_cases.v1.jsonl`
- 관련 `tests/test_*.py`
- `docs/validation/mini-challenge-mvp.md`

세부 원인과 결과는 뒤의 “평가에서 발견한 문제”에 정리한다.

### [운영·핸드오프 문서 — `0146b7b`, `2127074`]

**변경 파일:**

- `docs/data-contracts/mini-challenge-handoff.md`

backend 호출 진입점, `ChatResponse`/`QuizResponse` 계약, status 처리, transient 데이터 원칙을 문서화했다. 다문항 Quiz 평균 약 28초, Q&A→Quiz E2E 5건 평균 약 44초라는 운영 지표를 반영해 Q&A 우선 응답·Quiz 비동기 생성·loading/timeout 정책 협의를 권장했다.

## 5. 핵심 클래스·함수 역할

| 경로 | 구성 요소 | 역할 |
| --- | --- | --- |
| `src/contracts/models.py` | `QuizEvidence` | final citation의 ID와 원문을 보존하는 입력 evidence |
| 동일 | `QuizGenerationRequest` | answer, evidence, quote 후보, 1~3 문항 상한 |
| 동일 | `QuizDraftResponse`, `QuizDraftQuestion` | LLM raw output 전용 내부 contract |
| 동일 | `QuizResponse`, `QuizQuestion` | 외부에 반환하는 최종 contract |
| `src/services/quiz_adapters.py` | `chat_response_to_quiz_request()` | final Q&A에서 실제 인용만 추출 |
| `src/services/quiz_quote_candidates.py` | `extract_quote_candidates()` | evidence 원문에서 15~240자 exact 문장/목록 후보 생성 |
| `src/lang/quiz_prompts.py` | `build_quiz_generation_messages()` | grounded system/user messages 조립 |
| `src/rag_to_llm/answer_generator.py` | `generate_structured()` | shared Qwen runtime으로 raw JSON 1회 생성 |
| `src/rag_to_llm/quiz_text_generator.py` | `HuggingFaceQuizTextGenerator` | Qwen generator를 `QuizTextGenerator` protocol로 연결 |
| `src/services/quiz_parser.py` | `parse_quiz_draft_response()` | strict JSON 및 draft schema parsing |
| `src/services/quiz_validation.py` | validation/finalizer 함수 | 구조·근거·인용·중복을 deterministic하게 검증 |
| `src/services/quiz_generator.py` | `QuizGenerator` | 전체 orchestration과 최종 status 결정 |

## 6. Validation과 grounding 전략

### 모델이 담당하는 일

- answer·evidence의 교집합에서 확인 가능한 핵심 사실을 선택
- 한국어 문제, A~D 선택지, 정답 ID, 해설 생성
- 허용된 `evidence_ids`와 `supporting_quote_id` 선택
- 근거가 부족하면 `insufficient_content` 선택

### deterministic code가 담당하는 일

- Pydantic schema·status/문항 수 계약 검증
- A/B/C/D 정확히 한 번, 4개 선택지, 공백·중복 선택지, 정답 존재 검증
- evidence ID 1개와 allowlist 검증
- quote 후보 ID가 evidence ID와 일치하는지 검증
- 후보 ID를 evidence의 실제 원문 substring으로 변환
- 15~240자 길이 및 source text 포함 여부 검증
- 중복 문항 제거·최대 수 제한·최종 status 결정

최종 구조의 핵심은 “인용문을 생성하지 않게 하는 것”이다. `QuizQuoteCandidate`는 `C1-Q1` 형식의 ID, evidence ID, exact content를 가진다. `extract_quote_candidates()`는 줄·문장 경계를 기준으로 후보를 만들고, LLM은 `supporting_quote_id`만 반환한다. `QuizGenerator._materialize_question()`이 이를 최종 `supporting_quotes` 원문으로 교체한다.

따라서 final `QuizResponse`의 quote는 모델의 의역 결과가 아니라 서버가 이미 evidence에서 뽑은 literal substring이다.

## 7. 실제 Qwen 연결과 모델 재사용

실제 경로는 다음과 같다.

```text
HuggingFaceAnswerGenerator (Q&A가 이미 사용)
  └─ HuggingFaceQuizTextGenerator
       └─ QuizGenerator
```

`HuggingFaceQuizTextGenerator`는 새 모델을 만들지 않는다. 주입된 answer generator의 `generate_structured()`를 호출하고 raw text만 돌려준다. `generate_structured()`도 기존 `_load_model()`과 `_generate_text()`를 재사용한다. 실제 E2E 실행에서는 Q&A 이후 Quiz의 model instance identity가 동일했고, Quiz 단계 Retriever 호출 수는 0으로 기록됐다.

Quiz 생성은 `do_sample=False`, 호출당 1회, Quiz retry 없음이다. 반면 기존 Q&A `generate()`의 citation validation/repair retry와 512 token 정책은 변경하지 않았다.

## 8. 평가에서 발견한 문제와 해결 과정

### 8.1 512 token JSON truncation

**증상 → 관찰:** initial 20-case 평가에서 JSON parser 통과는 5/20(25.0%)였다. positive 15건 중 13건의 raw output이 507~512 generated tokens에서 닫는 brace 이전에 끝났다.

**가설 → 실제 원인:** 3문항 JSON은 문제, 4개 선택지, 해설, evidence ID, supporting quote를 모두 포함하므로 `max_questions=3`과 structured `max_new_tokens=512` 조합에서 출력 공간이 부족했다.

**수정:** `HuggingFaceAnswerGenerator.generate_structured()`만 1~1024 tokens를 허용했다. 일반 Q&A `generate()`의 512 정책과 citation validation/retry는 변경하지 않았다. `HuggingFaceQuizTextGenerator`의 기본 structured 상한도 1024로 맞췄다.

**재평가:** JSON parser 20/20(100%)로 회복됐고 truncation은 재발하지 않았다. 문제의 원인이 parser의 엄격함이 아니었으므로 parser 자동 복구는 도입하지 않았다.

### 8.2 supporting quote 직접 생성 품질

**증상 → 관찰:** 1024-token 재평가에서는 quote 길이 초과 5건, 원문 불일치 1건이 남아 evidence 정확성이 10/16(62.5%), positive 유효 문항 제공률이 9/15(60.0%)였다.

**1차 원인 대응:** prompt에 “가장 짧은 충분한 원문 구절”, 15~240자, 문장부호·대소문자 보존, 배열 형식을 명시했다. 이후 quote 길이 위반은 2건으로 줄고 evidence 정확성은 10/13(76.9%), 제공률은 10/15(66.7%)가 됐지만, 모델이 목록 구두점·긴 원문 복사를 완전히 안정적으로 처리하지 못했다.

**최종 원인:** exact source substring 복사는 생성 과업으로 맡기기보다 deterministic selection 문제로 다루는 편이 안전했다.

**최종 수정:** `QuizQuoteCandidate`, `QuizDraftQuestion.supporting_quote_id`, `extract_quote_candidates()`, `_materialize_question()`을 도입했다. 모델은 허용 후보의 ID만 선택하고, 서버가 final quote를 채운다.

**수정하지 않은 영역:** parser 완화, quote 길이 검증 완화, evidence allowlist 완화, Retriever/RAG 변경, Q&A generate 변경은 하지 않았다.

**재평가:** final candidate-ID 평가에서 positive 15건은 draft parser·구조·evidence validation·quote match 모두 15/15, allowlist/quote 길이 위반 0, 평균 1.0문항, 평균 11.4초였다. evidence가 없는 5건은 LLM 호출 없이 `insufficient_content`가 됐다.

### 8.3 “3문항을 억지로 채우는가” 회귀 점검

별도 RunPod 다문항 regression에서는 `max_questions=3`, 4-bit Qwen, 1024 tokens, case당 1회 조건의 10개 multi-fact fixture를 사용했다. 작업 기록상 parser·구조·evidence 통과는 10/10, allowlist·quote mapping·quote match 실패는 0, 문항 수 분포는 1문항 1건/2문항 3건/3문항 6건, 평균 2.5문항이었다. 가장 긴 출력은 898 tokens였고, 중복 후보 1건은 finalizer가 제거했다. 평균 생성 시간은 약 28초였다.

이 상세 regression 수치는 현재 저장소에 machine-readable 결과 파일로 남아 있지 않고, 운영 가이드에는 평균 28초만 기록되어 있다. 발표에서 위 수치를 사용한다면 실행 로그 또는 평가 결과 JSON을 함께 보관하는 것이 바람직하다.

## 9. 시간 순서별 주요 결과

| 단계 | 조건 | JSON parser | evidence/quote | 유효 문항 제공 | 평균 시간 |
| --- | --- | ---: | ---: | ---: | ---: |
| Commit 13 smoke | 10 SSH/OS 고정 fixture | 10/10 | allowlist 0, quote 10/10 | 10/10 | 11.5초 |
| Initial evaluation | 20건, structured 512 | 5/20 (25.0%) | 미측정 수준 | 0/15 | 15.4초 |
| 1024 + 초기 quote 지시 | 20건 | 20/20 (100%) | 10/16 (62.5%) | 9/15 (60.0%) | 11.2초 |
| quote prompt 보완 | 20건 | 19/20 (95.0%) | 10/13 (76.9%) | 10/15 (66.7%) | 8.8초 |
| quote 후보 ID 최종 구조 | positive 15 + insufficient 5 | 15/15 모델 호출 | 15/15, allowlist 0, quote mismatch 0 | 15/15 (100%) | 11.4초 |
| 다문항 regression | multi-fact 10건, max 3 | 10/10 | 10/10, 실패 0 | 10/10 | 약 28초 |

초기 수치는 개선 효과를 설명하는 ablation 용도다. 최종 기능 성능을 말할 때는 quote 후보 ID 구조의 결과를 사용해야 한다.

## 10. 최종 구조와 status 의미

- `available`: parser와 모든 deterministic 검증을 통과한 문항이 1개 이상 있다.
- `insufficient_content`: final citation/quote 후보가 없거나, parser는 성공했지만 유효 문항이 남지 않았거나, 모델이 근거 부족을 반환했다. 정상 결과다.
- `generation_failed`: raw model output이 strict JSON/draft schema를 통과하지 못했다. Q&A 결과에는 영향을 주지 않는다.

이 상태 분리는 backend가 Quiz 실패를 Q&A 실패로 전파하지 않도록 한다.

## 11. 테스트 자산

| 파일 | 검증 대상 |
| --- | --- |
| `tests/test_quiz_contracts.py` | strict Pydantic contract와 status/max questions |
| `tests/test_quiz_adapters.py` | final citation 재사용, citation/chunk 보존, non-answered 경계 |
| `tests/test_quiz_validation.py` | 구조, allowlist, quote 매칭, 길이, 중복 finalizer |
| `tests/test_quiz_prompts.py` | grounded prompt, evidence/HTML escape, quote 후보 노출 |
| `tests/test_quiz_parser.py` | JSON-only, full fence, schema 실패 경계, draft parser |
| `tests/test_quiz_generator.py` | orchestration, 일부 invalid 제거, status 경계, ChatResponse 진입점 |
| `tests/test_huggingface_answer_generator.py` | Q&A와 structured generation 정책 분리 |
| `tests/test_huggingface_quiz_text_generator.py` | injected answer generator 재사용 |
| `tests/test_quiz_quote_candidates.py` | exact candidate 추출과 범위 제외 |
| `tests/test_quiz_qwen_smoke.py` | CUDA 환경의 실제 Qwen smoke fixture |
| `eval/quiz_generation_cases.v1.jsonl` | OS/SSH/카메라/근거 부족 고정 evaluation fixture |
| `docs/validation/mini-challenge-mvp.md` | 개선 전후 실제 Qwen 결과 기록 |

## 12. 현재 남은 한계

1. **오답 보기의 의미적 grounding은 사람 검수 대상이다.** 코드가 정답 evidence와 supporting quote를 강하게 제한하지만, 오답 선택지가 evidence 밖의 일반 지식을 암시하지 않는지까지 자동으로 증명하지는 않는다.
2. **latency가 짧지 않다.** 다문항 Quiz는 평균 약 28초, 실제 Q&A부터 Quiz까지의 E2E 5건 평균은 약 44초로 기록돼 있다.
3. **정량 평가 로그 보존이 필요하다.** `docs/validation/mini-challenge-mvp.md`에는 final 15 positive 결과가 있으나, 다문항 10건의 세부 결과는 별도 JSON artifact로 추적되지 않는다.
4. **GPU smoke test의 parser 검토가 필요하다.** 현재 `tests/test_quiz_qwen_smoke.py`는 raw output에 `parse_quiz_response()`를 직접 적용한다. 최종 runtime은 draft shape(`supporting_quote_id`)에 `parse_quiz_draft_response()`를 적용하므로, 다음 GPU 재실행 전 smoke test의 raw parser assertion을 최종 draft 계약에 맞추는 정합성 검토가 필요하다. 이는 서비스 로직의 parser를 바꾸라는 뜻이 아니라, smoke test가 최종 파이프라인과 같은 contract를 검사하도록 맞추라는 의미다.

## 13. 백엔드 핸드오프 주의사항

상세 계약은 [mini-challenge-handoff.md](data-contracts/mini-challenge-handoff.md)에 있다.

- backend는 Q&A가 만든 final `ChatResponse`를 그대로 `QuizGenerator.generate_from_chat_response()`에 전달한다.
- Quiz용 Retriever/RAG를 새로 호출하지 않는다.
- Quiz는 transient 데이터다. 모든 생성 결과를 저장하지 말고, 사용자가 오답노트 저장을 선택한 항목만 persistence 대상으로 둔다.
- `insufficient_content`는 정상 UI 상태다. Quiz 영역을 숨기거나 “생성 가능한 문제가 없음”으로 표시한다.
- `generation_failed`는 로깅 가능하지만 Q&A 응답을 실패시키지 않는다.
- Q&A를 먼저 반환하고 Quiz를 비동기 생성·조회하는 UX를 권장한다. loading, timeout, 취소·polling/push 방식을 backend/frontend가 합의해야 한다.
- Q&A와 Quiz는 같은 `HuggingFaceAnswerGenerator` instance를 주입해 모델을 재사용해야 한다.

## A. 발표용 1분 요약

“Mini Challenge는 주제별 문제은행 대신, 사용자가 방금 받은 Q&A 답변과 실제 final citation을 재사용해 객관식 문제를 만드는 기능입니다. Quiz가 새로 검색하면 답변과 다른 근거를 쓸 수 있기 때문에, answer 안에 실제로 인용된 citation만 adapter가 evidence로 변환했습니다. Qwen은 문제·선택지·해설과 quote 후보 ID만 생성하고, 애플리케이션은 JSON parsing, 선택지 구조, evidence allowlist, 원문 quote 매핑, 중복 제거를 deterministic하게 처리합니다. 실제 Qwen 평가에서 처음에는 512 token 상한 때문에 3문항 JSON이 잘렸지만, structured generation만 1024로 확장해 Q&A에는 영향을 주지 않았습니다. 이후 인용문을 모델이 직접 복사할 때 발생한 오류는 quote 후보 ID 선택 방식으로 바꿔 해결했습니다.”

## B. 포트폴리오용 구현 기여 요약

- Q&A final citation을 재사용하는 framework-independent Quiz service와 Pydantic contract 설계
- Retriever 재호출 없이 `ChatResponse → QuizGenerationRequest → QuizResponse`를 연결하는 adapter 구현
- JSON-only parser, 4지선다·단일정답·allowlist·원문 quote·중복 제거 검증 계층 구현
- 기존 Qwen runtime을 재사용하는 structured generation path 및 thin adapter 구현
- 실제 Qwen RunPod smoke/evaluation을 통해 512-token truncation과 quote 직접 생성 문제를 raw output 기준으로 분석
- parser/validator 완화 대신 quote 후보 ID를 서버에서 materialize하는 구조로 grounding 안정성 개선
- backend handoff contract, 상태 처리, 비동기 UX 주의사항 문서화

## C. 면접 답변 예시 (1~2분)

“사용자가 Q&A 답변을 읽은 직후 이해도를 확인한다는 목적 때문에, 사전 문제은행 대신 동적 Quiz 방식을 선택했습니다. 핵심은 새 RAG를 만들지 않는 것이었습니다. 기존 Q&A의 `ChatResponse`에서 answer에 실제로 표시된 citation ID만 추출하고, 그 citation의 quote·document ID·chunk ID를 `QuizEvidence`로 전달합니다. 그래서 Quiz가 답변에 없던 검색 결과를 근거로 쓰지 않습니다.

LLM에게는 문제와 선택지, 정답, 해설, evidence ID, quote 후보 ID만 생성하게 했고, JSON parsing과 4지선다 구조, allowlist, quote 원문 일치, 중복 제거는 코드가 담당하게 분리했습니다. 실제 Qwen으로 평가했을 때 3문항 JSON이 512 tokens에서 자주 잘리는 것을 raw output으로 확인해서, Q&A 경로는 건드리지 않고 structured generation만 1024 tokens로 확장했습니다. 이후 quote를 모델이 직접 복사하면서 길이와 문장부호 문제가 남자, 서버가 evidence에서 quote 후보를 추출하고 모델은 ID만 고르게 변경했습니다. 그 결과 final positive 평가에서 parser·structure·evidence·quote match가 모두 통과했고, Quiz는 Q&A 모델 인스턴스를 재사용하므로 별도 모델 로딩도 만들지 않았습니다.”
