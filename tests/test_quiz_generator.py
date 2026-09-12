from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date

from src.contracts import ChatCitation, ChatResponse, QuizEvidence, QuizGenerationRequest
from src.services.quiz_generator import QuizGenerator


class FakeQuizTextGenerator:
    def __init__(self, output: str):
        self.output = output
        self.calls: list[list[dict[str, str]]] = []

    def generate(self, messages: Sequence[Mapping[str, str]]) -> str:
        self.calls.append([dict(message) for message in messages])
        return self.output


def quiz_request() -> QuizGenerationRequest:
    return QuizGenerationRequest(
        request_id="request-001",
        answer="SSH는 기본적으로 비활성화되어 있습니다. [C1]",
        evidence=[
            QuizEvidence(
                citation_id="C1",
                document_id="computers-remote-access-ssh",
                chunk_id="computers-remote-access-ssh-001",
                content="Raspberry Pi OS disables SSH by default.",
            )
        ],
        max_questions=3,
    )


def question_payload(number: int, *, evidence_id: str = "C1") -> dict[str, object]:
    return {
        "question_id": f"generated_{number:03d}",
        "question": f"SSH 확인 항목 {number}의 기본 상태는 무엇인가요?",
        "choices": [
            {"id": "A", "text": "기본적으로 비활성화"},
            {"id": "B", "text": "기본적으로 활성화"},
            {"id": "C", "text": "설치 중에만 활성화"},
            {"id": "D", "text": "연결 상태에 따라 변경"},
        ],
        "correct_choice_id": "A",
        "explanation": "공식 문서는 SSH가 기본적으로 비활성화된다고 설명합니다.",
        "evidence_ids": [evidence_id],
        "supporting_quote_id": "C1-Q1",
    }


def model_output(questions: list[dict[str, object]]) -> str:
    return json.dumps({"status": "available", "questions": questions}, ensure_ascii=False)


def chat_citation() -> ChatCitation:
    return ChatCitation(
        citation_id="C1",
        document_id="computers-remote-access-ssh",
        chunk_id="computers-remote-access-ssh-001",
        title="Raspberry Pi documentation",
        publisher="Raspberry Pi Ltd",
        section="Remote access",
        source_url="https://www.raspberrypi.com/documentation/",
        source_anchor=None,
        document_version="commit-abc",
        published_at=None,
        updated_at=None,
        collected_at=date(2026, 9, 12),
        license="CC BY-SA 4.0",
        quote="Raspberry Pi OS disables SSH by default.",
    )


def chat_response(status: str, *, citations: list[ChatCitation]) -> ChatResponse:
    return ChatResponse.model_construct(
        schema_version="1.2.0",
        request_id="qa-request-001",
        status=status,
        language="ko",
        answer="SSH는 기본적으로 비활성화되어 있습니다. [C1]",
        conditions=None,
        citations=citations,
        products=[],
        media=[],
        clarification_questions=[],
        warnings=[],
    )


def test_quiz_generator_returns_available_for_valid_model_output() -> None:
    fake = FakeQuizTextGenerator(model_output([question_payload(1)]))

    response = QuizGenerator(fake).generate(quiz_request())

    assert response.status == "available"
    assert [question.question_id for question in response.questions] == ["generated_001"]
    assert len(fake.calls) == 1


def test_quiz_generator_returns_generation_failed_for_invalid_json() -> None:
    fake = FakeQuizTextGenerator("{invalid json")

    response = QuizGenerator(fake).generate(quiz_request())

    assert response.status == "generation_failed"
    assert response.questions == []
    assert len(fake.calls) == 1


def test_quiz_generator_removes_question_with_unknown_evidence_id() -> None:
    fake = FakeQuizTextGenerator(model_output([question_payload(1, evidence_id="C9")]))

    response = QuizGenerator(fake).generate(quiz_request())

    assert response.status == "insufficient_content"
    assert response.questions == []


def test_quiz_generator_keeps_only_valid_questions_after_validation() -> None:
    fake = FakeQuizTextGenerator(
        model_output(
            [
                question_payload(1),
                question_payload(2, evidence_id="C9"),
                question_payload(3, evidence_id="C8"),
            ]
        )
    )

    response = QuizGenerator(fake).generate(quiz_request())

    assert response.status == "available"
    assert [question.question_id for question in response.questions] == ["generated_001"]


def test_quiz_generator_returns_insufficient_content_when_all_questions_are_invalid() -> None:
    fake = FakeQuizTextGenerator(
        model_output(
            [
                question_payload(1, evidence_id="C9"),
                question_payload(2, evidence_id="C8"),
            ]
        )
    )

    response = QuizGenerator(fake).generate(quiz_request())

    assert response.status == "insufficient_content"
    assert response.questions == []


def test_quiz_generator_generates_from_answered_chat_response() -> None:
    fake = FakeQuizTextGenerator(model_output([question_payload(1)]))

    response = QuizGenerator(fake).generate_from_chat_response(
        chat_response("answered", citations=[chat_citation()])
    )

    assert response.status == "available"
    assert len(fake.calls) == 1


def test_quiz_generator_skips_insufficient_evidence_chat_response_without_model_call() -> None:
    fake = FakeQuizTextGenerator(model_output([question_payload(1)]))

    response = QuizGenerator(fake).generate_from_chat_response(
        chat_response("insufficient_evidence", citations=[])
    )

    assert response.status == "insufficient_content"
    assert response.questions == []
    assert len(fake.calls) == 0


def test_quiz_generator_skips_error_chat_response_without_model_call() -> None:
    fake = FakeQuizTextGenerator(model_output([question_payload(1)]))

    response = QuizGenerator(fake).generate_from_chat_response(
        chat_response("error", citations=[])
    )

    assert response.status == "insufficient_content"
    assert response.questions == []
    assert len(fake.calls) == 0


def test_quiz_generator_skips_answered_chat_response_without_citations() -> None:
    fake = FakeQuizTextGenerator(model_output([question_payload(1)]))

    response = QuizGenerator(fake).generate_from_chat_response(
        chat_response("answered", citations=[])
    )

    assert response.status == "insufficient_content"
    assert response.questions == []
    assert len(fake.calls) == 0
