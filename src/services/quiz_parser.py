"""Strict parser for one structured quiz model response."""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from src.contracts import QuizResponse


_FULL_CODE_FENCE = re.compile(
    r"\A\s*```(?:json)?[ \t]*\n(?P<content>[\s\S]*?)\n?```\s*\Z",
    re.IGNORECASE,
)


class QuizOutputError(ValueError):
    """Raised when one model output is not a valid quiz response JSON object."""

    def __init__(self, message: str, raw_output: str):
        super().__init__(message)
        self.raw_output = raw_output


def _remove_full_code_fence(raw_output: str) -> str:
    """Allow only a complete Markdown JSON fence, never surrounding prose."""

    match = _FULL_CODE_FENCE.fullmatch(raw_output)
    return match.group("content") if match else raw_output


def parse_quiz_response(raw_output: str) -> QuizResponse:
    """Parse JSON-only model output into the shared quiz response contract.

    A complete Markdown code fence is accepted as a small presentation-only
    recovery. Natural-language prefixes, suffixes, partial JSON, and schema
    mismatches are intentionally rejected for the MVP's one-call policy.
    """

    text = _remove_full_code_fence(raw_output).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise QuizOutputError("퀴즈 모델 출력이 유효한 JSON이 아닙니다.", raw_output) from exc

    try:
        response = QuizResponse.model_validate(payload, strict=True)
    except ValidationError as exc:
        raise QuizOutputError("퀴즈 모델 출력이 응답 계약과 일치하지 않습니다.", raw_output) from exc

    if response.status == "generation_failed":
        raise QuizOutputError("모델 출력은 generation_failed 상태를 사용할 수 없습니다.", raw_output)
    return response


__all__ = ["QuizOutputError", "parse_quiz_response"]
