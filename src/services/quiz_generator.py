"""Framework-independent orchestration for dynamic mini-challenge generation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from src.contracts import ChatResponse, QuizGenerationRequest, QuizResponse
from src.lang import build_quiz_generation_messages
from src.services.quiz_adapters import chat_response_to_quiz_request
from src.services.quiz_parser import QuizOutputError, parse_quiz_response
from src.services.quiz_validation import (
    finalize_questions,
    validate_question_evidence,
    validate_question_structure,
)


class QuizTextGenerator(Protocol):
    """Minimal model boundary used by QuizGenerator without framework coupling."""

    def generate(self, messages: Sequence[Mapping[str, str]]) -> str:
        """Return one raw model response for the supplied chat messages."""


class QuizGenerator:
    """Generate and deterministically filter grounded quiz questions once."""

    def __init__(self, text_generator: QuizTextGenerator):
        self._text_generator = text_generator

    def generate(self, request: QuizGenerationRequest) -> QuizResponse:
        """Call the text generator once, then reuse the existing quiz pipeline."""

        messages = build_quiz_generation_messages(request)
        raw_output = self._text_generator.generate(messages)
        try:
            parsed = parse_quiz_response(raw_output)
        except QuizOutputError:
            return QuizResponse(status="generation_failed", questions=[])

        if parsed.status == "insufficient_content":
            return parsed

        evidence_by_id = {item.citation_id: item for item in request.evidence}
        valid_questions = [
            question
            for question in parsed.questions
            if not validate_question_structure(question)
            and not validate_question_evidence(question, evidence_by_id)
        ]
        return finalize_questions(valid_questions, max_questions=request.max_questions)

    def generate_from_chat_response(
        self,
        response: ChatResponse,
        *,
        max_questions: int = 3,
    ) -> QuizResponse:
        """Generate a challenge from final Q&A citations without retrieval."""

        request = chat_response_to_quiz_request(response, max_questions=max_questions)
        if request is None:
            return QuizResponse(status="insufficient_content", questions=[])
        return self.generate(request)


__all__ = ["QuizGenerator", "QuizTextGenerator"]
