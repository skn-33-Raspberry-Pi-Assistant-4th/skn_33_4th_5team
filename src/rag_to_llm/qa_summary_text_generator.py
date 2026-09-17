"""Reuse the already selected Qwen answer generator for summary JSON calls."""

from __future__ import annotations

from .answer_generator import AnswerGenerator, HuggingFaceAnswerGenerator
from .quiz_text_generator import HuggingFaceQuizTextGenerator


class HuggingFaceQaSummaryTextGenerator(HuggingFaceQuizTextGenerator):
    """Thin summary adapter sharing one Qwen model with Q&A and Mini Challenge."""

    def __init__(
        self,
        answer_generator: HuggingFaceAnswerGenerator,
        *,
        max_new_tokens: int = 256,
    ) -> None:
        super().__init__(answer_generator, max_new_tokens=max_new_tokens)


def build_qa_summary_text_generator(
    answer_generator: AnswerGenerator,
) -> HuggingFaceQaSummaryTextGenerator | None:
    """Return no generator for template or other non-Qwen answer providers."""

    if not isinstance(answer_generator, HuggingFaceAnswerGenerator):
        return None
    return HuggingFaceQaSummaryTextGenerator(answer_generator)


__all__ = ["HuggingFaceQaSummaryTextGenerator", "build_qa_summary_text_generator"]
