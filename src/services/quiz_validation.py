"""Deterministic structural checks for generated multiple-choice questions."""

from __future__ import annotations

from collections.abc import Mapping

from src.contracts import QuizEvidence, QuizQuestion


_EXPECTED_CHOICE_IDS = {"A", "B", "C", "D"}


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
    question. Verifying that the quote appears in the evidence body is handled
    separately so this function only enforces identifier and cardinality rules.
    """

    errors: list[str] = []
    if len(question.evidence_ids) != 1:
        errors.append("evidence_ids_must_contain_exactly_one")
    if len(question.supporting_quotes) != 1:
        errors.append("supporting_quotes_must_contain_exactly_one")
    if any(evidence_id not in evidence_by_id for evidence_id in question.evidence_ids):
        errors.append("evidence_ids_must_be_allowed")
    return errors


__all__ = ["validate_question_evidence", "validate_question_structure"]
