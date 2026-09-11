from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BANK_PATH = ROOT / "data" / "products" / "challenge_bank.json"
MANIFEST_PATH = ROOT / "document_pipeline" / "data" / "manifest_v3.json"


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_challenge_bank_questions_and_evidence_match_v3_manifest() -> None:
    bank = load(BANK_PATH)
    manifest = load(MANIFEST_PATH)
    questions = bank["questions"]
    chunks = {chunk["chunk_id"]: chunk for chunk in manifest["chunks"]}

    assert Counter(question["topic"] for question in questions) == {
        "os_installation": 5,
        "remote_access": 5,
    }
    assert len({question["question_id"] for question in questions}) == 10

    for question in questions:
        choices = question["choices"]
        choice_ids = {choice["choice_id"] for choice in choices}
        assert len(choices) == 4
        assert len(choice_ids) == 4
        assert question["correct_choice_id"] in choice_ids
        assert len(question["evidence_ids"]) == len(question["evidence_checksums"])
        for evidence_id, checksum in zip(question["evidence_ids"], question["evidence_checksums"]):
            assert evidence_id in chunks
            assert chunks[evidence_id]["chunk_checksum"] == checksum
            assert chunks[evidence_id]["official_verified"] is True
            assert chunks[evidence_id]["quality_status"] == "approved"
