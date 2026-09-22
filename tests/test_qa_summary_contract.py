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
    parse_summary_review,
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


def test_answer_summary_accepts_valid_single_line_prose_from_qwen() -> None:
    assert (
        parse_answer_summary("SSH는 기본적으로 비활성화되어 있습니다. [C1]", _response())
        == "SSH는 기본적으로 비활성화되어 있습니다. [C1]"
    )


@pytest.mark.parametrize(
    "raw_output",
    [
        "설명:\nSSH는 기본적으로 비활성화되어 있습니다. [C1]",
        '설명 {"answer_summary":"SSH는 비활성화되어 있습니다. [C1]"}',
        "```json {SSH는 기본적으로 비활성화되어 있습니다. [C1]}```",
        "```SSH는 기본적으로 비활성화되어 있습니다. [C1]```",
        "첫 문장.둘째 문장.셋째 문장.넷째 문장. [C1]",
    ],
)
def test_answer_summary_rejects_unsafe_or_long_plain_output(raw_output: str) -> None:
    with pytest.raises(QaSummaryOutputError):
        parse_answer_summary(raw_output, _response())


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


@pytest.mark.parametrize(
    "summary",
    [
        "인용 없이 SSH를 활성화하세요.",
        "SSH를 활성화하세요. [C0]",
        "SSH를 활성화하세요. [C01]",
        "SSH를 활성화하세요. [C1] [C0]",
        "SSH를 활성화하세요. [C1] [C2,C3]",
    ],
)
def test_answer_summary_requires_only_valid_original_citations(summary: str) -> None:
    with pytest.raises(QaSummaryOutputError):
        parse_answer_summary(json.dumps({"answer_summary": summary}), _response())


@pytest.mark.parametrize(
    "summary",
    [
        "첫 문장. 둘째 문장. 셋째 문장. 넷째 문장. [C1]",
        "첫 문장.둘째 문장.셋째 문장.넷째 문장. [C1]",
    ],
)
def test_answer_summary_rejects_more_than_three_sentences(summary: str) -> None:
    with pytest.raises(QaSummaryOutputError, match="결과 계약"):
        parse_answer_summary(
            json.dumps({"answer_summary": summary}),
            _response(),
        )


def test_answer_summary_accepts_three_sentences() -> None:
    summary = "첫 문장. 둘째 문장. 셋째 문장. [C1]"

    assert parse_answer_summary(json.dumps({"answer_summary": summary}), _response()) == summary


def test_sentence_count_ignores_decimal_and_ascii_identifier_dots() -> None:
    summary = "Python 3.11에서 host.local에 접속하세요. [C1]"

    assert parse_answer_summary(json.dumps({"answer_summary": summary}), _response()) == summary


@pytest.mark.parametrize(
    ("summary", "reason"),
    [
        ("SSH는 가장 간편한 방법입니다. [C1]", "단정 표현"),
        ("SSH는 5.1V 이하에서만 가능합니다. [C1]", "수치 조건"),
    ],
)
def test_answer_summary_rejects_new_claim_strength(summary: str, reason: str) -> None:
    with pytest.raises(QaSummaryOutputError, match=reason):
        parse_answer_summary(json.dumps({"answer_summary": summary}), _response())


def test_summary_contract_rejects_undeclared_fields() -> None:
    with pytest.raises(ValidationError):
        QaSummaryResult(
            question_title=None,
            question_title_status="not_applicable",
            answer_summary=None,
            answer_summary_status="not_applicable",
            status="available",
        )


def test_review_parser_requires_exact_boolean_json() -> None:
    assert parse_summary_review('{"valid":true}') is True
    assert parse_summary_review('{"valid":false}') is False
    for raw in ('{"valid":"true"}', '{"valid":true,"reason":"ok"}', "true", "잘됨"):
        with pytest.raises(QaSummaryOutputError):
            parse_summary_review(raw)


@pytest.mark.parametrize(
    "question",
    [
        "저장장치와 키보드에서 무엇이 다른가요?",
        "저장장치 및 키보드 차이는 무엇인가요?",
    ],
)
def test_summary_does_not_fail_only_because_a_long_question_facet_is_omitted(question: str) -> None:
    response = _response().model_copy(
        update={"answer": "저장장치는 M.2 SSD입니다. [C1]"}
    )
    summary = "저장장치는 M.2 SSD입니다. [C1]"

    assert parse_answer_summary(
        json.dumps({"answer_summary": summary}), response, question
    ) == summary


def test_summary_rejects_command_with_wrong_original_citation() -> None:
    response = _response().model_copy(
        update={"answer": "`vcgencmd measure_temp`로 확인합니다. [C1] 팬이 냉각합니다. [C2]"}
    )
    with pytest.raises(QaSummaryOutputError, match="명령어의 인용"):
        parse_answer_summary(
            json.dumps({"answer_summary": "`vcgencmd measure_temp`로 확인하며 팬이 냉각합니다. [C2]"}),
            response,
        )


def test_summary_accepts_command_with_consecutive_original_citations() -> None:
    response = _response().model_copy(
        update={"answer": "`vcgencmd measure_temp`로 확인합니다. [C1][C2]"}
    )
    assert parse_answer_summary(
        json.dumps({"answer_summary": "`vcgencmd measure_temp`로 확인합니다. [C2]"}),
        response,
    )


def test_summary_rejects_likely_transcription_error() -> None:
    response = _response().model_copy(
        update={"answer": "라즈베리파이에서 SSH를 설정합니다. [C1]"}
    )
    with pytest.raises(QaSummaryOutputError, match="철자"):
        parse_answer_summary(
            json.dumps({"answer_summary": "라즈베이리파이에서 SSH를 설정합니다. [C1]"}),
            response,
            "라즈베리파이에서 SSH를 어떻게 설정하나요?",
        )
