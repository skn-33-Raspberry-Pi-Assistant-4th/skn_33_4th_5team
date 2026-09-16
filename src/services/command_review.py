"""Audit and apply the two-person review gate for Command Lab draft templates.

The ledger records human decisions; this module deliberately does not evaluate
whether a command is semantically correct.  It only makes that review process
traceable and prevents an unreviewed item from being promoted accidentally.
"""
from __future__ import annotations

import csv
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from typing import Any, TextIO


ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "data/products/command_catalog.json"
MANIFEST_PATH = ROOT / "document_pipeline/data/manifest_v3.json"
LEDGER_PATH = ROOT / "data/products/command_review_ledger.json"
APPROVED_REVIEWER_LABEL = "B: 양원; C: 나은"
DATA_OWNER_REVIEWER_LABEL = "A: 최지흠"


class CommandReviewError(ValueError):
    """The review ledger does not meet the two-person approval contract."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CommandReviewError(f"JSON을 읽을 수 없습니다: {path}") from exc
    if not isinstance(payload, dict):
        raise CommandReviewError(f"JSON 객체여야 합니다: {path}")
    return payload


def _catalog_templates(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    templates = catalog.get("templates")
    if not isinstance(templates, list):
        raise CommandReviewError("카탈로그 templates가 배열이 아닙니다.")
    mapped = {item.get("template_id"): item for item in templates if isinstance(item, dict)}
    if len(mapped) != len(templates) or None in mapped:
        raise CommandReviewError("카탈로그 template_id가 누락되었거나 중복되었습니다.")
    return mapped


def _require_date(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise CommandReviewError(f"{label}은 YYYY-MM-DD 문자열이어야 합니다.")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise CommandReviewError(f"{label}은 YYYY-MM-DD 형식이어야 합니다.") from exc
    return value


def _review(record: dict[str, Any], reviewer: str, template_id: str) -> dict[str, Any] | None:
    value = record.get(reviewer)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise CommandReviewError(f"{template_id}의 {reviewer} 검수 기록이 객체가 아닙니다.")
    if value.get("verdict") not in {"approve", "revise"}:
        raise CommandReviewError(f"{template_id}의 {reviewer} verdict는 approve 또는 revise여야 합니다.")
    if not isinstance(value.get("reason"), str) or not value["reason"].strip():
        raise CommandReviewError(f"{template_id}의 {reviewer} 검수 사유가 비어 있습니다.")
    _require_date(value.get("reviewed_at"), f"{template_id}의 {reviewer}.reviewed_at")
    return value


def _data_owner_approval(ledger: dict[str, Any], candidate_count: int) -> dict[str, Any] | None:
    """Validate an explicit whole-catalog approval from the data owner.

    This is separate from the B/C dual-review path so the ledger never invents
    individual reviewer decisions that were not actually recorded.
    """
    value = ledger.get("data_owner_approval")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise CommandReviewError("data_owner_approval은 객체여야 합니다.")
    expected = {
        "reviewer_role": "A",
        "reviewer_name": "최지흠",
        "verdict": "approve",
        "scope": "all_candidates",
        "template_count": candidate_count,
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise CommandReviewError(f"data_owner_approval.{key} 값이 검수 계약과 다릅니다.")
    if not isinstance(value.get("reason"), str) or not value["reason"].strip():
        raise CommandReviewError("data_owner_approval.reason이 비어 있습니다.")
    _require_date(value.get("reviewed_at"), "data_owner_approval.reviewed_at")
    return value


def audit_review_ledger(
    catalog: dict[str, Any], ledger: dict[str, Any], *, strict_catalog_sync: bool = False
) -> dict[str, Any]:
    """Return coverage and integrity errors without making catalog changes."""
    templates = _catalog_templates(catalog)
    candidate_ids = ledger.get("candidate_template_ids")
    reviews = ledger.get("reviews")
    reviewers = ledger.get("reviewers")
    errors: list[str] = []
    if ledger.get("schema_version") != "1.0.0":
        errors.append("지원하지 않는 review ledger schema_version입니다.")
    if not isinstance(candidate_ids, list) or not all(isinstance(item, str) for item in candidate_ids):
        errors.append("candidate_template_ids는 문자열 배열이어야 합니다.")
        candidate_ids = []
    if len(candidate_ids) != len(set(candidate_ids)):
        errors.append("candidate_template_ids에 중복 ID가 있습니다.")
    if not isinstance(reviews, dict):
        errors.append("reviews는 객체여야 합니다.")
        reviews = {}
    if reviewers != {"B": "양원", "C": "나은"}:
        errors.append("검수자 계약은 B=양원, C=나은이어야 합니다.")

    candidate_set = set(candidate_ids)
    unknown = sorted(candidate_set - templates.keys())
    if unknown:
        errors.append(f"카탈로그에 없는 검수 대상 ID: {', '.join(unknown)}")
    extra_reviews = sorted(set(reviews) - candidate_set)
    if extra_reviews:
        errors.append(f"검수 대상이 아닌 review 기록: {', '.join(extra_reviews)}")

    try:
        data_owner_approval = _data_owner_approval(ledger, len(candidate_ids))
    except CommandReviewError as exc:
        errors.append(str(exc))
        data_owner_approval = None

    pending = ready = held = approved = data_owner_approved = 0
    for template_id in candidate_ids:
        item = templates.get(template_id)
        if item is None:
            continue
        record = reviews.get(template_id)
        if data_owner_approval is not None:
            if record is not None:
                errors.append(f"{template_id}: 데이터 담당자 일괄 승인과 개별 검수 기록이 중복됩니다.")
                continue
            if item.get("review_status") == "approved":
                if (
                    item.get("reviewed_by") != DATA_OWNER_REVIEWER_LABEL
                    or item.get("reviewed_at") != data_owner_approval["reviewed_at"]
                ):
                    errors.append(f"{template_id}: 카탈로그 데이터 담당자 승인 메타데이터가 원장과 다릅니다.")
                data_owner_approved += 1
            else:
                ready += 1
                if strict_catalog_sync:
                    errors.append(f"{template_id}: 데이터 담당자 승인 완료지만 카탈로그에 아직 반영되지 않았습니다.")
            continue
        if record is None:
            if item.get("review_status") == "approved":
                errors.append(f"{template_id}: 이중 검수 기록 없이 승인되었습니다.")
            pending += 1
            continue
        if not isinstance(record, dict):
            errors.append(f"{template_id}: review 기록이 객체가 아닙니다.")
            continue
        try:
            b_review = _review(record, "B", template_id)
            c_review = _review(record, "C", template_id)
        except CommandReviewError as exc:
            errors.append(str(exc))
            continue
        if b_review is None or c_review is None:
            if item.get("review_status") == "approved":
                errors.append(f"{template_id}: 두 검수자의 판정 없이 승인되었습니다.")
            pending += 1
            continue
        resolution = record.get("resolution")
        if not isinstance(resolution, dict) or resolution.get("status") not in {"approved", "draft"}:
            errors.append(f"{template_id}: 두 판정 후 resolution.status를 기록해야 합니다.")
            continue
        if not isinstance(resolution.get("note"), str) or not resolution["note"].strip():
            errors.append(f"{template_id}: resolution.note가 비어 있습니다.")
            continue
        try:
            resolved_at = _require_date(resolution.get("resolved_at"), f"{template_id}의 resolution.resolved_at")
        except CommandReviewError as exc:
            errors.append(str(exc))
            continue
        both_approve = b_review["verdict"] == c_review["verdict"] == "approve"
        expected = "approved" if both_approve else "draft"
        if resolution["status"] != expected:
            errors.append(f"{template_id}: 두 판정과 resolution.status가 일치하지 않습니다.")
            continue
        if expected == "approved":
            if item.get("review_status") == "approved":
                if item.get("reviewed_by") != APPROVED_REVIEWER_LABEL or item.get("reviewed_at") != resolved_at:
                    errors.append(f"{template_id}: 카탈로그 이중 검수 메타데이터가 resolution과 다릅니다.")
                approved += 1
            else:
                ready += 1
                if strict_catalog_sync:
                    errors.append(f"{template_id}: 승인 준비 완료지만 카탈로그에 아직 반영되지 않았습니다.")
        else:
            held += 1
            if item.get("review_status") != "draft":
                errors.append(f"{template_id}: revise 판정인데 카탈로그에서 공개 상태입니다.")

    return {
        "candidates": len(candidate_ids),
        "pending": pending,
        "ready_to_approve": ready,
        "approved_after_data_owner_review": data_owner_approved,
        "approved_after_dual_review": approved,
        "held_as_draft": held,
        "errors": errors,
    }


def sync_approved_reviews(catalog: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
    """Promote only completed B/C approvals; callers persist the returned catalog."""
    audit = audit_review_ledger(catalog, ledger)
    if audit["errors"]:
        raise CommandReviewError("검수 ledger 오류가 있어 승인 상태를 반영할 수 없습니다.")
    updated = deepcopy(catalog)
    templates = _catalog_templates(updated)
    data_owner_approval = _data_owner_approval(ledger, len(ledger["candidate_template_ids"]))
    if data_owner_approval is not None:
        for template_id in ledger["candidate_template_ids"]:
            item = templates[template_id]
            item["review_status"] = "approved"
            item["reviewed_by"] = DATA_OWNER_REVIEWER_LABEL
            item["reviewed_at"] = data_owner_approval["reviewed_at"]
    for template_id, record in ledger["reviews"].items():
        if record["resolution"]["status"] != "approved":
            continue
        item = templates[template_id]
        item["review_status"] = "approved"
        item["reviewed_by"] = APPROVED_REVIEWER_LABEL
        item["reviewed_at"] = record["resolution"]["resolved_at"]
    return updated


def write_review_sheet(catalog: dict[str, Any], manifest: dict[str, Any], ledger: dict[str, Any], stream: TextIO) -> None:
    """Write the full scoped inventory as CSV for independent offline review."""
    templates = _catalog_templates(catalog)
    chunks = {chunk["chunk_id"]: chunk for chunk in manifest.get("chunks", [])}
    writer = csv.DictWriter(stream, fieldnames=(
        "template_id", "canonical_command", "topic", "risk_level", "evidence_ids", "evidence_urls",
        "A_verdict", "A_reason", "A_reviewed_at",
        "B_verdict", "B_reason", "B_reviewed_at", "C_verdict", "C_reason", "C_reviewed_at",
        "resolution_status", "resolution_note", "resolution_resolved_at",
    ))
    writer.writeheader()
    data_owner_approval = _data_owner_approval(ledger, len(ledger["candidate_template_ids"]))
    for template_id in ledger["candidate_template_ids"]:
        item = templates[template_id]
        record = ledger["reviews"].get(template_id, {})
        b_review, c_review = record.get("B", {}), record.get("C", {})
        resolution = record.get("resolution", {})
        evidence_ids = item["evidence_ids"]
        writer.writerow({
            "template_id": template_id,
            "canonical_command": item["canonical_command"],
            "topic": item["topic"],
            "risk_level": item["risk_level"],
            "evidence_ids": ";".join(evidence_ids),
            "evidence_urls": ";".join(chunks.get(key, {}).get("source_url", "") for key in evidence_ids),
            "A_verdict": data_owner_approval.get("verdict", "") if data_owner_approval else "",
            "A_reason": data_owner_approval.get("reason", "") if data_owner_approval else "",
            "A_reviewed_at": data_owner_approval.get("reviewed_at", "") if data_owner_approval else "",
            "B_verdict": b_review.get("verdict", ""), "B_reason": b_review.get("reason", ""), "B_reviewed_at": b_review.get("reviewed_at", ""),
            "C_verdict": c_review.get("verdict", ""), "C_reason": c_review.get("reason", ""), "C_reviewed_at": c_review.get("reviewed_at", ""),
            "resolution_status": resolution.get("status", ""), "resolution_note": resolution.get("note", ""), "resolution_resolved_at": resolution.get("resolved_at", ""),
        })
