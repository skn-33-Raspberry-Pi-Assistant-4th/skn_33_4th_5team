"""Deterministic structural checks for generated multiple-choice questions."""

from __future__ import annotations

from src.contracts import QuizQuestion


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


__all__ = ["validate_question_structure"]
