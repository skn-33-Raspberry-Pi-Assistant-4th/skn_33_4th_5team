import pytest
from pydantic import ValidationError

from src.contracts import QuizEvidence


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
