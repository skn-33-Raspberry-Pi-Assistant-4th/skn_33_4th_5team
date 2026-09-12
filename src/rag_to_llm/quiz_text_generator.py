"""Qwen structured generation을 QuizGenerator 계약에 연결한다."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .answer_generator import GenerationResult, HuggingFaceAnswerGenerator


class HuggingFaceQuizTextGenerator:
    """이미 생성된 Qwen runtime을 quiz raw-text 경로에 재사용한다.

    이 어댑터는 prompt, JSON parsing, 또는 evidence 검증을 수행하지 않는다.
    해당 책임은 각각 QuizGenerator의 기존 계층에 남겨 둔다.
    """

    def __init__(
        self,
        answer_generator: HuggingFaceAnswerGenerator,
        *,
        max_new_tokens: int = 512,
    ) -> None:
        self._answer_generator = answer_generator
        self._max_new_tokens = max_new_tokens
        self.last_result: GenerationResult | None = None

    def generate(self, messages: Sequence[Mapping[str, str]]) -> str:
        """Generate raw text once through the injected Qwen instance."""

        self.last_result = self._answer_generator.generate_structured(
            messages,
            max_new_tokens=self._max_new_tokens,
        )
        return self.last_result.text


__all__ = ["HuggingFaceQuizTextGenerator"]
