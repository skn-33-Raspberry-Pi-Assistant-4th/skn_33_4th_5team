from src.contracts import QuizEvidence
from src.services.quiz_quote_candidates import extract_quote_candidates


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
