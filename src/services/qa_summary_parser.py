"""Validate independent structured title and answer-summary model outputs."""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from src.contracts import ChatResponse, QaSummaryResult
from src.lang import extract_citation_ids


class QaSummaryOutputError(ValueError):
    """One summary model output is not usable under the public result contract."""

    def __init__(self, message: str, raw_output: str):
        super().__init__(message)
        self.raw_output = raw_output


def _parse_field(raw_output: str, field_name: str) -> str:
    """Accept one JSON object with exactly the requested string field."""

    try:
        payload = json.loads(raw_output.strip())
    except json.JSONDecodeError as exc:
        raise QaSummaryOutputError("요약 모델 출력이 유효한 JSON이 아닙니다.", raw_output) from exc
    if not isinstance(payload, dict) or set(payload) != {field_name}:
        raise QaSummaryOutputError("요약 모델 출력 필드가 계약과 일치하지 않습니다.", raw_output)
    value = payload[field_name]
    if not isinstance(value, str):
        raise QaSummaryOutputError("요약 모델 출력은 문자열이어야 합니다.", raw_output)
    try:
        QaSummaryResult(
            question_title=value if field_name == "question_title" else None,
            question_title_status="available" if field_name == "question_title" else "not_applicable",
            answer_summary=value if field_name == "answer_summary" else None,
            answer_summary_status="available" if field_name == "answer_summary" else "not_applicable",
        )
    except ValidationError as exc:
        raise QaSummaryOutputError("요약 모델 출력이 결과 계약을 통과하지 못했습니다.", raw_output) from exc
    return value


def parse_question_title(raw_output: str) -> str:
    """Parse a short, single-line title from a title-only model call."""

    return _parse_field(raw_output, "question_title")


def parse_answer_summary(raw_output: str, response: ChatResponse) -> str:
    """Parse a summary without accepting citations absent from the final answer."""

    try:
        json.loads(raw_output.strip())
    except json.JSONDecodeError:
        # Qwen sometimes returns the requested prose without a JSON wrapper.
        # Accept only a single clean line, then apply the same contract and
        # citation validation as JSON output. Never extract text from a mixed
        # explanation, code fence, or malformed JSON object.
        value = raw_output.strip()
        if (
            not value
            or "\n" in value
            or "\r" in value
            or "```" in value
            or any(char in value for char in "{}")
        ):
            raise QaSummaryOutputError("요약 모델 출력이 유효한 JSON 또는 한 줄 요약이 아닙니다.", raw_output)
        value = _parse_field(json.dumps({"answer_summary": value}), "answer_summary")
    else:
        value = _parse_field(raw_output, "answer_summary")
    cited_ids = extract_citation_ids(value)
    if not cited_ids:
        raise QaSummaryOutputError("답변 요약에는 원래 답변의 인용 ID가 필요합니다.", raw_output)
    # Any other square-bracketed marker, including malformed [C0] or [C01],
    # must not pass merely because the valid-ID extractor ignores it.
    uncited_text = re.sub(r"\[C[1-9][0-9]*\]", "", value)
    if "[" in uncited_text or "]" in uncited_text:
        raise QaSummaryOutputError("답변 요약에 잘못된 인용 표기가 있습니다.", raw_output)
    if not cited_ids.issubset(extract_citation_ids(response.answer)):
        raise QaSummaryOutputError("답변 요약에 원래 답변에 없는 인용 ID가 있습니다.", raw_output)
    # These terms materially strengthen a claim. An unsupported qualifier is
    # more dangerous than an unavailable summary, so fail closed and let the
    # summary service request one fresh candidate from the original answer.
    for qualifier in ("가장 ", "반드시", "무조건", "유일", "항상"):
        if qualifier in value and qualifier not in response.answer:
            raise QaSummaryOutputError("답변 요약에 원답변에 없는 단정 표현이 있습니다.", raw_output)
    normalized_answer = re.sub(r"\s+", "", response.answer)
    for match in re.finditer(r"\d+(?:\.\d+)?\s*[A-Za-z%]*\s*(?:이상|이하|미만|초과)", value):
        if re.sub(r"\s+", "", match.group()) not in normalized_answer:
            raise QaSummaryOutputError("답변 요약에 원답변에 없는 수치 조건이 있습니다.", raw_output)
    return value


__all__ = ["QaSummaryOutputError", "parse_answer_summary", "parse_question_title"]
