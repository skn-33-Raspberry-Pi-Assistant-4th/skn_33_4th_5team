"""Server-side, evidence-checked mini challenge service.

The browser receives only prompts and shuffled choices.  Correct answers and
explanations stay in the reviewed question bank until a submitted choice is
validated by this service.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import secrets
from typing import Any
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
ACTIVE_REVIEW_STATUS = "approved"
QUESTIONS_PER_CHALLENGE = 3


class ChallengeError(ValueError):
    """A challenge request or its reviewed data cannot be used safely."""


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class ChallengeService:
    """Select, grade and explain reviewed questions without exposing answers."""

    def __init__(self, root: Path = ROOT):
        self.bank = _read_json(root / "data/products/challenge_bank.json")
        manifest = _read_json(root / "document_pipeline/data/manifest_v3.json")
        self.chunks = {chunk["chunk_id"]: chunk for chunk in manifest["chunks"]}
        self.questions = {question["question_id"]: question for question in self.bank["questions"]}
        if len(self.questions) != len(self.bank["questions"]):
            raise ChallengeError("중복 문제 ID가 있습니다.")

    def _validate_question(self, question: dict[str, Any]) -> None:
        if question.get("review_status") != ACTIVE_REVIEW_STATUS:
            raise ChallengeError("검수 완료된 문제만 사용할 수 있습니다.")
        choices = question.get("choices", [])
        choice_ids = {choice.get("choice_id") for choice in choices}
        if len(choices) != 4 or len(choice_ids) != 4 or question.get("correct_choice_id") not in choice_ids:
            raise ChallengeError("문제 선택지 계약이 올바르지 않습니다.")
        evidence_ids = question.get("evidence_ids", [])
        checksums = question.get("evidence_checksums", [])
        if not evidence_ids or len(evidence_ids) != len(checksums):
            raise ChallengeError("공식 근거가 없거나 검증 정보가 올바르지 않습니다.")
        for chunk_id, checksum in zip(evidence_ids, checksums, strict=True):
            chunk = self.chunks.get(chunk_id)
            if not chunk or chunk.get("chunk_checksum") != checksum:
                raise ChallengeError("문제 근거가 누락되었거나 변경되었습니다.")
            if chunk.get("official_verified") is not True or chunk.get("quality_status") != ACTIVE_REVIEW_STATUS:
                raise ChallengeError("승인된 공식 근거가 아닙니다.")
            source = urlsplit(chunk["source_url"])
            if source.scheme != "https" or source.hostname not in {"raspberrypi.com", "www.raspberrypi.com"}:
                raise ChallengeError("공식 출처 URL이 아닙니다.")

    def _approved_questions(self, topic: str) -> list[dict[str, Any]]:
        if not isinstance(topic, str) or not topic:
            raise ChallengeError("학습 주제를 선택해 주세요.")
        result = []
        for question in self.questions.values():
            if question.get("topic") != topic or question.get("review_status") != ACTIVE_REVIEW_STATUS:
                continue
            try:
                self._validate_question(question)
            except ChallengeError:
                continue
            result.append(question)
        if len(result) < QUESTIONS_PER_CHALLENGE:
            raise ChallengeError("이 주제의 검수 완료 문제를 준비하지 못했습니다.")
        return result

    def topics(self) -> list[dict[str, Any]]:
        labels = {"os_installation": "OS 설치", "remote_access": "원격 접속·SSH"}
        topics = []
        for topic, label in labels.items():
            count = len(self._approved_questions(topic))
            if count >= QUESTIONS_PER_CHALLENGE:
                topics.append({"id": topic, "label": label, "available_count": count})
        return topics

    def start(self, topic: str) -> dict[str, Any]:
        """Return cookie-safe session state and the first public question."""

        candidates = self._approved_questions(topic)
        selected = secrets.SystemRandom().sample(candidates, QUESTIONS_PER_CHALLENGE)
        state = {
            "topic": topic,
            "question_ids": [question["question_id"] for question in selected],
            "choice_orders": {
                question["question_id"]: secrets.SystemRandom().sample(
                    [choice["choice_id"] for choice in question["choices"]], 4
                )
                for question in selected
            },
            "current_index": 0,
            "score": 0,
        }
        return {"state": state, "question": self.current_question(state)}

    def _question_for_state(self, state: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(state, dict):
            raise ChallengeError("진행 중인 챌린지 정보가 올바르지 않습니다.")
        question_ids = state.get("question_ids")
        current_index = state.get("current_index")
        if (
            not isinstance(question_ids, list)
            or len(question_ids) != QUESTIONS_PER_CHALLENGE
            or len(set(question_ids)) != QUESTIONS_PER_CHALLENGE
            or not isinstance(current_index, int)
            or not 0 <= current_index < QUESTIONS_PER_CHALLENGE
        ):
            raise ChallengeError("진행 중인 챌린지 정보가 올바르지 않습니다.")
        question_id = question_ids[current_index]
        question = self.questions.get(question_id)
        if not question or question.get("topic") != state.get("topic"):
            raise ChallengeError("현재 문제를 확인할 수 없습니다.")
        self._validate_question(question)
        return question

    def _public_question(self, question: dict[str, Any], order: list[str]) -> dict[str, Any]:
        if not isinstance(order, list) or set(order) != {choice["choice_id"] for choice in question["choices"]}:
            raise ChallengeError("선택지 순서 정보가 올바르지 않습니다.")
        choices = {choice["choice_id"]: choice["text"] for choice in question["choices"]}
        return {
            "question_id": question["question_id"],
            "topic": question["topic"],
            "prompt": question["prompt"],
            "choices": [{"choice_id": choice_id, "text": choices[choice_id]} for choice_id in order],
        }

    def current_question(self, state: dict[str, Any]) -> dict[str, Any]:
        question = self._question_for_state(state)
        order = state.get("choice_orders", {}).get(question["question_id"])
        return self._public_question(question, order)

    def submit(self, state: dict[str, Any], *, question_id: str, choice_id: str) -> dict[str, Any]:
        """Grade the current question, then return its explanation and next step."""

        question = self._question_for_state(state)
        if question_id != question["question_id"]:
            raise ChallengeError("현재 문제를 제출해 주세요.")
        known_choices = {choice["choice_id"] for choice in question["choices"]}
        if choice_id not in known_choices:
            raise ChallengeError("제출한 선택지를 확인할 수 없습니다.")
        if choice_id not in state.get("choice_orders", {}).get(question_id, []):
            raise ChallengeError("이번 챌린지에 제시된 선택지를 골라 주세요.")

        correct = choice_id == question["correct_choice_id"]
        next_state = deepcopy(state)
        next_state["score"] = int(next_state.get("score", 0)) + int(correct)
        next_state["current_index"] += 1
        completed = next_state["current_index"] >= QUESTIONS_PER_CHALLENGE
        result = {
            "state": next_state,
            "correct": correct,
            "selected_choice_id": choice_id,
            "correct_choice_id": question["correct_choice_id"],
            "rationale_ko": question["rationale_ko"],
            "choice_feedback": question["choice_feedback"][choice_id],
            "evidence": self._evidence_cards(question),
            "completed": completed,
            "score": next_state["score"],
            "total": QUESTIONS_PER_CHALLENGE,
        }
        if not completed:
            result["next_question"] = self.current_question(next_state)
        return result

    def _evidence_cards(self, question: dict[str, Any]) -> list[dict[str, str]]:
        cards = []
        for chunk_id in question["evidence_ids"]:
            chunk = self.chunks[chunk_id]
            cards.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "title": chunk["title"],
                    "section": chunk["section"],
                    "url": chunk["source_url"],
                }
            )
        return cards
