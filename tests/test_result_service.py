"""Tests for the backend-callable feature result functions."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from web_app.portal.result_service import (
    get_challenge_result,
    get_command_lab_result,
    get_qa_result,
    get_recommendation_result,
)


class JsonResponseStub(SimpleNamespace):
    def model_dump(self, *, mode: str):
        assert mode == "json"
        return {
            "request_id": self.request_id,
            "status": self.status,
            "answer": self.answer,
        }


def test_get_qa_result_returns_question_answer_and_original_response():
    response = JsonResponseStub(request_id="qa-1", status="answered", answer="SSH 안내입니다.")
    service = Mock()
    service.answer.return_value = response

    returned = get_qa_result(service, request_id="qa-1", question="SSH를 어떻게 켜나요?")

    assert returned.question == "SSH를 어떻게 켜나요?"
    assert returned.answer == "SSH 안내입니다."
    assert returned.result is response
    assert returned.to_dict()["payload"]["result"]["request_id"] == "qa-1"
    service.answer.assert_called_once_with(
        request_id="qa-1",
        question="SSH를 어떻게 켜나요?",
        retrieval_mode="hybrid",
        trace=True,
    )


def test_get_recommendation_result_returns_form_input_with_answer():
    form = SimpleNamespace(
        request_id="recommend-1",
        free_text="홈 서버용 제품을 추천해 주세요.",
        model_dump=lambda mode: {"request_id": "recommend-1", "free_text": "홈 서버용 제품을 추천해 주세요."},
    )
    response = JsonResponseStub(request_id="recommend-1", status="answered", answer="Raspberry Pi 5를 추천합니다.")
    service = Mock()
    service.answer_form.return_value = response

    returned = get_recommendation_result(service, form=form)

    assert returned.feature == "recommendation"
    assert returned.question == form.free_text
    assert returned.answer == response.answer
    assert returned.payload["input"]["free_text"] == form.free_text
    service.answer_form.assert_called_once_with(form=form, trace=True)


def test_get_command_lab_result_calls_analyze_and_builds_answer():
    service = Mock()
    service.analyze.return_value = {
        "command": "ssh pi@raspberrypi.local",
        "effect_ko": "원격 셸에 접속합니다.",
        "execution_context": "클라이언트 터미널",
        "risk_notice_ko": "신뢰할 수 있는 호스트인지 확인하세요.",
        "limitations_ko": "명령은 실행하지 않습니다.",
    }

    returned = get_command_lab_result(service, command="ssh pi@raspberrypi.local")

    assert returned.feature == "command_lab"
    assert returned.question == "ssh pi@raspberrypi.local"
    assert "원격 셸에 접속합니다." in returned.answer
    assert "주의사항:" in returned.answer
    assert returned.result == service.analyze.return_value
    service.analyze.assert_called_once_with("ssh pi@raspberrypi.local")


def test_get_command_lab_result_calls_compose_when_template_is_given():
    service = Mock()
    service.compose.return_value = {
        "command": "ssh learner@raspberrypi.local",
        "effect_ko": "원격 접속합니다.",
        "execution_context": "터미널",
        "risk_notice_ko": "",
        "limitations_ko": "",
    }

    returned = get_command_lab_result(
        service,
        template_id="cmd-1",
        values={"host": "learner@raspberrypi.local"},
        product_id="rpi-5",
    )

    assert returned.question == "ssh learner@raspberrypi.local"
    service.compose.assert_called_once_with(
        "cmd-1", {"host": "learner@raspberrypi.local"}, product_id="rpi-5"
    )


def test_get_challenge_result_returns_prompt_selection_and_explanation():
    state = {"current_index": 0}
    question = {
        "question_id": "ssh-01",
        "prompt": "SSH의 기본 상태는 무엇인가요?",
        "choices": [
            {"choice_id": "A", "text": "활성화"},
            {"choice_id": "B", "text": "비활성화"},
        ],
    }
    outcome = {
        "correct": True,
        "selected_choice_id": "B",
        "correct_choice_id": "B",
        "choice_feedback": "맞았습니다.",
        "rationale_ko": "기본적으로 비활성화되어 있습니다.",
    }
    service = Mock()
    service.current_question.return_value = question
    service.submit.return_value = outcome

    returned = get_challenge_result(
        service,
        state=state,
        question_id="ssh-01",
        choice_id="B",
    )

    assert returned.feature == "challenge"
    assert returned.question == question["prompt"]
    assert returned.status == "correct"
    assert "선택한 답: 비활성화" in returned.answer
    assert "기본적으로 비활성화" in returned.answer
    assert returned.result is outcome
    service.current_question.assert_called_once_with(state)
    service.submit.assert_called_once_with(state, question_id="ssh-01", choice_id="B")
