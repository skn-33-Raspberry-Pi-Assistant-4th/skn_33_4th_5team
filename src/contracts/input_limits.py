"""Shared text limits for UI and service entry points (Unicode characters)."""

MIN_INPUT_CHARS = 1
MAX_INPUT_CHARS = 10_000
INPUT_LENGTH_HINT = "최소 1자 / 최대 10,000자 · 앞뒤 공백 제외"


def validate_input_text(value: str) -> str:
    text = value.strip()
    if not MIN_INPUT_CHARS <= len(text) <= MAX_INPUT_CHARS:
        raise ValueError(INPUT_LENGTH_HINT)
    return text
