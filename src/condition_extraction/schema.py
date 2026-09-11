"""팀 공통 조건 계약을 사용하는 제품 추천 설문 입력 모델을 정의한다."""

from __future__ import annotations

from pydantic import Field, field_validator

from src.contracts import ConditionPayload
from src.contracts.input_limits import MAX_INPUT_CHARS, validate_input_text
from src.contracts.models import StrictContract


class SurveyAnswer(StrictContract):
    """기존 설문 UI에서 전달되는 질문과 사용자 답변 한 쌍이다."""

    question_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_-]+$")
    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1, max_length=MAX_INPUT_CHARS)

    @field_validator("answer", mode="before")
    @classmethod
    def validate_text(cls, value):
        return validate_input_text(value) if isinstance(value, str) else value


class SurveyResponse(StrictContract):
    """한 사용자가 제출한 설문 답변 전체와 선택적 세션 ID를 담는다."""

    session_id: str | None = Field(default=None, max_length=100)
    answers: list[SurveyAnswer] = Field(min_length=1, max_length=20)

    def model_post_init(self, __context: object) -> None:
        """모델 생성 직후 한 설문 안의 question_id 중복을 검사한다."""

        ids = [answer.question_id for answer in self.answers]
        if len(ids) != len(set(ids)):
            raise ValueError("question_id는 한 설문 안에서 중복될 수 없습니다.")

    def to_prompt_text(self) -> str:
        """질문 ID·질문·답변을 모델이 읽을 수 있는 한국어 텍스트로 만든다."""

        return "\n".join(
            f"[{answer.question_id}] {answer.question}\n답변: {answer.answer}"
            for answer in self.answers
        )


CONDITION_FIELD_NAMES = tuple(ConditionPayload.model_fields)

__all__ = [
    "CONDITION_FIELD_NAMES",
    "ConditionPayload",
    "SurveyAnswer",
    "SurveyResponse",
]
