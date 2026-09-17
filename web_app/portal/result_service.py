"""Callable result functions for the four user-facing PiCare features."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar
from uuid import uuid4


Feature = Literal["qa", "recommendation", "command_lab", "challenge"]
ResultT = TypeVar("ResultT")


def _json_payload(value: Any) -> Any:
    """Return JSON-safe data without losing Pydantic response fields."""

    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return deepcopy(value)
    if isinstance(value, (list, tuple)):
        return [_json_payload(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    # Test doubles and legacy response objects still expose the public fields
    # needed by the UI.  Never serialize arbitrary private attributes.
    return {
        key: _json_payload(getattr(value, key))
        for key in (
            "request_id",
            "status",
            "answer",
            "clarification_questions",
            "warnings",
        )
        if hasattr(value, key)
    }


@dataclass(frozen=True)
class FeatureResult(Generic[ResultT]):
    """A domain result plus its normalized user question and answer."""

    feature: Feature
    request_id: str
    question: str
    answer: str
    status: str
    payload: dict[str, Any]
    result: ResultT

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe value for an API response or another backend."""

        return {
            "feature": self.feature,
            "request_id": self.request_id,
            "question": self.question,
            "answer": self.answer,
            "status": self.status,
            "payload": deepcopy(self.payload),
        }


def get_qa_result(
    service: Any,
    *,
    request_id: str,
    question: str,
    retrieval_mode: str = "hybrid",
    trace: bool = True,
) -> FeatureResult[Any]:
    """Call Q&A and return its response together with the user's question."""

    response = service.answer(
        request_id=request_id,
        question=question,
        retrieval_mode=retrieval_mode,
        trace=trace,
    )
    return FeatureResult(
        feature="qa",
        request_id=str(getattr(response, "request_id", request_id)),
        question=question,
        answer=str(response.answer),
        status=str(response.status),
        payload={"input": {"question": question}, "result": _json_payload(response)},
        result=response,
    )


def get_recommendation_result(service: Any, *, form: Any, trace: bool = True) -> FeatureResult[Any]:
    """Call product recommendation and return its result with the user input."""

    response = service.answer_form(form=form, trace=trace)
    form_payload = _json_payload(form)
    return FeatureResult(
        feature="recommendation",
        request_id=str(getattr(response, "request_id", form.request_id)),
        question=str(form.free_text),
        answer=str(response.answer),
        status=str(response.status),
        payload={"input": form_payload, "result": _json_payload(response)},
        result=response,
    )


def _command_answer(result: dict[str, Any]) -> str:
    lines = [str(result["effect_ko"]), f"사용 위치: {result['execution_context']}"]
    if result.get("risk_notice_ko"):
        lines.append(f"주의사항: {result['risk_notice_ko']}")
    if result.get("limitations_ko"):
        lines.append(f"제한사항: {result['limitations_ko']}")
    return "\n".join(lines)


def get_command_lab_result(
    service: Any,
    *,
    command: str | None = None,
    template_id: str | None = None,
    values: dict[str, str] | None = None,
    product_id: str | None = None,
) -> FeatureResult[dict[str, Any]]:
    """Call command analysis/composition and return its explanation."""

    if command is not None:
        result = service.analyze(command)
    elif template_id is not None:
        result = service.compose(template_id, values, product_id=product_id)
    else:
        raise ValueError("분석할 명령어나 명령어 템플릿이 필요합니다.")
    return FeatureResult(
        feature="command_lab",
        request_id=str(uuid4()),
        question=str(result["command"]),
        answer=_command_answer(result),
        status="analyzed",
        payload={
            "input": {
                "command": command,
                "template_id": template_id,
                "values": deepcopy(values or {}),
                "product_id": product_id,
            },
            "result": _json_payload(result),
        },
        result=result,
    )


def _value(item: Any, key: str, default: Any = None) -> Any:
    """Read the same public field from a Pydantic model or a legacy mapping."""

    return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)


def get_challenge_result(
    *,
    question: Any,
    selected_choice_id: str,
    submission: dict[str, Any],
    request_id: str | None = None,
) -> FeatureResult[dict[str, Any]]:
    """Normalize one submitted dynamic Mini Challenge answer.

    Quiz creation and answer-key protection remain owned by the Q&A session API.
    This function is deliberately called only after the server has graded a choice.
    """

    choices = {
        str(_value(item, "id", _value(item, "choice_id"))): str(_value(item, "text", ""))
        for item in (_value(question, "choices", []) or [])
    }
    selected_id = str(submission.get("selected_choice_id", selected_choice_id))
    correct_id = str(submission["correct_choice_id"])
    selected_text = choices.get(selected_id, selected_id)
    correct_text = choices.get(correct_id, correct_id)
    is_correct = bool(submission.get("is_correct", submission.get("correct", False)))
    feedback = submission.get("choice_feedback") or ("정답입니다." if is_correct else "오답입니다.")
    explanation = submission.get("explanation") or submission.get("rationale_ko") or ""
    answer = "\n".join(
        line
        for line in (
            f"선택한 답: {selected_text}",
            f"정답: {correct_text}",
            str(feedback),
            str(explanation),
        )
        if line
    )
    return FeatureResult(
        feature="challenge",
        request_id=request_id or str(uuid4()),
        question=str(_value(question, "question", _value(question, "prompt", ""))),
        answer=answer,
        status="correct" if is_correct else "incorrect",
        payload={
            "input": {
                "question": _json_payload(question),
                "selected_choice_id": selected_id,
            },
            "result": _json_payload(submission),
        },
        result=submission,
    )


__all__ = [
    "FeatureResult",
    "get_challenge_result",
    "get_command_lab_result",
    "get_qa_result",
    "get_recommendation_result",
]
