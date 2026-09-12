import pytest
from pydantic import ValidationError

from src.contracts import (
    QuizChoice,
    QuizEvidence,
    QuizGenerationRequest,
    QuizQuestion,
    QuizResponse,
)


def valid_quiz_evidence() -> QuizEvidence:
    return QuizEvidence(
        citation_id="C1",
        document_id="computers-remote-access-ssh",
        chunk_id="computers-remote-access-ssh-001",
        content="Raspberry Pi OS disables SSH by default.",
    )


def valid_quiz_question() -> QuizQuestion:
    return QuizQuestion(
        question_id="generated-001",
        question="SSH의 기본 상태는 무엇인가요?",
        choices=[
            QuizChoice(id="A", text="기본적으로 비활성화"),
            QuizChoice(id="B", text="기본적으로 활성화"),
        ],
        correct_choice_id="A",
        explanation="공식 문서는 SSH가 기본적으로 비활성화된다고 설명합니다.",
        evidence_ids=["C1"],
        supporting_quotes=["Raspberry Pi OS disables SSH by default."],
    )


def test_quiz_evidence_accepts_a_final_qa_citation() -> None:
    evidence = QuizEvidence(
        citation_id="C1",
        document_id="computers-remote-access-ssh",
        chunk_id="computers-remote-access-ssh-001",
        content="Raspberry Pi OS disables SSH by default.",
    )

    assert evidence.citation_id == "C1"
    assert evidence.chunk_id == "computers-remote-access-ssh-001"


def test_quiz_evidence_rejects_empty_content() -> None:
    with pytest.raises(ValidationError):
        QuizEvidence(
            citation_id="C1",
            document_id="computers-remote-access-ssh",
            chunk_id="computers-remote-access-ssh-001",
            content="",
        )


@pytest.mark.parametrize("field_name", ["document_id", "chunk_id", "content"])
def test_quiz_evidence_rejects_whitespace_only_required_text(field_name: str) -> None:
    values = {
        "citation_id": "C1",
        "document_id": "computers-remote-access-ssh",
        "chunk_id": "computers-remote-access-ssh-001",
        "content": "Raspberry Pi OS disables SSH by default.",
    }
    values[field_name] = "   \n\t"

    with pytest.raises(ValidationError):
        QuizEvidence(**values)


@pytest.mark.parametrize("citation_id", ["C0", "C01", "citation-1", "c1"])
def test_quiz_evidence_rejects_invalid_citation_id(citation_id: str) -> None:
    with pytest.raises(ValidationError):
        QuizEvidence(
            citation_id=citation_id,
            document_id="computers-remote-access-ssh",
            chunk_id="computers-remote-access-ssh-001",
            content="Raspberry Pi OS disables SSH by default.",
        )


def test_quiz_evidence_rejects_undefined_fields() -> None:
    with pytest.raises(ValidationError):
        QuizEvidence(
            citation_id="C1",
            document_id="computers-remote-access-ssh",
            chunk_id="computers-remote-access-ssh-001",
            content="Raspberry Pi OS disables SSH by default.",
            unsupported_field="value",
        )


@pytest.mark.parametrize("max_questions", [0, 4])
def test_quiz_generation_request_rejects_out_of_range_question_count(max_questions: int) -> None:
    with pytest.raises(ValidationError):
        QuizGenerationRequest(
            request_id="request-001",
            answer="SSH는 기본적으로 비활성화되어 있습니다. [C1]",
            evidence=[valid_quiz_evidence()],
            max_questions=max_questions,
        )


def test_quiz_response_accepts_available_questions() -> None:
    response = QuizResponse(status="available", questions=[valid_quiz_question()])

    assert response.status == "available"
    assert response.questions[0].correct_choice_id == "A"


def test_quiz_response_accepts_empty_insufficient_content() -> None:
    response = QuizResponse(status="insufficient_content", questions=[])

    assert response.questions == []


def test_quiz_response_rejects_invalid_status() -> None:
    with pytest.raises(ValidationError):
        QuizResponse(status="unknown", questions=[])
