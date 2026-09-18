import pytest

from src.contracts import QuizEvidence
from src.services.quiz_quote_candidates import (
    MAX_QUOTE_CANDIDATES_PER_EVIDENCE,
    extract_quote_candidates,
)


def test_extract_quote_candidates_uses_exact_single_list_item_substrings() -> None:
    evidence = QuizEvidence(
        citation_id="C1",
        document_id="doc-1",
        chunk_id="chunk-1",
        content=(
            "To install an OS, you need:\n"
            "- A blank storage device to be your boot media, typically a microSD card.\n"
            "- A computer you can use to write the OS image."
        ),
    )

    candidates = extract_quote_candidates([evidence])

    assert [candidate.quote_id for candidate in candidates] == ["C1-Q1", "C1-Q2"]
    assert candidates[0].content == "A blank storage device to be your boot media, typically a microSD card."
    assert all(candidate.content in evidence.content for candidate in candidates)


def test_extract_quote_candidates_excludes_out_of_range_text() -> None:
    evidence = QuizEvidence(
        citation_id="C1",
        document_id="doc-1",
        chunk_id="chunk-1",
        content="Short.\n" + ("a" * 241),
    )

    assert extract_quote_candidates([evidence]) == []


def test_extract_quote_candidates_bounds_long_evidence_without_losing_end_coverage() -> None:
    sentences = [f"Step {index} has enough text to be a valid exact quote." for index in range(1, 11)]
    evidence = QuizEvidence(
        citation_id="C1",
        document_id="doc-1",
        chunk_id="chunk-1",
        content="\n".join(sentences),
    )

    candidates = extract_quote_candidates([evidence])

    assert len(candidates) == MAX_QUOTE_CANDIDATES_PER_EVIDENCE
    assert candidates[0].quote_id == "C1-Q1"
    assert candidates[-1].quote_id == "C1-Q10"
    assert all(candidate.content in evidence.content for candidate in candidates)


def test_extract_quote_candidates_rejects_a_non_positive_per_evidence_limit() -> None:
    evidence = QuizEvidence(
        citation_id="C1",
        document_id="doc-1",
        chunk_id="chunk-1",
        content="A valid evidence sentence that is long enough.",
    )

    with pytest.raises(ValueError, match="at least 1"):
        extract_quote_candidates([evidence], max_per_evidence=0)
