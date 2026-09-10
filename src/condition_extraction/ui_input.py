"""Streamlit 위젯값을 공통 조건 계약과 설문 입력으로 연결한다."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from src.contracts import ConditionPayload
from src.contracts.input_limits import MAX_INPUT_CHARS, validate_input_text
from src.contracts.models import StrictContract

from .schema import SurveyAnswer, SurveyResponse


USER_LEVEL_LABELS = {
    "선택 안 함": None,
    "입문자": "beginner",
    "중급자": "intermediate",
    "고급자": "advanced",
}
PERFORMANCE_PRIORITY_LABELS = {
    "선택 안 함": None,
    "낮음": "low",
    "보통": "medium",
    "높음": "high",
}


class RecommendationFormInput(StrictContract):
    """제품 추천 화면의 자유 입력·선택값·토글값을 검증하는 계약이다."""

    request_id: str = Field(min_length=1, max_length=120)
    free_text: str = Field(min_length=1, max_length=MAX_INPUT_CHARS)

    user_level: Literal["beginner", "intermediate", "advanced"] | None = None
    performance_priority: Literal["low", "medium", "high"] | None = None
    wireless_required: bool | None = None
    camera_required: bool | None = None
    gpio_required: bool | None = None
    monitor_absent: bool | None = None

    @field_validator("free_text", mode="before")
    @classmethod
    def validate_text(cls, value):
        return validate_input_text(value) if isinstance(value, str) else value

    @classmethod
    def from_widget_values(
        cls,
        *,
        request_id: str,
        free_text: str,
        user_level_label: str,
        performance_priority_label: str,
        wireless_required: bool | None,
        camera_required: bool | None,
        gpio_required: bool | None,
        monitor_absent: bool | None,
    ) -> "RecommendationFormInput":
        """화면의 한국어 선택 라벨을 내부 표준 enum 값으로 변환한다."""

        try:
            user_level = USER_LEVEL_LABELS[user_level_label]
            performance_priority = PERFORMANCE_PRIORITY_LABELS[
                performance_priority_label
            ]
        except KeyError as exc:
            raise ValueError(f"지원하지 않는 Streamlit 선택값입니다: {exc.args[0]}") from exc
        return cls(
            request_id=request_id,
            free_text=free_text,
            user_level=user_level,
            performance_priority=performance_priority,
            wireless_required=wireless_required,
            camera_required=camera_required,
            gpio_required=gpio_required,
            monitor_absent=monitor_absent,
        )

    def to_survey(self) -> SurveyResponse:
        """자유 입력과 위젯 선택값을 sLLM이 읽을 설문 답변으로 변환한다."""

        answers = [
            SurveyAnswer(
                question_id="purpose_environment",
                question="Raspberry Pi 제품 추천을 위해 사용 목적과 환경을 알려 주세요.",
                answer=self.free_text,
            )
        ]
        selections = (
            ("user_level", "사용자 수준은 무엇인가요?", self.user_level),
            ("performance_priority", "성능 우선순위는 무엇인가요?", self.performance_priority),
            ("wireless_required", "Wi-Fi가 필요한가요?", self.wireless_required),
            ("camera_required", "카메라를 사용하나요?", self.camera_required),
            ("gpio_required", "GPIO를 사용하나요?", self.gpio_required),
            ("monitor_absent", "사용 가능한 모니터가 없나요?", self.monitor_absent),
        )
        for field, question, value in selections:
            if value is not None:
                answer = ("예" if value else "아니요") if isinstance(value, bool) else value
                answers.append(SurveyAnswer(question_id=field, question=question, answer=answer))
        return SurveyResponse(session_id=self.request_id, answers=answers)

    def apply_explicit_values(self, extracted: ConditionPayload) -> ConditionPayload:
        """명시적인 UI 선택값을 sLLM 추출값보다 우선해 최종 조건에 반영한다."""

        explicit = {
            "intent": "product_recommendation",
            "user_level": self.user_level,
            "performance_priority": self.performance_priority,
            "wireless_required": self.wireless_required,
            "camera_required": self.camera_required,
            "gpio_required": self.gpio_required,
            "monitor_available": None if self.monitor_absent is None else not self.monitor_absent,
        }
        updated = extracted.model_copy(
            update={key: value for key, value in explicit.items() if value is not None}
        )
        return ConditionPayload.model_validate(updated.model_dump())


__all__ = [
    "PERFORMANCE_PRIORITY_LABELS",
    "RecommendationFormInput",
    "USER_LEVEL_LABELS",
]
