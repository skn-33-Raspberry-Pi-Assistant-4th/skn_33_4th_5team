"""Deterministic extraction of exact quote candidates from final Q&A evidence."""

from __future__ import annotations

import re

from src.contracts import QuizEvidence, QuizQuoteCandidate

_LIST_MARKER = re.compile(r"^(?:[-*]|\d+\.)\s+")
_SENTENCES = re.compile(r"(?<=[.!?])\s+")
_MIN_CHARS = 15
_MAX_CHARS = 240
MAX_QUOTE_CANDIDATES_PER_EVIDENCE = 8


def _evenly_spaced_candidates(
    candidates: list[QuizQuoteCandidate],
    *,
    limit: int,
) -> list[QuizQuoteCandidate]:
    """Keep bounded evidence coverage without always discarding later steps.

    Long procedural citations often place relevant instructions near the end.
    Retaining evenly spaced exact candidates keeps the prompt bounded while
    preserving first, middle, and final procedural statements.
    """

    if len(candidates) <= limit:
        return candidates
    if limit == 1:
        return [candidates[0]]
    last_index = len(candidates) - 1
    selected_indexes = [index * last_index // (limit - 1) for index in range(limit)]
    return [candidates[index] for index in selected_indexes]


def extract_quote_candidates(
    evidence: list[QuizEvidence],
    *,
    max_per_evidence: int = MAX_QUOTE_CANDIDATES_PER_EVIDENCE,
) -> list[QuizQuoteCandidate]:
    """Return exact one-line sentence/list-item substrings in validator bounds.

    The function never paraphrases or normalizes source text. Removing a list
    marker only chooses the remaining literal substring, which is still present
    in the original evidence body.
    """

    if max_per_evidence < 1:
        raise ValueError("max_per_evidence must be at least 1")

    candidates: list[QuizQuoteCandidate] = []
    for item in evidence:
        item_candidates: list[QuizQuoteCandidate] = []
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
                item_candidates.append(
                    QuizQuoteCandidate(
                        quote_id=f"{item.citation_id}-Q{position}",
                        evidence_id=item.citation_id,
                        content=quote,
                    )
                )
                position += 1
        candidates.extend(
            _evenly_spaced_candidates(item_candidates, limit=max_per_evidence)
        )
    return candidates


__all__ = ["MAX_QUOTE_CANDIDATES_PER_EVIDENCE", "extract_quote_candidates"]
