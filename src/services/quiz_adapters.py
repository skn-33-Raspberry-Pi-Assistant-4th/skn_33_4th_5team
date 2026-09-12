"""Adapters that reuse final Q&A citations as quiz-generation evidence."""

from __future__ import annotations

from src.contracts import ChatResponse, QuizEvidence, QuizGenerationRequest


def chat_response_to_quiz_request(
    response: ChatResponse,
    *,
    max_questions: int = 3,
) -> QuizGenerationRequest | None:
    """Convert an answered Q&A response without invoking retrieval again.

    Only final citations are used. Their request-local citation ID, source
    document identifiers, and original quote are retained for later evidence
    validation by QuizGenerator.
    """

    if response.status != "answered" or not response.citations:
        return None

    return QuizGenerationRequest(
        request_id=response.request_id,
        answer=response.answer,
        evidence=[
            QuizEvidence(
                citation_id=citation.citation_id,
                document_id=citation.document_id,
                chunk_id=citation.chunk_id,
                content=citation.quote,
            )
            for citation in response.citations
        ],
        max_questions=max_questions,
    )


__all__ = ["chat_response_to_quiz_request"]
