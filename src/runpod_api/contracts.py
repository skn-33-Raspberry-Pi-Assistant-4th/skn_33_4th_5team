"""Wire contracts shared by the RunPod HTTP boundary and its worker."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from src.contracts.models import StrictContract


JobKind = Literal["qa", "recommendation", "quiz"]
JobStatus = Literal[
    "queued",
    "running",
    "cancelling",
    "succeeded",
    "failed",
    "cancelled",
    "expired",
]


class JobCreate(StrictContract):
    """AWS Django 서버가 RunPod로 전달하는 하나의 AI 작업 요청 형식."""

    job_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    kind: JobKind
    payload: dict[str, object]

    @field_validator("payload")
    @classmethod
    def limit_payload_shape(cls, value: dict[str, object]) -> dict[str, object]:
        """요청 payload의 최상위 필드 수를 제한해 과도한 입력을 차단한다."""

        if len(value) > 32:
            raise ValueError("payload has too many top-level fields")
        return value


class JobResponse(StrictContract):
    """작업 생성·상태 조회·취소 API가 공통으로 반환하는 응답 형식."""

    job_id: str
    kind: JobKind
    status: JobStatus
    result: dict[str, object] | None = None
    error: str | None = None


class QaPayload(StrictContract):
    """질문 답변 작업(`kind=qa`)에 사용하는 입력 데이터 형식."""

    question: str = Field(min_length=1, max_length=10_000)
    retrieval_mode: Literal["hybrid", "bm25"] = "hybrid"
    trace: bool = True


class QuizPayload(StrictContract):
    """퀴즈 생성 작업(`kind=quiz`)에 사용하는 입력 데이터 형식."""

    response: dict[str, object]
    max_questions: int = Field(default=3, ge=1, le=3)


__all__ = [
    "JobCreate",
    "JobKind",
    "JobResponse",
    "JobStatus",
    "QaPayload",
    "QuizPayload",
]
