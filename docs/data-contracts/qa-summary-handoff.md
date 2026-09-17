# Q&A 질문 제목·답변 요약 핸드오프

## 목적과 현재 상태

Q&A가 완료된 뒤 원문 질문을 아카이브 목록용 제목 한 줄로, 최종 답변을 QnA 토글과 아카이브 상세에서 공통으로 쓸 1~2문장으로 요약한다. 기존 답변의 검색·생성·저장 흐름과 분리된 Python 서비스가 구현되어 있다. **백엔드의 호출·저장·API 연결과 프론트의 화면 연결은 아직 구현되지 않았다.**

제목과 답변 요약은 서로 독립적인 결과다. 답변이 `answered`가 아니더라도 유효한 질문이면 제목을 생성한다. 답변 요약은 최종 `ChatResponse.status == "answered"`일 때만 생성한다. 요약 실패는 원래 `ChatResponse`를 변경하지 않는다.

## 백엔드 연결 계약

- 입력: 사용자 원문 질문 `str`, 생성이 끝난 `ChatResponse`, **그 답변에 사용한** `HuggingFaceAnswerGenerator` 인스턴스.
- 출력: 별도 `QaSummaryResult`. `ChatResponse`에 요약 필드를 추가하거나 객체를 수정하지 않는다.
- Qwen 설정이 아닌 `template` 등은 어댑터 팩토리가 `None`을 반환한다. 서비스는 가능한 필드에 `unsupported`를 반환한다.

```python
from src.rag_to_llm.qa_summary_text_generator import build_qa_summary_text_generator
from src.rag_to_llm import GenerationCancelled
from src.services.qa_summary import QaSummaryService
from threading import Event

# answer_generator: 현재 Q&A에 사용한 기존 생성기 인스턴스
# chat_response: 해당 질문의 최종 ChatResponse
text_generator = build_qa_summary_text_generator(answer_generator)
cancel_event = Event()  # Q&A 건마다 별도로 생성
try:
    summary = QaSummaryService(
        text_generator,
        cancel_requested=cancel_event.is_set,
    ).generate(question=original_question, response=chat_response)
    # 필요한 경우 summary.model_dump()로 API/저장용 dict를 얻는다.
except GenerationCancelled:
    # 요약 작업을 cancelled로 기록하고, 원래 ChatResponse는 그대로 유지
    ...
```

생성기를 새로 만들지 말고 기존 Q&A의 인스턴스를 전달해야 로드된 Qwen을 재사용한다. 요약은 검색을 다시 실행하지 않는다. 두 결과가 첫 시도에 성공하면 제목 생성·제목 검수·답변 요약 생성·답변 요약 검수로 **Qwen 호출이 네 번** 추가된다. 답변 요약의 형식·내용 검증 오류에는 답변 요약만 최대 한 번 재시도하며, 재시도 시 검수 호출도 추가될 수 있다. 모델 호출 오류에는 재시도하지 않는다. 호출은 현재 동기식이며, 각 결과가 나온 즉시 반환하는 스트리밍 인터페이스는 없다.

결과 계약은 다음과 같다.

```json
{
  "question_title": "Raspberry Pi SSH 설정 방법",
  "question_title_status": "available",
  "answer_summary": "설정 도구에서 SSH를 활성화할 수 있습니다. [C1]",
  "answer_summary_status": "available"
}
```

예시 문구는 필드 형식 설명용이며 실제 모델 결과가 아니다. `answer_summary`에 쓰인 인용 ID는 해당 원답변의 본문에 실제로 존재해야 한다.

각 상태의 의미는 두 필드에 독립적으로 적용된다.

| 상태 | 의미 | 텍스트 값 |
| --- | --- | --- |
| `available` | 생성 및 검증 성공 | 공백이 아닌 한 줄 문자열 |
| `generation_failed` | 모델 호출 또는 출력 검증 실패 | `null` |
| `not_applicable` | 입력 질문이 유효하지 않거나, 답변 요약의 경우 최종 응답이 `answered`가 아님 | `null` |
| `unsupported` | Qwen 구조화 생성 경로를 쓸 수 없는 생성기 | `null` |

백엔드 담당자는 원래 질문·답변·`ChatResponse.request_id`와 요약 결과를 같은 Q&A 건에 연결해 저장·전달하면 된다. 저장 형태와 API 경로는 기존 백엔드 규약에 맞춰 결정한다. 모델 생성 오류가 나더라도 원답변 전달을 막지 않아야 한다. 제목과 답변 요약이 각각 다른 상태일 수 있으므로 묶어서 성공·실패 처리하지 않는다. 아카이브 제목이 없을 때 사용할 표시 문구는 백엔드·프론트에서 정한다.

## 프론트 표시 계약

- QnA: 원래 질문과 답변을 표시하고, `answer_summary_status == "available"`일 때 받은 `answer_summary`를 요약 토글에 표시한다.
- 질문 아카이브 목록: `question_title_status == "available"`이면 `question_title`을 제목으로 사용한다. 그 외 상태의 대체 제목은 화면 정책으로 정한다.
- 질문 아카이브 상세: 원문 질문·원답변·사용 가능한 답변 요약을 표시한다.
- `available`이 아닌 요약 필드는 `null`이므로 요약문처럼 표시하지 않는다. 요약의 `[C1]` 같은 인용은 **해당 원답변의 기존 citation 데이터**와 연결한다. 요약 결과는 새로운 출처 카드를 만들지 않는다.

요약 토글은 표시·숨김을 제어하는 UI이며, 현재 Python 서비스의 생성 취소 기능을 뜻하지 않는다.

## 검증 근거와 한계

2026-09-17 RunPod A40에서 `Qwen/Qwen3-4B-Instruct-2507`로 Hybrid RAG → 최종 답변 → 제목 → 답변 요약을 20개 질문에 대해 실행했다. 당시 버전에서 제목은 **20/20** `available`; 최종 답변 18건이 `answered`였고 해당 요약은 **18/18** `available`; 나머지 2건은 `not_applicable`이었다. 전체 실행에서 같은 답변 생성기와 로드된 Qwen 모델을 재사용했다. **이 수치는 이후 추가한 의미 검수·질문 항목·인용 대응 검사 이전의 결과**이므로 현재 코드의 성공률로 해석하지 않는다. 현재 검사를 당시 18건에 재적용하면 12번과 16번 요약은 질문 항목 누락으로 거절된다. 이 결과는 표본 검증이며 모든 질문에 대한 성공률 보장은 아니다.

이후 RunPod에서 별도의 SoC 온도·냉각 질문과 Raspberry Pi 500+ 저장장치·키보드 질문을 시험했다. 두 건의 원답변은 `answered`였지만, 잘못 연결된 명령어 인용과 질문 항목 누락 때문에 현재 요약 서비스는 각각 `answer_summary_status=generation_failed`로 처리했다. 다시 고른 **텍스트 콘솔 부팅 설정**과 **카메라 소프트웨어 동기화 시작 순서** 질문에서는 제목·답변 요약이 각각 `available`이었고, 답변 요약의 핵심 내용과 인용을 원답변·공식 인용 근거에 대조했다. 이 네 건도 전체 질문에 대한 품질 보증은 아니다.

실행 결과: `artifacts/validation/2026-09-17/final/qa_summary_20_results.json`, `artifacts/validation/2026-09-17/final/qa_summary_20_results.csv`. **`artifacts/`는 Git에서 제외**되므로 팀에 이 결과가 필요하면 파일을 별도로 전달해야 한다.

현재 로컬 요약·생성기 관련 테스트는 103개 통과, Django 테스트를 제외한 pytest는 500개 통과·1개 건너뜀이다. 전체 pytest는 이 로컬 환경에 Django가 없어 Django 테스트를 수집하지 못했다. 이번 작업은 `settings.py`와 `views.py`를 수정하지 않았다.

취소 기능은 RunPod A40의 실제 Qwen에서 확인했다. 별도 스레드의 `Event`를 추론 중 설정하자 `GenerationCancelled`가 전파됐고, 요약 서비스에서 시작한 제목 생성도 같은 방식으로 중단됐다. 두 번의 취소 뒤 같은 로드된 모델 인스턴스로 제목 생성에 성공했다. 이 검증은 요약 코드의 취소 경계를 확인한 것이며, 프론트 취소 버튼과 백엔드 작업 상태의 연결은 아직 검증하지 않았다.

인용 검증은 원답변의 인용 ID 존재 여부, 명령어와 인용의 대응, 질문에 명시적으로 나열된 항목, 일부 형식·수치 표현을 검사한다. Qwen 검수는 원답변의 인용 근거도 함께 읽지만, 모든 문장의 의미나 인용 관계를 완벽히 판정할 수는 없다. 불확실하거나 거절된 결과는 `generation_failed`로 반환할 수 있다. 원답변 자체의 오류도 요약 서비스가 고치지 않는다. 20건 중 11번 원답변의 `raspistill` 설명 모순과 16번 원답변의 `BOOT_ORDER` 설명 오류는 별도 Q&A 품질 과제로 남아 있다.

## 아직 연결하거나 설계해야 할 항목

1. 백엔드: 최종 `ChatResponse` 이후 서비스 호출, 결과 저장, API 응답, 기존 Q&A와 동일 건 매핑 및 실패 처리.
2. 프론트: QnA 요약 토글, 아카이브 목록·상세 표시, 상태별 대체 표시와 원답변 citation 연결.
3. 취소 연결: 요약 서비스는 `cancel_requested` 콜백을 받아 제목·검수·답변 요약 호출 사이에 확인한다. 요약용 Qwen 호출 중에도 Transformers의 중단 조건으로 토큰 생성 단계마다 확인한다. 취소 시 `GenerationCancelled` 예외가 전파되며, `QaSummaryResult`의 `generation_failed`로 바뀌지 않는다. 취소 신호를 넘기지 않는 기존 Q&A `generate()`와 Mini Challenge 호출에는 중단 조건이 추가되지 않는다. 모델 로딩이나 이미 실행 중인 GPU 연산 한 단계는 즉시 끊을 수 없고 다음 확인 지점에서 멈춘다. **프론트 취소 버튼 또는 API 요청 중단을 해당 콜백의 상태에 연결하는 백엔드 작업은 남아 있다.** 같은 프로세스의 `Event`를 쓸 경우 백엔드는 생성 중에도 다른 실행 흐름에서 `set()`을 호출할 수 있어야 한다. 다른 프로세스의 작업이라면 해당 작업에 맞는 취소 신호 저장소가 필요하다.

코드 진입점은 `src/services/qa_summary.py`, `src/rag_to_llm/qa_summary_text_generator.py`, `src/contracts/models.py`의 `QaSummaryResult`다. 검증 규칙은 `src/services/qa_summary_parser.py`, 프롬프트는 `src/lang/qa_summary_prompts.py`를 참조한다.
