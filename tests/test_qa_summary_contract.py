"""Contract and parser tests for independently usable Q&A summaries."""

from __future__ import annotations

import json
from datetime import date

import pytest
from pydantic import ValidationError

from src.contracts import ChatCitation, ChatResponse, QaSummaryResult
from src.services.qa_summary_parser import (
    QaSummaryOutputError,
    parse_answer_summary,
    parse_question_title,
)


def _response() -> ChatResponse:
    return ChatResponse(
        schema_version="1.2.0",
        request_id="qa-summary-test",
        status="answered",
        language="ko",
        answer="SSH는 기본적으로 비활성화되어 있습니다. [C1]",
        conditions=None,
        citations=[
            ChatCitation(
                citation_id="C1",
                document_id="remote-access",
                chunk_id="ssh-001",
                title="Remote access",
                publisher="Raspberry Pi Ltd",
                section="SSH",
                source_url="https://www.raspberrypi.com/documentation/computers/remote-access.html",
                source_anchor=None,
                document_version=None,
                published_at=None,
                updated_at=None,
                collected_at=date(2026, 9, 12),
                license="CC BY-SA 4.0",
                quote="SSH is disabled by default on Raspberry Pi OS.",
            )
        ],
        products=[],
        media=[],
        clarification_questions=[],
        warnings=[],
    )


def test_title_and_answer_summary_can_succeed_independently() -> None:
    title_only = QaSummaryResult(
        question_title="Raspberry Pi SSH 설정 방법",
        question_title_status="available",
        answer_summary=None,
        answer_summary_status="generation_failed",
    )
    answer_only = QaSummaryResult(
        question_title=None,
        question_title_status="generation_failed",
        answer_summary="SSH는 기본적으로 비활성화되어 있습니다. [C1]",
        answer_summary_status="available",
    )

    assert title_only.question_title is not None and title_only.answer_summary is None
    assert answer_only.question_title is None and answer_only.answer_summary is not None


@pytest.mark.parametrize("status", ["generation_failed", "not_applicable", "unsupported"])
def test_non_available_fields_must_be_null(status: str) -> None:
    with pytest.raises(ValidationError):
        QaSummaryResult(
            question_title="잘못된 제목",
            question_title_status=status,
            answer_summary=None,
            answer_summary_status="not_applicable",
        )


@pytest.mark.parametrize("value", [None, "", "  ", " 제목 ", "첫 줄\n둘째 줄", "가" * 201])
def test_available_title_rejects_invalid_text(value: str | None) -> None:
    with pytest.raises(ValidationError):
        QaSummaryResult(
            question_title=value,
            question_title_status="available",
            answer_summary=None,
            answer_summary_status="not_applicable",
        )


@pytest.mark.parametrize("value", [None, "", "  ", " 요약 ", "첫 줄\n둘째 줄", "가" * 501])
def test_available_answer_summary_rejects_invalid_text(value: str | None) -> None:
    with pytest.raises(ValidationError):
        QaSummaryResult(
            question_title=None,
            question_title_status="not_applicable",
            answer_summary=value,
            answer_summary_status="available",
        )


def test_parsers_accept_separate_valid_json_outputs() -> None:
    response = _response()
    title = parse_question_title(json.dumps({"question_title": "Raspberry Pi SSH 설정 방법"}))
    summary = parse_answer_summary(
        json.dumps({"answer_summary": "SSH는 기본적으로 비활성화되어 있습니다. [C1]"}),
        response,
    )

    assert title == "Raspberry Pi SSH 설정 방법"
    assert summary == "SSH는 기본적으로 비활성화되어 있습니다. [C1]"


@pytest.mark.parametrize(
    ("raw_output", "field_name"),
    [
        ("not json", "question_title"),
        ("{}", "question_title"),
        ('{"question_title":"제목","answer_summary":"요약"}', "question_title"),
        ('{"question_title":null}', "question_title"),
        ('{"question_title":""}', "question_title"),
        ('{"answer_summary":""}', "answer_summary"),
        (json.dumps({"answer_summary": "가" * 501}), "answer_summary"),
    ],
)
def test_parsers_reject_invalid_model_outputs(raw_output: str, field_name: str) -> None:
    with pytest.raises(QaSummaryOutputError):
        if field_name == "question_title":
            parse_question_title(raw_output)
        else:
            parse_answer_summary(raw_output, _response())


def test_answer_summary_rejects_citation_not_used_by_final_answer() -> None:
    with pytest.raises(QaSummaryOutputError, match="인용 ID"):
        parse_answer_summary(
            json.dumps({"answer_summary": "SSH를 활성화하세요. [C2]"}),
            _response(),
        )


def test_summary_contract_rejects_undeclared_fields() -> None:
    with pytest.raises(ValidationError):
        QaSummaryResult(
            question_title=None,
            question_title_status="not_applicable",
            answer_summary=None,
            answer_summary_status="not_applicable",
            status="available",
        )
