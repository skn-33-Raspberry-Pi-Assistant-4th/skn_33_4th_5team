"""RAG QA 답변 생성기가 사용할 RunPod·로컬 공통 설정이다."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

from src.model_runtime import InferenceDeviceError, normalize_inference_device


DEFAULT_ANSWER_MODEL_ID = "Qwen/Qwen3-4B-Instruct-2507"
DEFAULT_ANSWER_MODEL_REVISION = "main"


class AnswerGeneratorSettingsError(ValueError):
    """답변 생성기 환경 변수가 누락됐거나 허용 범위를 벗어났을 때 발생한다."""


@dataclass(frozen=True)
class AnswerGeneratorSettings:
    """템플릿 또는 RunPod Hugging Face 생성기를 조립하는 실행 설정이다."""

    provider: Literal["template", "huggingface"]
    model_id: str
    model_revision: str
    load_in_4bit: bool
    max_new_tokens: int
    device: str

    @classmethod
    def from_env(cls, project_root: Path | None = None) -> "AnswerGeneratorSettings":
        """프로젝트 `.env`와 OS 환경변수에서 답변 생성기 설정을 읽는다."""

        root = (project_root or Path(__file__).resolve().parents[2]).resolve()
        load_dotenv(root / ".env", override=False)

        provider = os.getenv("ANSWER_GENERATOR", "template").strip().lower()
        if provider not in {"template", "huggingface"}:
            raise AnswerGeneratorSettingsError(
                "ANSWER_GENERATOR must be either 'template' or 'huggingface'."
            )

        def non_empty(name: str, default: str) -> str:
            value = os.getenv(name, default).strip()
            if not value:
                raise AnswerGeneratorSettingsError(f"{name} must not be empty.")
            return value

        load_in_4bit_raw = os.getenv("ANSWER_LOAD_IN_4BIT", "true").strip().lower()
        bool_values = {"true": True, "false": False}
        if load_in_4bit_raw not in bool_values:
            raise AnswerGeneratorSettingsError(
                "ANSWER_LOAD_IN_4BIT must be either 'true' or 'false'."
            )

        max_new_tokens_raw = os.getenv("ANSWER_MAX_NEW_TOKENS", "768").strip()
        try:
            max_new_tokens = int(max_new_tokens_raw)
        except ValueError as exc:
            raise AnswerGeneratorSettingsError(
                "ANSWER_MAX_NEW_TOKENS must be an integer between 1 and 1024."
            ) from exc
        if not 1 <= max_new_tokens <= 1024:
            raise AnswerGeneratorSettingsError(
                "ANSWER_MAX_NEW_TOKENS must be an integer between 1 and 1024."
            )

        try:
            device = normalize_inference_device(os.getenv("INFERENCE_DEVICE", "auto"))
        except InferenceDeviceError as exc:
            raise AnswerGeneratorSettingsError(str(exc)) from exc

        return cls(
            provider=provider,
            model_id=non_empty("ANSWER_MODEL_ID", DEFAULT_ANSWER_MODEL_ID),
            model_revision=non_empty("ANSWER_MODEL_REVISION", DEFAULT_ANSWER_MODEL_REVISION),
            load_in_4bit=bool_values[load_in_4bit_raw],
            max_new_tokens=max_new_tokens,
            device=device,
        )


__all__ = [
    "AnswerGeneratorSettings",
    "AnswerGeneratorSettingsError",
    "DEFAULT_ANSWER_MODEL_ID",
    "DEFAULT_ANSWER_MODEL_REVISION",
]
