"""Worker-only tasks for C's Q&A-grounded Quiz generator."""

from __future__ import annotations

from celery import shared_task

from src.contracts import ChatResponse
from src.rag_to_llm.quiz_text_generator import HuggingFaceQuizTextGenerator
from src.services.quiz_generator import QuizGenerator


@shared_task(name="portal.generate_dynamic_quiz", acks_late=False)
def generate_dynamic_quiz(response_payload: dict, *, max_questions: int = 3) -> dict:
    """Generate a Quiz in a worker process that may be terminated by cancelAPI."""

    response = ChatResponse.model_validate(response_payload)
    if response.status != "answered" or not response.citations:
        return {"status": "insufficient_content", "questions": []}

    # Import inside the worker so web requests never initialise another model.
    from .services import get_qa_service

    answer_generator = getattr(get_qa_service(), "answer_generator", None)
    if answer_generator is None or not hasattr(answer_generator, "generate_structured"):
        raise RuntimeError("현재 Q&A 생성기는 퀴즈 structured generation을 지원하지 않습니다.")
    quiz = QuizGenerator(HuggingFaceQuizTextGenerator(answer_generator)).generate_from_chat_response(
        response,
        max_questions=max_questions,
    )
    return quiz.model_dump(mode="json")

