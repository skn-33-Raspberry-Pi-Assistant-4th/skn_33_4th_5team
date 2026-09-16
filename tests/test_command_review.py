from __future__ import annotations

from copy import deepcopy

from src.services.command_review import (
    APPROVED_REVIEWER_LABEL,
    CATALOG_PATH,
    DATA_OWNER_REVIEWER_LABEL,
    LEDGER_PATH,
    audit_review_ledger,
    load_json,
    sync_approved_reviews,
)


def _dual_approval(reviewed_at: str = "2026-09-16") -> dict:
    return {
        "B": {"verdict": "approve", "reason": "공식 근거와 명령 구조를 확인했습니다.", "reviewed_at": reviewed_at},
        "C": {"verdict": "approve", "reason": "학습 설명과 위험 안내를 확인했습니다.", "reviewed_at": reviewed_at},
        "resolution": {"status": "approved", "note": "B/C 독립 검수 모두 통과", "resolved_at": reviewed_at},
    }


def _reset_candidates_to_draft(catalog: dict, ledger: dict) -> dict:
    updated = deepcopy(catalog)
    candidates = set(ledger["candidate_template_ids"])
    for item in updated["templates"]:
        if item["template_id"] in candidates:
            item["review_status"] = "draft"
            item["reviewed_by"] = None
            item["reviewed_at"] = None
    return updated


def test_data_owner_approval_covers_every_original_candidate():
    catalog, ledger = load_json(CATALOG_PATH), load_json(LEDGER_PATH)

    assert len(ledger["candidate_template_ids"]) == 92
    assert audit_review_ledger(catalog, ledger, strict_catalog_sync=True) == {
        "candidates": 92,
        "pending": 0,
        "ready_to_approve": 0,
        "approved_after_data_owner_review": 92,
        "approved_after_dual_review": 0,
        "held_as_draft": 0,
        "errors": [],
    }
    candidates = set(ledger["candidate_template_ids"])
    approved = [item for item in catalog["templates"] if item["template_id"] in candidates]
    assert all(item["review_status"] == "approved" for item in approved)
    assert all(item["reviewed_by"] == DATA_OWNER_REVIEWER_LABEL for item in approved)
    assert all(item["reviewed_at"] == "2026-09-16" for item in approved)


def test_data_owner_approval_count_must_match_fixed_scope():
    catalog, ledger = load_json(CATALOG_PATH), deepcopy(load_json(LEDGER_PATH))
    ledger["data_owner_approval"]["template_count"] = 91

    audit = audit_review_ledger(catalog, ledger)
    assert any("template_count" in error for error in audit["errors"])


def test_dual_approval_remains_supported_for_individual_review():
    catalog, ledger = load_json(CATALOG_PATH), deepcopy(load_json(LEDGER_PATH))
    catalog = _reset_candidates_to_draft(catalog, ledger)
    ledger.pop("data_owner_approval")
    template_id = ledger["candidate_template_ids"][0]
    ledger["reviews"][template_id] = _dual_approval()

    audit = audit_review_ledger(catalog, ledger)
    assert audit["pending"] == 91
    assert audit["ready_to_approve"] == 1
    assert audit["errors"] == []

    synchronized = sync_approved_reviews(catalog, ledger)
    item = next(item for item in synchronized["templates"] if item["template_id"] == template_id)
    assert item["review_status"] == "approved"
    assert item["reviewed_by"] == APPROVED_REVIEWER_LABEL
    assert item["reviewed_at"] == "2026-09-16"


def test_candidate_cannot_remain_public_without_recorded_approval():
    catalog, ledger = load_json(CATALOG_PATH), deepcopy(load_json(LEDGER_PATH))
    ledger.pop("data_owner_approval")

    audit = audit_review_ledger(catalog, ledger)
    assert any("이중 검수 기록 없이 승인" in error for error in audit["errors"])
