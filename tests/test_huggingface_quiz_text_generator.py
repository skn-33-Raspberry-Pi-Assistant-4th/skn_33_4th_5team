"""Tests for the thin Qwen-to-QuizGenerator adapter."""

from __future__ import annotations

from unittest.mock import Mock

from src.rag_to_llm import (
    GenerationResult,
    HuggingFaceAnswerGenerator,
    HuggingFaceQuizTextGenerator,
)


def test_quiz_text_generator_uses_injected_structured_path_once() -> None:
    answer_generator = Mock(spec=HuggingFaceAnswerGenerator)
    result = GenerationResult(
        text='{"status":"insufficient_content","questions":[]}',
        provider="huggingface",
        model_id="Qwen/test",
        elapsed_ms=12.5,
    )
    answer_generator.generate_structured.return_value = result
    generator = HuggingFaceQuizTextGenerator(answer_generator, max_new_tokens=256)
    messages = [{"role": "system", "content": "JSON만 출력하세요."}]

    assert generator.generate(messages) == result.text
    assert generator.last_result is result
    answer_generator.generate_structured.assert_called_once_with(messages, max_new_tokens=256)
