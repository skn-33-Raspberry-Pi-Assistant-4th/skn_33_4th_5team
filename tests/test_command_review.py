from __future__ import annotations

from copy import deepcopy

from src.services.command_review import (
    CATALOG_PATH,
    LEDGER_PATH,
    APPROVED_REVIEWER_LABEL,
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


def test_ledger_scopes_every_original_draft_and_starts_pending():
    catalog, ledger = load_json(CATALOG_PATH), load_json(LEDGER_PATH)
    original_drafts = {item["template_id"] for item in catalog["templates"] if item["review_status"] == "draft"}

    assert set(ledger["candidate_template_ids"]) == original_drafts
    assert len(original_drafts) == 92
    assert audit_review_ledger(catalog, ledger) == {
        "candidates": 92,
        "pending": 92,
        "ready_to_approve": 0,
        "approved_after_dual_review": 0,
        "held_as_draft": 0,
        "errors": [],
    }


def test_completed_dual_approval_is_the_only_promotion_path():
    catalog, ledger = load_json(CATALOG_PATH), load_json(LEDGER_PATH)
    ledger = deepcopy(ledger)
    template_id = ledger["candidate_template_ids"][0]
    ledger["reviews"][template_id] = _dual_approval()

    audit = audit_review_ledger(catalog, ledger)
    assert audit["ready_to_approve"] == 1
    assert audit["errors"] == []

    synchronized = sync_approved_reviews(catalog, ledger)
    item = next(item for item in synchronized["templates"] if item["template_id"] == template_id)
    assert item["review_status"] == "approved"
    assert item["reviewed_by"] == APPROVED_REVIEWER_LABEL
    assert item["reviewed_at"] == "2026-09-16"
    assert audit_review_ledger(synchronized, ledger, strict_catalog_sync=True)["errors"] == []


def test_candidate_cannot_be_promoted_without_two_reviews():
    catalog, ledger = load_json(CATALOG_PATH), load_json(LEDGER_PATH)
    catalog = deepcopy(catalog)
    template_id = ledger["candidate_template_ids"][0]
    item = next(item for item in catalog["templates"] if item["template_id"] == template_id)
    item["review_status"] = "approved"

    audit = audit_review_ledger(catalog, ledger)
    assert any(template_id in error and "이중 검수 기록 없이 승인" in error for error in audit["errors"])
