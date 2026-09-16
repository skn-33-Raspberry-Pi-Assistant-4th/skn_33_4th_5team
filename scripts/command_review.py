"""Operate the tracked two-person review ledger for Command Lab drafts."""
from __future__ import annotations

import argparse
import json
import sys

from src.services.command_review import (
    CATALOG_PATH,
    LEDGER_PATH,
    MANIFEST_PATH,
    CommandReviewError,
    audit_review_ledger,
    load_json,
    sync_approved_reviews,
    write_review_sheet,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Command Lab draft two-person review gate")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--audit", action="store_true", help="print review coverage and integrity errors")
    group.add_argument("--export-review-sheet", action="store_true", help="write the full CSV review sheet to stdout")
    group.add_argument("--sync-approved", action="store_true", help="promote completed dual approvals into the catalog")
    args = parser.parse_args(argv)
    try:
        catalog, ledger = load_json(CATALOG_PATH), load_json(LEDGER_PATH)
        if args.export_review_sheet:
            write_review_sheet(catalog, load_json(MANIFEST_PATH), ledger, sys.stdout)
            return 0
        audit = audit_review_ledger(catalog, ledger)
        if args.audit:
            print(json.dumps(audit, ensure_ascii=False, indent=2))
            return 1 if audit["errors"] else 0
        if audit["errors"]:
            raise CommandReviewError("ledger 오류가 있어 catalog 동기화를 중단했습니다.")
        if audit["ready_to_approve"] == 0:
            print("no completed dual approvals to synchronize")
            return 0
        CATALOG_PATH.write_text(json.dumps(sync_approved_reviews(catalog, ledger), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("completed dual approvals were synchronized into command_catalog.json")
        return 0
    except CommandReviewError as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
