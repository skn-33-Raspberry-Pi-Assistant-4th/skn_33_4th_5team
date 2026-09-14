"""Framework-independent orchestration for dynamic mini-challenge generation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from src.contracts import ChatResponse, QuizGenerationRequest, QuizQuestion, QuizResponse
from src.lang import build_quiz_generation_messages
from src.services.quiz_adapters import chat_response_to_quiz_request
from src.services.quiz_parser import QuizOutputError, parse_quiz_draft_response
from src.services.quiz_quote_candidates import extract_quote_candidates
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

        if not request.quote_candidates:
            request = request.model_copy(
                update={"quote_candidates": extract_quote_candidates(request.evidence)}
            )
        if not request.quote_candidates:
            return QuizResponse(status="insufficient_content", questions=[])

        messages = build_quiz_generation_messages(request)
        raw_output = self._text_generator.generate(messages)
        try:
            parsed = parse_quiz_draft_response(raw_output)
        except QuizOutputError:
            return QuizResponse(status="generation_failed", questions=[])

        if parsed.status == "insufficient_content":
            return QuizResponse(status="insufficient_content", questions=[])

        evidence_by_id = {item.citation_id: item for item in request.evidence}
        quote_by_id = {item.quote_id: item for item in request.quote_candidates}
        valid_questions = [
            question
            for draft in parsed.questions
            if (question := self._materialize_question(draft, quote_by_id)) is not None
            and not validate_question_structure(question)
            and not validate_question_evidence(question, evidence_by_id)
        ]
        return finalize_questions(valid_questions, max_questions=request.max_questions)

    @staticmethod
    def _materialize_question(draft, quote_by_id) -> QuizQuestion | None:
        """Replace an LLM-selected candidate ID with its exact source substring."""

        quote = quote_by_id.get(draft.supporting_quote_id)
        if quote is None or draft.evidence_ids != [quote.evidence_id]:
            return None
        return QuizQuestion(
            question_id=draft.question_id,
            question=draft.question,
            choices=draft.choices,
            correct_choice_id=draft.correct_choice_id,
            explanation=draft.explanation,
            evidence_ids=draft.evidence_ids,
            supporting_quotes=[quote.content],
        )

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
