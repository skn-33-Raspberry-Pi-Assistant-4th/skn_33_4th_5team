"""Template filters for cleaning up answer text before display."""
from __future__ import annotations

import re

from django import template

register = template.Library()

# Inline citation markers such as [C1] or [C12] are appended to sentences for
# internal grounding and validation. They should never surface in the UI.
_CITATION_PATTERN = re.compile(r"\s*\[C[1-9][0-9]*\]")


@register.filter
def strip_citations(value: object) -> str:
    """Remove inline [C1]/[C2]/... citation markers from display text."""
    if value is None:
        return ""
    return _CITATION_PATTERN.sub("", str(value))
