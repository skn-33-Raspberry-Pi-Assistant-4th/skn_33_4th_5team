"""Framework-independent summaries of completed Q&A questions and answers."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Literal

from src.contracts import ChatResponse, QaSummaryResult
from src.contracts.input_limits import validate_input_text
from src.lang import (
    build_answer_summary_messages,
    build_answer_summary_review_messages,
    build_question_title_messages,
    build_question_title_review_messages,
)
from src.rag_to_llm.answer_generator import EvidenceTemplateGenerator
from src.rag_to_llm.cancellation import GenerationCancelled, raise_if_cancelled
from src.services.qa_summary_parser import (
    QaSummaryOutputError,
    parse_answer_summary,
    parse_question_title,
    parse_summary_review,
)
from src.services.quiz_generator import QuizTextGenerator


logger = logging.getLogger(__name__)
MAX_GENERATED_TITLE_CHARS = 80
_LIST_ITEM_PREFIX = re.compile(r"^\s*(?:[-*]\s+|\d+[.)]\s+)")


def _fallback_answer_summary(response: ChatResponse) -> str | None:
    """Reuse leading cited answer items only when the normal summary validator accepts them."""

    blocks: list[str] = []
    current: list[str] = []
    for raw_line in response.answer.splitlines():
        line = raw_line.strip()
        starts_item = bool(_LIST_ITEM_PREFIX.match(line))
        if current and (not line or starts_item):
            blocks.append(" ".join(current))
            current = []
        if line:
            current.append(line)
    if current:
        blocks.append(" ".join(current))

    selected: list[str] = []
    fallback: str | None = None
    for block in blocks:
        normalized = _LIST_ITEM_PREFIX.sub("", block, count=1).strip()
        if not normalized or not re.search(r"\[C[1-9][0-9]*\]", normalized):
            continue
        candidate = " ".join([*selected, normalized])
        if len(candidate) > 500:
            break
        try:
            # The fallback is not exempt from the public summary contract,
            # citation allowlist, command mapping, or numeric-strength checks.
            parse_answer_summary(
                json.dumps({"answer_summary": candidate}, ensure_ascii=False),
                response,
            )
        except QaSummaryOutputError:
            break
        selected.append(normalized)
        fallback = candidate
        if len(selected) == 3:
            break
    return fallback


class QaSummaryService:
    """Generate title and answer summary independently of web storage flows."""

    def __init__(
        self,
        text_generator: QuizTextGenerator | None,
        *,
        cancel_requested: Callable[[], bool] | None = None,
    ):
        # A QA template generator does not implement the one-argument structured
        # text boundary, even when passed here without the adapter factory.
        self._text_generator = (
            None if isinstance(text_generator, EvidenceTemplateGenerator) else text_generator
        )
        self._cancel_requested = cancel_requested

    def _check_cancel(self) -> None:
        raise_if_cancelled(self._cancel_requested)

    def _generate_text(self, messages: Sequence[Mapping[str, str]]) -> str:
        self._check_cancel()
        assert self._text_generator is not None
        if self._cancel_requested is None:
            output = self._text_generator.generate(messages)
        else:
            output = self._text_generator.generate(
                messages, cancel_requested=self._cancel_requested
            )
        self._check_cancel()
        return output

    def generate_question_title(self, question: str) -> QaSummaryResult:
        """Return one title outcome; answer-summary remains independently unset."""

        self._check_cancel()
        if not isinstance(question, str):
            return self._title_result(None, "not_applicable")
        try:
            normalized_question = validate_input_text(question)
        except ValueError:
            return self._title_result(None, "not_applicable")
        if self._text_generator is None:
            return self._title_result(None, "unsupported")

        try:
            raw_output = self._generate_text(
                build_question_title_messages(normalized_question)
            )
            title = parse_question_title(raw_output)
            if len(title) > MAX_GENERATED_TITLE_CHARS:
                raise QaSummaryOutputError("생성된 질문 제목이 너무 깁니다.", raw_output)
            review = self._generate_text(
                build_question_title_review_messages(normalized_question, title)
            )
            if not parse_summary_review(review):
                raise QaSummaryOutputError("질문 제목 검수를 통과하지 못했습니다.", review)
        except GenerationCancelled:
            raise
        except Exception as exc:
            logger.warning("Question title generation failed: %s", type(exc).__name__)
            return self._title_result(None, "generation_failed")
        return self._title_result(title, "available")

    def generate_answer_summary(self, question: str, response: ChatResponse) -> QaSummaryResult:
        """Summarize only an answered response, without affecting its title."""

        self._check_cancel()
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

        for attempt, retry in enumerate((False, True), start=1):
            try:
                raw_output = self._generate_text(
                    build_answer_summary_messages(normalized_question, response.answer, retry=retry)
                )
            except GenerationCancelled:
                raise
            except Exception as exc:
                logger.warning(
                    "Answer summary generation failed: attempt=%d error=%s",
                    attempt,
                    type(exc).__name__,
                )
                return self._answer_result(None, "generation_failed")
            try:
                summary = parse_answer_summary(raw_output, response, normalized_question)
                review = self._generate_text(
                    build_answer_summary_review_messages(normalized_question, response, summary)
                )
                if not parse_summary_review(review):
                    raise QaSummaryOutputError("답변 요약 검수를 통과하지 못했습니다.", review)
            except GenerationCancelled:
                raise
            except QaSummaryOutputError as exc:
                logger.warning(
                    "Answer summary output rejected: attempt=%d reason=%s raw_length=%d",
                    attempt,
                    str(exc),
                    len(exc.raw_output),
                )
                if retry:
                    break
                continue
            except Exception as exc:
                logger.warning(
                    "Answer summary validation failed: attempt=%d error=%s",
                    attempt,
                    type(exc).__name__,
                )
                return self._answer_result(None, "generation_failed")
            return self._answer_result(summary, "available")

        fallback = _fallback_answer_summary(response)
        if fallback is not None:
            logger.info(
                "Answer summary used validated fallback: length=%d",
                len(fallback),
            )
            return self._answer_result(fallback, "available")
        return self._answer_result(None, "generation_failed")

    def generate(self, question: str, response: ChatResponse) -> QaSummaryResult:
        """Run both independent calls and preserve either successful outcome."""

        self._check_cancel()
        title_result = self.generate_question_title(question)
        self._check_cancel()
        answer_result = self.generate_answer_summary(question, response)
        self._check_cancel()
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
