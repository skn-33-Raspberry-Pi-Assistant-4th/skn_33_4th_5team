"""Framework-independent summaries of completed Q&A questions and answers."""

from __future__ import annotations

import logging
from typing import Literal

from src.contracts import ChatResponse, QaSummaryResult
from src.contracts.input_limits import validate_input_text
from src.lang import build_answer_summary_messages, build_question_title_messages
from src.rag_to_llm.answer_generator import EvidenceTemplateGenerator
from src.services.qa_summary_parser import (
    QaSummaryOutputError,
    parse_answer_summary,
    parse_question_title,
)
from src.services.quiz_generator import QuizTextGenerator


logger = logging.getLogger(__name__)
MAX_GENERATED_TITLE_CHARS = 80


class QaSummaryService:
    """Generate title and answer summary independently of web storage flows."""

    def __init__(self, text_generator: QuizTextGenerator | None):
        # A QA template generator does not implement the one-argument structured
        # text boundary, even when passed here without the adapter factory.
        self._text_generator = (
            None if isinstance(text_generator, EvidenceTemplateGenerator) else text_generator
        )

    def generate_question_title(self, question: str) -> QaSummaryResult:
        """Return one title outcome; answer-summary remains independently unset."""

        if not isinstance(question, str):
            return self._title_result(None, "not_applicable")
        try:
            normalized_question = validate_input_text(question)
        except ValueError:
            return self._title_result(None, "not_applicable")
        if self._text_generator is None:
            return self._title_result(None, "unsupported")

        try:
            raw_output = self._text_generator.generate(
                build_question_title_messages(normalized_question)
            )
            title = parse_question_title(raw_output)
            if len(title) > MAX_GENERATED_TITLE_CHARS:
                raise QaSummaryOutputError("생성된 질문 제목이 너무 깁니다.", raw_output)
        except Exception as exc:
            logger.warning("Question title generation failed: %s", type(exc).__name__)
            return self._title_result(None, "generation_failed")
        return self._title_result(title, "available")

    def generate_answer_summary(self, question: str, response: ChatResponse) -> QaSummaryResult:
        """Summarize only an answered response, without affecting its title."""

        if response.status != "answered":
            return self._answer_result(None, "not_applicable")
        if not isinstance(question, str):
            return self._answer_result(None, "not_applicable")
        try:
            normalized_question = validate_input_text(question)
        except ValueError:
            return self._answer_result(None, "not_applicable")
        if self._text_generator is None:
            return self._answer_result(None, "unsupported")

        for retry in (False, True):
            try:
                raw_output = self._text_generator.generate(
                    build_answer_summary_messages(normalized_question, response.answer, retry=retry)
                )
            except Exception as exc:
                logger.warning("Answer summary generation failed: %s", type(exc).__name__)
                return self._answer_result(None, "generation_failed")
            try:
                summary = parse_answer_summary(raw_output, response)
            except QaSummaryOutputError as exc:
                logger.warning("Answer summary output rejected: %s", exc)
                if retry:
                    return self._answer_result(None, "generation_failed")
                continue
            except Exception as exc:
                logger.warning("Answer summary validation failed: %s", type(exc).__name__)
                return self._answer_result(None, "generation_failed")
            return self._answer_result(summary, "available")

        return self._answer_result(None, "generation_failed")

    def generate(self, question: str, response: ChatResponse) -> QaSummaryResult:
        """Run both independent calls and preserve either successful outcome."""

        title_result = self.generate_question_title(question)
        answer_result = self.generate_answer_summary(question, response)
        return QaSummaryResult(
            question_title=title_result.question_title,
            question_title_status=title_result.question_title_status,
            answer_summary=answer_result.answer_summary,
            answer_summary_status=answer_result.answer_summary_status,
        )

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

    @staticmethod
    def _answer_result(
        summary: str | None,
        status: Literal["available", "generation_failed", "not_applicable", "unsupported"],
    ) -> QaSummaryResult:
        return QaSummaryResult(
            question_title=None,
            question_title_status="not_applicable",
            answer_summary=summary,
            answer_summary_status=status,
        )


__all__ = ["QaSummaryService"]
