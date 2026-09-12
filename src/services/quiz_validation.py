"""Deterministic structural checks for generated multiple-choice questions."""

from __future__ import annotations

from collections.abc import Mapping

from src.contracts import QuizEvidence, QuizQuestion


_EXPECTED_CHOICE_IDS = {"A", "B", "C", "D"}
_MIN_SUPPORTING_QUOTE_CHARS = 15
_MAX_SUPPORTING_QUOTE_CHARS = 240


def _normalize_whitespace(value: str) -> str:
    """Trim and collapse whitespace without changing case or punctuation."""

    return " ".join(value.split())


def supporting_quote_matches(quote: str, evidence_content: str) -> bool:
    """Return whether a length-valid quote occurs in the normalized evidence."""

    normalized_quote = _normalize_whitespace(quote)
    quote_length = len(normalized_quote)
    if not _MIN_SUPPORTING_QUOTE_CHARS <= quote_length <= _MAX_SUPPORTING_QUOTE_CHARS:
        return False
    return normalized_quote in _normalize_whitespace(evidence_content)


def validate_question_structure(question: QuizQuestion) -> list[str]:
    """Return stable error codes for invalid multiple-choice question structure.

    This function intentionally validates only local question structure. Evidence
    allowlist, supporting-quote, and duplicate-question checks belong to later
    QuizGenerator validation steps.
    """

    errors: list[str] = []
    choice_ids = [choice.id for choice in question.choices]
    choice_texts = [choice.text for choice in question.choices]

    if len(question.choices) != 4:
        errors.append("choices_count_must_be_4")
    if set(choice_ids) != _EXPECTED_CHOICE_IDS or len(choice_ids) != len(set(choice_ids)):
        errors.append("choice_ids_must_be_A_B_C_D_once_each")
    if any(not text.strip() for text in choice_texts):
        errors.append("choice_text_must_not_be_blank")
    if len(choice_texts) != len(set(choice_texts)):
        errors.append("choice_texts_must_be_unique")
    if question.correct_choice_id not in choice_ids:
        errors.append("correct_choice_id_must_match_a_choice")
    if not question.question.strip():
        errors.append("question_must_not_be_blank")
    if not question.explanation.strip():
        errors.append("explanation_must_not_be_blank")

    return errors


def validate_question_evidence(
    question: QuizQuestion,
    evidence_by_id: Mapping[str, QuizEvidence],
) -> list[str]:
    """Return error codes when a question exceeds its supplied evidence scope.

    The MVP deliberately permits one evidence item and one supporting quote per
    question. The quote must be 15 to 240 characters after whitespace
    normalization and appear in that evidence body.
    """

    errors: list[str] = []
    if len(question.evidence_ids) != 1:
        errors.append("evidence_ids_must_contain_exactly_one")
    if len(question.supporting_quotes) != 1:
        errors.append("supporting_quotes_must_contain_exactly_one")
    if any(evidence_id not in evidence_by_id for evidence_id in question.evidence_ids):
        errors.append("evidence_ids_must_be_allowed")
    if (
        len(question.evidence_ids) == 1
        and len(question.supporting_quotes) == 1
        and question.evidence_ids[0] in evidence_by_id
    ):
        quote = question.supporting_quotes[0]
        normalized_quote = _normalize_whitespace(quote)
        quote_length = len(normalized_quote)
        if not _MIN_SUPPORTING_QUOTE_CHARS <= quote_length <= _MAX_SUPPORTING_QUOTE_CHARS:
            errors.append("supporting_quote_length_must_be_between_15_and_240")
        elif not supporting_quote_matches(
            quote,
            evidence_by_id[question.evidence_ids[0]].content,
        ):
            errors.append("supporting_quote_must_match_evidence_content")
    return errors


__all__ = [
    "supporting_quote_matches",
    "validate_question_evidence",
    "validate_question_structure",
]
