# Dynamic Mini Challenge API 계약

## 목적과 경계

미니 챌린지는 방금 완료된 Q&A의 `ChatResponse.answer`와 실제 인용된
`ChatResponse.citations`만으로 만든 최대 3개의 객관식 문제다. Retriever, Chroma,
RAG를 다시 호출하지 않으며 Quiz 생성 실패·취소는 이미 표시한 Q&A 답변에 영향을 주지
않는다.

Q&A 웹 프로세스와 Quiz Celery worker는 각각 Qwen 인스턴스를 보유한다. Quiz worker는
`QuizGenerator.generate_from_chat_response(response, max_questions=3)`를 실행하고,
Redis에 task 상태와 결과를 보관한다. Quiz·제출 이력은 DB에 저장하지 않으며 오답노트로
명시적으로 저장한 항목만 기존 DB 흐름을 사용한다.

## 세션 및 정답 보호

- 생성 시작은 browser session의 **가장 최신** 서버 생성 `ChatResponse`만 사용한다.
- `status == "answered"` 이고 citation이 있을 때만 worker task를 등록한다.
- task ID와 해당 Q&A `request_id`, 취소 상태는 세션에 보관한다.
- 생성 완료 전 또는 취소 후에는 정답·해설·인용문을 응답하지 않는다.
- 완료 조회는 문제와 선택지(`id`, `text`)만 전달한다. `correct_choice_id`, `explanation`,
  `supporting_quotes`는 세션의 원본 `QuizResponse`에만 둔다.
- 답안 제출 뒤에만 정답 여부, 해설과 공식 출처 카드를 반환한다.

## API

모든 POST 요청은 `Content-Type: application/json`, session cookie, Django CSRF token을
포함해야 한다.

### 생성 시작

`POST /api/qa/mini-challenge`

```json
{"max_questions": 3}
```

성공 시 `202 Accepted`:

```json
{"task_id": "2d345026-2d80-42e5-ae7b-2374d30a561a", "status": "pending"}
```

근거가 부족하면 worker를 만들지 않고 다음을 반환한다.

```json
{"status": "insufficient_content", "quiz": {"status": "insufficient_content", "questions": []}}
```

최신 Q&A가 없으면 `404 qa_response_not_found`, 이미 생성 중이면 `409
generation_in_progress`, Redis/Celery 등록 실패면 `503 queue_unavailable`이다.

### 상태 조회

`GET /api/qa/mini-challenge/jobs/<task_id>`

상태는 `pending`, `running`, `available`, `insufficient_content`,
`generation_failed`, `cancelled` 중 하나다. `pending`·`running`은 `202`이고 나머지는
`200`이다. 다른 세션의 task나 이전 Q&A의 task는 `404 job_not_found`다.

`available`의 예시는 다음과 같다. 정답과 해설은 포함하지 않는다.

```json
{
  "task_id": "2d345026-2d80-42e5-ae7b-2374d30a561a",
  "status": "available",
  "quiz_id": "f13a9c1e-77be-4e9b-9cfe-b4f3406c0e31",
  "quiz": {
    "status": "available",
    "questions": [{
      "question_id": "generated_001",
      "question": "Raspberry Pi OS에서 SSH의 기본 상태는 무엇인가요?",
      "choices": [{"id": "A", "text": "기본적으로 비활성화"}]
    }]
  }
}
```

### 취소

`POST /api/qa/mini-challenge/jobs/<task_id>/cancel`

세션 소유 task만 취소할 수 있다. 서버는 세션 상태를 먼저 `cancelled`로 확정한 다음
`Celery AsyncResult.revoke(terminate=True, signal="SIGTERM")`를 요청한다. 이 순서 때문에
취소와 완료가 경합해도 늦게 도착한 Quiz 결과는 세션·프론트에 반영되지 않는다. worker는
종료된 프로세스를 단일 prefork pool에서 다시 띄우고 Qwen을 다시 로드한다.

성공 응답은 `202 Accepted`의 `{"task_id": "...", "status": "cancelled"}`다.

### 답안 제출

`POST /api/qa/mini-challenge/quizzes/<quiz_id>/submit`

```json
{"question_id": "generated_001", "selected_choice_id": "A"}
```

응답에는 `is_correct`, `correct_choice_id`, `explanation`, `supporting_quotes`, 공식
`evidence` 카드가 포함된다. 한 문항은 세션마다 한 번만 제출할 수 있다. 로그인 사용자의
오답 응답에는 기존 오답노트 저장 URL도 포함된다.

## 프론트 동작

Q&A가 `answered`이고 citation이 있으면 답변을 즉시 렌더링한 뒤 생성 API를 호출하고,
1초 주기로 상태를 조회한다. 3초 동안 진행 중이면 `cancelAPI()`가 호출하는 취소 버튼을
보인다. 취소하면 polling을 멈추고 재시도 버튼을 표시한다. `insufficient_content`는 재시도
없이 안내만 보이며, `generation_failed`·queue 오류는 재시도할 수 있다.

## Compose 운영

`docker compose up --build`는 MySQL, Redis, Django `web`, GPU `quiz-worker`를 함께
실행한다. 실제 GPU 취소에는 Docker와 NVIDIA Container Toolkit이 필요하며, Q&A web과
worker가 각각 Qwen을 적재하므로 GPU 메모리 여유가 필요하다.
