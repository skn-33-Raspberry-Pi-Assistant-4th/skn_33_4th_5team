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
    """One idempotent inference request created by the AWS application."""

    job_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    kind: JobKind
    payload: dict[str, object]

    @field_validator("payload")
    @classmethod
    def limit_payload_shape(cls, value: dict[str, object]) -> dict[str, object]:
        if len(value) > 32:
            raise ValueError("payload has too many top-level fields")
        return value


class JobResponse(StrictContract):
    """Public state returned by submit, status, and cancellation endpoints."""

    job_id: str
    kind: JobKind
    status: JobStatus
    result: dict[str, object] | None = None
    error: str | None = None


class QaPayload(StrictContract):
    question: str = Field(min_length=1, max_length=10_000)
    retrieval_mode: Literal["hybrid", "bm25"] = "hybrid"
    trace: bool = True


class QuizPayload(StrictContract):
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
