from __future__ import annotations

import json

import pytest

from src.services.quiz_parser import QuizOutputError, parse_quiz_response


def valid_response_payload() -> dict[str, object]:
    return {
        "status": "available",
        "questions": [
            {
                "question_id": "generated_001",
                "question": "SSH의 기본 상태는 무엇인가요?",
                "choices": [
                    {"id": "A", "text": "기본적으로 비활성화"},
                    {"id": "B", "text": "기본적으로 활성화"},
                    {"id": "C", "text": "설치 중에만 활성화"},
                    {"id": "D", "text": "연결 상태에 따라 변경"},
                ],
                "correct_choice_id": "A",
                "explanation": "공식 문서는 SSH가 기본적으로 비활성화된다고 설명합니다.",
                "evidence_ids": ["C1"],
                "supporting_quotes": ["Raspberry Pi OS disables SSH by default."],
            }
        ],
    }


def serialized_valid_response() -> str:
    return json.dumps(valid_response_payload(), ensure_ascii=False)


@pytest.mark.parametrize(
    "raw_output",
    [
        pytest.param(serialized_valid_response(), id="plain_json"),
        pytest.param(f"```json\n{serialized_valid_response()}\n```", id="json_fence"),
        pytest.param(f"```\n{serialized_valid_response()}\n```", id="bare_fence"),
    ],
)
def test_parse_quiz_response_accepts_json_or_complete_code_fence(raw_output: str) -> None:
    response = parse_quiz_response(raw_output)

    assert response.status == "available"
    assert response.questions[0].question_id == "generated_001"


@pytest.mark.parametrize(
    "raw_output",
    [
        pytest.param(serialized_valid_response() + "\n생성 완료", id="trailing_prose"),
        pytest.param("{\"status\": \"available\", \"questions\": [", id="truncated_json"),
        pytest.param(
            json.dumps(
                {
                    **valid_response_payload(),
                    "questions": [
                        {
                            **valid_response_payload()["questions"][0],
                            "choices": ["A", "B", "C", "D"],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            id="choices_as_strings",
        ),
        pytest.param(
            json.dumps({**valid_response_payload(), "status": "unknown"}, ensure_ascii=False),
            id="invalid_status",
        ),
        pytest.param(
            json.dumps({"status": "generation_failed", "questions": []}, ensure_ascii=False),
            id="model_generated_failure_status",
        ),
        pytest.param(
            json.dumps({"status": "available", "questions": []}, ensure_ascii=False),
            id="available_without_questions",
        ),
        pytest.param(
            json.dumps(
                {"status": "insufficient_content", "questions": valid_response_payload()["questions"]},
                ensure_ascii=False,
            ),
            id="insufficient_content_with_questions",
        ),
        pytest.param(
            "설명입니다\n```json\n" + serialized_valid_response() + "\n```",
            id="prose_before_fence",
        ),
        pytest.param(
            "```json\n" + serialized_valid_response() + "\n```\n생성 완료",
            id="prose_after_fence",
        ),
    ],
)
def test_parse_quiz_response_rejects_non_contract_or_non_json_output(raw_output: str) -> None:
    with pytest.raises(QuizOutputError) as error:
        parse_quiz_response(raw_output)

    assert error.value.raw_output == raw_output
