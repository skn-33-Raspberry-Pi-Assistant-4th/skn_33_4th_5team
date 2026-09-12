"""RAG 근거를 답변 생성기에 전달하는 교체 가능한 생성 계층이다.

RunPod Pod의 Hugging Face Qwen 생성기는 답변 요청 시에만 lazy loading한다. import 시
API 호출이나 모델 로딩을 수행하지 않는다.
"""

from __future__ import annotations

from .answer_generator import (
    AnswerGenerationError,
    AnswerGenerator,
    EvidenceTemplateGenerator,
    GenerationResult,
    HuggingFaceAnswerGenerator,
)
from .factory import build_answer_generator
from .quiz_text_generator import HuggingFaceQuizTextGenerator
from .settings import AnswerGeneratorSettings, AnswerGeneratorSettingsError

__all__ = [
    "AnswerGenerationError",
    "AnswerGenerator",
    "AnswerGeneratorSettings",
    "AnswerGeneratorSettingsError",
    "EvidenceTemplateGenerator",
    "GenerationResult",
    "HuggingFaceAnswerGenerator",
    "HuggingFaceQuizTextGenerator",
    "build_answer_generator",
]
