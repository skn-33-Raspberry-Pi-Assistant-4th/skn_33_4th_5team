"""Strict parser for one structured quiz model response."""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from src.contracts import QuizDraftResponse, QuizResponse


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


def _repair_json_syntax(text: str) -> str | None:
    """Return one conservative JSON syntax repair, or ``None`` when unsafe.

    The model occasionally adds a comma immediately before a closing container.
    It can also omit only the final outer closers after completing an inner
    object or list.  Both repairs preserve every JSON token the model emitted;
    this function never extracts prose, moves fields, invents values, or fixes
    an incomplete object.
    """

    repaired: list[str] = []
    stack: list[str] = []
    in_string = False
    escaped = False
    changed = False
    index = 0
    length = len(text)

    while index < length:
        char = text[index]
        if in_string:
            repaired.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            repaired.append(char)
        elif char in "[{":
            stack.append(char)
            repaired.append(char)
        elif char in "]}":
            cursor = len(repaired) - 1
            while cursor >= 0 and repaired[cursor].isspace():
                cursor -= 1
            if cursor >= 0 and repaired[cursor] == ",":
                del repaired[cursor]
                changed = True
            expected_opener = "[" if char == "]" else "{"
            if not stack or expected_opener != stack[-1]:
                return None
            stack.pop()
            repaired.append(char)
        else:
            repaired.append(char)
        index += 1

    if in_string:
        return None

    last_non_whitespace = next((char for char in reversed(repaired) if not char.isspace()), "")
    if stack:
        # A completed inner object/list can safely be wrapped by only its
        # missing outer closers.  Any other ending may be token truncation.
        if last_non_whitespace not in "]}":
            return None
        repaired.extend("]" if opener == "[" else "}" for opener in reversed(stack))
        changed = True

    return "".join(repaired) if changed else None


def _load_json_payload(raw_output: str) -> object:
    """Parse JSON once, then retry only an explicitly safe syntax repair."""

    text = _remove_full_code_fence(raw_output).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as initial_error:
        repaired = _repair_json_syntax(text)
        if repaired is None:
            raise initial_error
        return json.loads(repaired)


def parse_quiz_response(raw_output: str) -> QuizResponse:
    """Parse JSON-only model output into the shared quiz response contract.

    A complete Markdown code fence is accepted as a small presentation-only
    recovery. Natural-language prefixes, suffixes, partial JSON, and schema
    mismatches are intentionally rejected for the MVP's one-call policy.
    """

    try:
        payload = _load_json_payload(raw_output)
    except json.JSONDecodeError as exc:
        raise QuizOutputError("퀴즈 모델 출력이 유효한 JSON이 아닙니다.", raw_output) from exc

    try:
        response = QuizResponse.model_validate(payload, strict=True)
    except ValidationError as exc:
        raise QuizOutputError("퀴즈 모델 출력이 응답 계약과 일치하지 않습니다.", raw_output) from exc

    if response.status == "generation_failed":
        raise QuizOutputError("모델 출력은 generation_failed 상태를 사용할 수 없습니다.", raw_output)
    return response


def parse_quiz_draft_response(raw_output: str) -> QuizDraftResponse:
    """Parse the LLM-only shape that selects an exact quote candidate by ID."""

    try:
        payload = _load_json_payload(raw_output)
    except json.JSONDecodeError as exc:
        raise QuizOutputError("퀴즈 모델 출력이 유효한 JSON이 아닙니다.", raw_output) from exc

    try:
        response = QuizDraftResponse.model_validate(payload, strict=True)
    except ValidationError as exc:
        raise QuizOutputError("퀴즈 모델 출력이 응답 계약과 일치하지 않습니다.", raw_output) from exc

    if response.status == "generation_failed":
        raise QuizOutputError("모델 출력은 generation_failed 상태를 사용할 수 없습니다.", raw_output)
    return response


__all__ = ["QuizOutputError", "parse_quiz_draft_response", "parse_quiz_response"]
