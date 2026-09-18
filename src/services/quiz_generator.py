"""Framework-independent orchestration for dynamic mini-challenge generation."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from src.rag_to_llm.cancellation import call_cancellable, raise_if_cancelled
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
    """Generate and deterministically filter grounded quiz questions."""

    def __init__(self, text_generator: QuizTextGenerator):
        self._text_generator = text_generator

    def generate(self, request: QuizGenerationRequest, *, cancel_requested: Callable[[], bool] | None = None) -> QuizResponse:
        """Generate once and retry only an output-contract rejection one time."""

        raise_if_cancelled(cancel_requested)
        if not request.quote_candidates:
            request = request.model_copy(
                update={"quote_candidates": extract_quote_candidates(request.evidence)}
            )
        if not request.quote_candidates:
            return QuizResponse(status="insufficient_content", questions=[])

        messages = build_quiz_generation_messages(request)
        raw_output = call_cancellable(
            self._text_generator.generate,
            messages,
            cancel_requested=cancel_requested,
        )
        try:
            parsed = parse_quiz_draft_response(raw_output)
        except QuizOutputError:
            # Preserve the original grounded request and only strengthen the
            # output-shape instruction.  A malformed model response must not
            # bypass the existing schema and evidence checks below.
            raise_if_cancelled(cancel_requested)
            repair_messages = build_quiz_generation_messages(request, repair=True)
            repair_output = call_cancellable(
                self._text_generator.generate,
                repair_messages,
                cancel_requested=cancel_requested,
            )
            try:
                parsed = parse_quiz_draft_response(repair_output)
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
        cancel_requested: Callable[[], bool] | None = None,
    ) -> QuizResponse:
        """Generate a challenge from final Q&A citations without retrieval."""

        raise_if_cancelled(cancel_requested)
        request = chat_response_to_quiz_request(response, max_questions=max_questions)
        if request is None:
            return QuizResponse(status="insufficient_content", questions=[])
        return self.generate(request, cancel_requested=cancel_requested)


__all__ = ["QuizGenerator", "QuizTextGenerator"]
