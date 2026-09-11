from __future__ import annotations

import pytest

from src.services.challenge_service import ChallengeError, ChallengeService


def test_start_response_and_cookie_safe_state_do_not_include_answers() -> None:
    service = ChallengeService()

    started = service.start("os_installation")

    assert set(started["question"]) == {"question_id", "topic", "prompt", "choices"}
    assert len(started["question"]["choices"]) == 4
    assert set(started["state"]) == {"topic", "question_ids", "choice_orders", "current_index", "score"}
    encoded_state = str(started["state"])
    assert "correct_choice_id" not in encoded_state
    assert "rationale_ko" not in encoded_state
    assert "choice_feedback" not in encoded_state


def test_submit_grades_only_the_current_question_and_advances() -> None:
    service = ChallengeService()
    started = service.start("remote_access")
    current = started["question"]

    result = service.submit(
        started["state"], question_id=current["question_id"], choice_id=current["choices"][0]["choice_id"]
    )

    assert result["total"] == 3
    assert result["selected_choice_id"] in {choice["choice_id"] for choice in current["choices"]}
    assert result["rationale_ko"]
    assert result["evidence"]
    assert "chunk_checksum" not in result["evidence"][0]
    assert result["state"]["current_index"] == 1


def test_submit_rejects_a_question_other_than_the_current_one() -> None:
    service = ChallengeService()
    started = service.start("remote_access")
    current = started["question"]

    with pytest.raises(ChallengeError, match="현재 문제"):
        service.submit(started["state"], question_id="not-current", choice_id=current["choices"][0]["choice_id"])
