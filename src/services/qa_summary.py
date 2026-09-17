"""Framework-independent generation of titles for completed Q&A questions."""

from __future__ import annotations

import logging
from typing import Literal

from src.contracts import QaSummaryResult
from src.contracts.input_limits import validate_input_text
from src.lang import build_question_title_messages
from src.services.qa_summary_parser import QaSummaryOutputError, parse_question_title
from src.services.quiz_generator import QuizTextGenerator


logger = logging.getLogger(__name__)
MAX_GENERATED_TITLE_CHARS = 80


class QaSummaryService:
    """Generate a title without depending on answer-summary or web storage flows."""

    def __init__(self, text_generator: QuizTextGenerator | None):
        self._text_generator = text_generator

    def generate_question_title(self, question: str) -> QaSummaryResult:
        """Return one title outcome; answer-summary remains independently unset."""

        try:
            normalized_question = validate_input_text(question)
        except ValueError:
            return self._title_result(None, "not_applicable")
        if self._text_generator is None:
            return self._title_result(None, "unsupported")

        try:
            raw_output = self._text_generator.generate(build_question_title_messages(normalized_question))
            title = parse_question_title(raw_output)
            if len(title) > MAX_GENERATED_TITLE_CHARS:
                raise QaSummaryOutputError("생성된 질문 제목이 너무 깁니다.", raw_output)
        except Exception as exc:
            logger.warning("Question title generation failed: %s", type(exc).__name__)
            return self._title_result(None, "generation_failed")
        return self._title_result(title, "available")

    @staticmethod
    def _title_result(
        title: str | None,
        status: Literal["available", "generation_failed", "not_applicable", "unsupported"],
    ) -> QaSummaryResult:
        return QaSummaryResult(
            question_title=title,
            question_title_status=status,
            answer_summary=None,
            answer_summary_status="not_applicable",
        )


__all__ = ["QaSummaryService"]
