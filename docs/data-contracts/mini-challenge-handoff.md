# Dynamic Mini Challenge MVP 백엔드 핸드오프

## 기능 목적

방금 제공한 Q&A 답변을 사용자가 이해했는지 확인하는 근거 기반 객관식 퀴즈를 반환한다. 퀴즈는 새로운 검색 결과가 아니라, 이미 완성된 `ChatResponse.answer`와 answer에 실제로 인용된 `ChatResponse.citations`만 사용한다.

- Retriever, Chroma, embedding, RAG를 다시 호출하지 않는다.
- Quiz 생성 실패는 기존 Q&A 실패가 아니다.
- 퀴즈는 기본적으로 transient 데이터이며, 사용자가 오답노트 저장을 선택한 항목만 persistence 대상으로 본다.

## 백엔드 호출 진입점

백엔드는 Q&A 완료 후 이미 생성된 `ChatResponse`를 아래 메서드에 전달한다.

```python
from src.services.quiz_generator import QuizGenerator

quiz_response = quiz_generator.generate_from_chat_response(
    chat_response,
    max_questions=3,
)
```

실제 메서드 서명은 다음과 같다.

```python
QuizGenerator.generate_from_chat_response(
    response: ChatResponse,
    *,
    max_questions: int = 3,
) -> QuizResponse
```

`QuizGenerator`는 생성기 주입 방식이다. 실제 Qwen 연결 시에는 이미 로드한 `HuggingFaceAnswerGenerator`를 `HuggingFaceQuizTextGenerator`로 감싸 주입한다. 별도 Qwen 인스턴스를 만들지 않는다.

## 처리 흐름

```text
ChatResponse
→ chat_response_to_quiz_request()
→ QuizGenerationRequest
→ grounded prompt 생성
→ 기존 Qwen structured generation 1회
→ draft JSON parser
→ quote 후보 ID를 원문 supporting_quotes로 변환
→ 구조/evidence validation
→ duplicate 제거/finalize
→ QuizResponse
```

adapter는 `status == "answered"`이고 citation이 있는 경우에만 동작한다. answer 안의 `[C1]` 같은 실제 citation ID에 해당하는 citation만 `QuizEvidence`로 변환한다. citation의 `quote`는 evidence 본문으로 사용한다.

quote 후보는 evidence 원문에서 서버가 추출한다. 모델은 후보 ID만 선택하고, 서버가 대응되는 원문을 최종 `supporting_quotes`에 넣는다. 따라서 외부 `QuizResponse`에는 내부 `supporting_quote_id`가 노출되지 않는다.

## 계약

### 입력: `ChatResponse`

백엔드가 QuizGenerator에 전달하는 입력이다. Quiz에 필요한 핵심 필드는 `request_id`, `status`, `answer`, `citations`이며, `ChatResponse` 전체 계약상 아래 필드도 존재한다.

| 필드 | 타입 |
| --- | --- |
| `schema_version` | string (`"1.2.0"`) |
| `request_id` | non-empty string |
| `status` | `answered` 등 Q&A 상태 |
| `language` | language code string |
| `answer` | non-empty string, answered이면 inline citation 필요 |
| `conditions` | object 또는 `null` |
| `citations` | `ChatCitation[]` |
| `products` | array |
| `media` | array |
| `clarification_questions` | string array |
| `warnings` | string array |

`ChatCitation`에서 Quiz에 재사용되는 필드는 `citation_id`, `document_id`, `chunk_id`, `quote`다. citation ID는 `C1`, `C2` 형식이다.

### 내부 변환: `QuizGenerationRequest`

이 계약은 adapter가 만든 내부 입력이다. API 소비자가 직접 만들 필요는 없다.

| 필드 | 타입 |
| --- | --- |
| `request_id` | string |
| `answer` | string |
| `evidence` | `QuizEvidence[]` (`citation_id`, `document_id`, `chunk_id`, `content`) |
| `quote_candidates` | `QuizQuoteCandidate[]` |
| `max_questions` | integer, 1~3 |

### 출력: `QuizResponse`

| 필드 | 타입 |
| --- | --- |
| `status` | `available` / `insufficient_content` / `generation_failed` |
| `questions` | `QuizQuestion[]` |

각 `QuizQuestion`은 `question_id`, `question`, `choices`, `correct_choice_id`, `explanation`, `evidence_ids`, `supporting_quotes`를 가진다. `choices`는 `id` (`A`~`D`)와 `text`를 가진다.

## status 처리

| status | 의미 | 백엔드 처리 |
| --- | --- | --- |
| `available` | 검증된 문항이 1개 이상 있음 | frontend에 quiz 전달 |
| `insufficient_content` | citation/quote 후보가 없거나 유효 문항이 없음 | 정상 결과로 취급. quiz UI를 숨기거나 “생성 가능한 문제가 없음” 표시 |
| `generation_failed` | Qwen 출력이 draft JSON 계약을 통과하지 못함 | quiz 오류로 로깅 가능. 기존 Q&A는 그대로 반환 |

## 분리 frontend용 JSON API 계약

이 절은 Django template render가 아니라 별도 frontend가 Quiz를 호출할 때 적용한다. endpoint 구현 전 backend와 frontend는 이 경로와 payload를 함께 확정해야 한다.

### Quiz 생성 요청

`POST /api/qa/mini-challenge`

Q&A의 원문이나 citation을 client가 다시 보내지 않는다. backend는 현재 browser session에 저장된 최신 final `ChatResponse`만 읽어 `QuizGenerator.generate_from_chat_response()`에 전달한다. 이렇게 해야 client가 다른 답변 또는 임의 evidence로 Quiz를 만들 수 없다.

```json
{
  "max_questions": 3
}
```

| 필드 | 필수 | 규칙 |
| --- | --- | --- |
| `max_questions` | 아니오 | 정수 `1`~`3`, 생략하면 `3` |

요청은 `Content-Type: application/json` 및 session cookie를 포함해야 하며, cookie 인증을 쓰는 Django 배포에서는 CSRF token도 포함해야 한다.

### 성공 응답

HTTP `200 OK`에서 반환한다. `quiz_id`는 이후 답안 제출·오답노트 저장에 쓰는 서버 발급 UUID이며, `quiz` 값은 [quiz-response.schema.json](../schemas/quiz-response.schema.json) 전체와 일치한다.

```json
{
  "quiz_id": "2d345026-2d80-42e5-ae7b-2374d30a561a",
  "quiz": {
    "status": "insufficient_content",
    "questions": []
  }
}
```

`quiz.status`는 HTTP 실패가 아니라 Quiz 생성 결과다. frontend는 아래처럼 처리한다.

| `quiz.status` | frontend 처리 |
| --- | --- |
| `available` | `questions`를 표시하고 `quiz_id`로 답안을 제출한다. |
| `insufficient_content` | 오류 토스트나 자동 재시도 없이 “현재 답변으로는 문제를 만들 수 없음”을 표시한다. |
| `generation_failed` | Q&A 본문을 유지하고 Quiz 영역에 재시도 안내를 표시한다. |

### 오류 응답

`generation_failed`는 아래 오류 응답이 아니라 HTTP 200의 정상 Quiz 상태다. HTTP 오류는 API 호출 자체를 완료할 수 없었을 때만 사용한다.

```json
{
  "error": {
    "code": "qa_response_not_found",
    "message": "퀴즈를 만들 Q&A 결과가 없습니다. 먼저 질문을 제출해 주세요."
  }
}
```

| HTTP 상태 | `error.code` | 의미 및 frontend 처리 |
| --- | --- | --- |
| `400` | `invalid_request` | JSON 형식, `max_questions` 범위 또는 Content-Type이 잘못됨. 입력을 수정해 다시 요청한다. |
| `403` | `csrf_failed` | CSRF token 또는 session 검증 실패. 로그인/세션 상태를 갱신한 뒤 다시 요청한다. |
| `404` | `qa_response_not_found` | 현재 session에 Quiz 대상 Q&A가 없음 또는 만료됨. Q&A 화면으로 이동한다. |
| `500` | `internal_error` | 예상하지 못한 backend 오류. Q&A는 유지하고 잠시 뒤 재시도 안내를 표시한다. |

## 요청/응답 예시

### 1. ChatResponse → QuizResponse 전체 예시

입력 `ChatResponse`:

```json
{
  "schema_version": "1.2.0",
  "request_id": "qa-20260912-001",
  "status": "answered",
  "language": "ko",
  "answer": "Raspberry Pi OS에서는 SSH가 기본적으로 비활성화되어 있습니다. [C1]",
  "conditions": null,
  "citations": [
    {
      "citation_id": "C1",
      "document_id": "rpi-doc-remote-access-ssh",
      "chunk_id": "rpi-doc-remote-access-ssh-001",
      "title": "Remote access",
      "publisher": "Raspberry Pi Ltd",
      "section": "SSH",
      "source_url": "https://www.raspberrypi.com/documentation/computers/remote-access.html",
      "source_anchor": null,
      "document_version": null,
      "published_at": null,
      "updated_at": null,
      "collected_at": "2026-09-12",
      "license": "CC BY-SA 4.0",
      "quote": "SSH is disabled by default on Raspberry Pi OS."
    }
  ],
  "products": [],
  "media": [],
  "clarification_questions": [],
  "warnings": []
}
```

호출 결과 `QuizResponse`:

```json
{
  "status": "available",
  "questions": [
    {
      "question_id": "generated_001",
      "question": "Raspberry Pi OS에서 SSH의 기본 상태는 무엇인가요?",
      "choices": [
        {"id": "A", "text": "기본적으로 비활성화"},
        {"id": "B", "text": "기본적으로 활성화"},
        {"id": "C", "text": "설치 중에만 활성화"},
        {"id": "D", "text": "네트워크 연결 시에만 활성화"}
      ],
      "correct_choice_id": "A",
      "explanation": "근거는 Raspberry Pi OS에서 SSH가 기본적으로 비활성화되어 있다고 설명합니다.",
      "evidence_ids": ["C1"],
      "supporting_quotes": ["SSH is disabled by default on Raspberry Pi OS."]
    }
  ]
}
```

### 2. `available` 응답

```json
{
  "status": "available",
  "questions": [
    {
      "question_id": "generated_001",
      "question": "Raspberry Pi OS에서 SSH의 기본 상태는 무엇인가요?",
      "choices": [
        {"id": "A", "text": "기본적으로 비활성화"},
        {"id": "B", "text": "기본적으로 활성화"},
        {"id": "C", "text": "처음 부팅할 때만 활성화"},
        {"id": "D", "text": "네트워크 연결 시에만 활성화"}
      ],
      "correct_choice_id": "A",
      "explanation": "근거는 Raspberry Pi OS에서 SSH가 기본적으로 비활성화되어 있다고 설명합니다.",
      "evidence_ids": ["C1"],
      "supporting_quotes": ["SSH is disabled by default on Raspberry Pi OS."]
    }
  ]
}
```

### 3. `insufficient_content` 응답

```json
{
  "status": "insufficient_content",
  "questions": []
}
```

### 4. `generation_failed` 응답

```json
{
  "status": "generation_failed",
  "questions": []
}
```

## 담당 범위

### QuizGenerator가 이미 담당하는 범위

- `ChatResponse` citation을 `QuizGenerationRequest`로 변환
- grounded prompt와 quote 후보 생성
- Qwen structured generation 호출
- draft JSON parser
- 선택지·정답·evidence·quote 원문 검증
- 유효 문항만 남기고 중복 제거
- `QuizResponse` 반환

### 백엔드 담당 범위

- API endpoint 설계와 요청 인증
- session/user와 Q&A `ChatResponse` 연결
- Q&A 완료 후 `generate_from_chat_response()` 호출
- `QuizResponse`를 frontend에 전달
- 사용자가 선택한 오답노트 항목만 persistence

## 통합 원칙과 운영 주의사항

- Quiz 생성을 위해 새 RAG/Retriever를 호출하지 않는다.
- 기존 Q&A의 최종 `ChatResponse`를 그대로 사용한다.
- 모든 생성 Quiz를 DB에 저장하지 않는다.
- Quiz는 transient 데이터이며, 사용자가 오답노트 저장을 선택한 항목만 persistence 대상으로 본다.
- Quiz 생성 실패가 기존 Q&A 응답을 실패시키면 안 된다.

실제 Qwen 다문항 평가에서 `max_questions=3`의 Quiz 생성 시간은 평균 약 28초였다. 실제 Q&A부터 Quiz까지 이어지는 E2E 5건의 전체 평균 시간은 약 44초였다. 이는 기능 오류는 아니지만 동기 HTTP 응답에서 UX 문제가 될 수 있다.

### 권장 API/UX 처리

- 권장: Q&A 답변을 먼저 반환하고, Quiz는 별도 비동기 작업으로 생성한 뒤 quiz 상태 또는 결과를 조회·전달한다.
- frontend는 Quiz 생성 중에는 loading 상태를 표시하고, 완료 전에는 Q&A 본문을 정상적으로 읽을 수 있어야 한다.
- backend/frontend는 Quiz 전용 timeout, 취소 가능 여부, polling 또는 push 방식의 결과 전달을 협의한다.
- 동기 방식을 선택하더라도 Q&A와 Quiz 실패를 분리한다. Quiz timeout 또는 `generation_failed`가 발생해도 Q&A 본문은 그대로 반환한다.
- `insufficient_content`는 오류가 아니므로 재시도 대상으로 취급하지 않고 Quiz UI만 숨긴다.
