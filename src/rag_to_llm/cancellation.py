"""Cooperative cancellation for optional structured Qwen generation."""

from __future__ import annotations

from collections.abc import Callable


class GenerationCancelled(Exception):
    """The caller cancelled an in-progress structured generation."""


def raise_if_cancelled(cancel_requested: Callable[[], bool] | None) -> None:
    if cancel_requested is not None and cancel_requested():
        raise GenerationCancelled("요약 생성이 취소됐습니다.")


__all__ = ["GenerationCancelled", "raise_if_cancelled"]
