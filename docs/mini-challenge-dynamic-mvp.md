# 동적 미니 챌린지 MVP

## 목적

미니 챌린지는 사용자가 방금 받은 Q&A 답변을 이해했는지 확인하는 기능이다.
최종 답변과 그 답변에 인용된 근거만 사용해 객관식 문제를 생성한다.

## 입력

```text
ChatResponse.answer
+ ChatResponse.citations[]
```

퀴즈 evidence는 최종 citation의 아래 필드로 만든다.

```text
citation_id
document_id
chunk_id
quote  -> evidence 본문
source_url
```

`ChatCitation.quote`를 evidence 본문으로 사용한다. 퀴즈 서비스는 문서를 다시
검색하거나 더 넓은 검색 결과를 사용하면 안 된다.

## 출력

서비스는 1~3개의 객관식 문제를 담은 구조화 JSON을 반환한다.

```text
available
  - 검증된 문제 1~3개 반환

insufficient_content
  - 답변 또는 근거만으로 문제를 만들 수 없을 때 빈 문제 목록 반환

generation_failed
  - 모델 출력을 안전하게 파싱 또는 검증할 수 없을 때 빈 문제 목록 반환
```

서비스는 3개보다 적은 문제를 반환할 수 있다. 3개를 채우기 위해 무관하거나
중복된 문제를 추가하면 안 된다.

## 범위

포함:

- UI 프레임워크에 의존하지 않는 QuizGenerator 서비스
- 퀴즈 프롬프트, 구조화 JSON parser, Pydantic 계약
- 생성 문항의 결정적 검증
- 단위 테스트와 대표 평가 사례

제외:

- 새 RAG 파이프라인 또는 Retriever 호출
- Chroma, Vector DB, embedding, corpus, manifest 변경
- sLLM/LoRA 학습 또는 재학습
- Django API 구현, DB 저장, 점수 누적, 랭킹, 배지, 완성형 프론트 UI

퀴즈 생성은 원래 Q&A 응답의 결과나 제공 여부에 영향을 주면 안 된다. 퀴즈 생성에
실패하면 Q&A와 독립적으로 빈 퀴즈 결과를 반환한다.

## 필수 검증

모든 검증을 통과한 문제만 반환한다.

1. JSON을 파싱할 수 있고 `QuizResponse` 스키마를 만족한다.
2. 응답에는 1~3개의 문제만 포함된다.
3. 모든 문제는 `A`, `B`, `C`, `D` ID를 각각 한 번씩 가진 4개의 선택지를 포함한다.
4. `correct_choice_id`는 반환된 선택지 중 하나와 일치한다.
5. 모든 문제는 입력에서 허용된 evidence ID를 하나 이상 참조한다.
6. 생성된 evidence ID는 입력 citation allowlist 밖에 있으면 안 된다.
7. 모든 문제는 약속한 공백 정규화 후 참조 evidence 본문에 실제 존재하는
   supporting quote를 반환한다.
8. 중복 문제는 제거하며, 유효한 문제가 남지 않으면
   `insufficient_content`.

## 운영 규칙

- Q&A 응답 상태가 `answered`이고 최종 citation이 하나 이상일 때만 퀴즈를 생성한다.
- `C1` 같은 요청 단위 citation ID를 evidence allowlist로 사용하고, 추적을 위해
  `chunk_id`와 `document_id`도 유지한다.
- MVP에서는 문제당 evidence 하나를 우선 사용해 검증 대상을 명확히 한다.
- 모델은 제공된 답변과 evidence만 사용해야 하며, 사전학습 지식이나 다른 출처의
  Raspberry Pi 정보를 추가하면 안 된다.
- 초기 MVP는 모델 생성 요청을 최대 1회만 사용하며, 결정적 검증 결과로 문제 표시 여부를
  결정한다.

## 완료 기준

팀원이 구현 코드를 읽지 않아도 이 문서만으로 QuizGenerator의 입력, 출력 상태, 제외 범위,
검증 규칙을 파악할 수 있다.
