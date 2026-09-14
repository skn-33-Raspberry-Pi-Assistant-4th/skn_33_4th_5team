"""Deterministic extraction of exact quote candidates from final Q&A evidence."""

from __future__ import annotations

import re

from src.contracts import QuizEvidence, QuizQuoteCandidate

_LIST_MARKER = re.compile(r"^(?:[-*]|\d+\.)\s+")
_SENTENCES = re.compile(r"(?<=[.!?])\s+")
_MIN_CHARS = 15
_MAX_CHARS = 240


def extract_quote_candidates(evidence: list[QuizEvidence]) -> list[QuizQuoteCandidate]:
    """Return exact one-line sentence/list-item substrings in validator bounds.

    The function never paraphrases or normalizes source text. Removing a list
    marker only chooses the remaining literal substring, which is still present
    in the original evidence body.
    """

    candidates: list[QuizQuoteCandidate] = []
    for item in evidence:
        seen: set[str] = set()
        position = 1
        for raw_line in item.content.splitlines():
            line = _LIST_MARKER.sub("", raw_line.strip())
            if not line or line.startswith("```") or line.endswith(":"):
                continue
            for sentence in _SENTENCES.split(line):
                quote = sentence.strip()
                if quote in seen or not _MIN_CHARS <= len(quote) <= _MAX_CHARS:
                    continue
                seen.add(quote)
                candidates.append(
                    QuizQuoteCandidate(
                        quote_id=f"{item.citation_id}-Q{position}",
                        evidence_id=item.citation_id,
                        content=quote,
                    )
                )
                position += 1
    return candidates


__all__ = ["extract_quote_candidates"]
