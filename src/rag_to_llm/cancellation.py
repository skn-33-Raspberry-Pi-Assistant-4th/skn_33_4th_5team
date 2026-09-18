"""Cooperative cancellation for optional structured Qwen generation."""

from __future__ import annotations

from collections.abc import Callable


class GenerationCancelled(Exception):
    """The caller cancelled an in-progress structured generation."""


def raise_if_cancelled(cancel_requested: Callable[[], bool] | None) -> None:
    if cancel_requested is not None and cancel_requested():
        raise GenerationCancelled("생성이 취소됐습니다.")


def call_cancellable(function, *args, cancel_requested=None, **kwargs):
    """Preserve existing callers while forwarding an explicitly supplied callback."""

    raise_if_cancelled(cancel_requested)
    if cancel_requested is not None:
        kwargs["cancel_requested"] = cancel_requested
    result = function(*args, **kwargs)
    raise_if_cancelled(cancel_requested)
    return result


__all__ = ["GenerationCancelled", "call_cancellable", "raise_if_cancelled"]
