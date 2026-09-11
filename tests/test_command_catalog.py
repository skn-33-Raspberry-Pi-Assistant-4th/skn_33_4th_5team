from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "products" / "command_catalog.json"
MANIFEST_PATH = ROOT / "document_pipeline" / "data" / "manifest_v3.json"
TOPIC_COUNTS = {
    "os_installation": 10,
    "remote_access": 16,
    "networking": 18,
    "camera": 16,
    "storage": 12,
    "interfaces": 18,
    "system_status": 10,
}
ID_PATTERN = re.compile(
    r"^cmd-(?:os-installation|remote-access|networking|camera|storage|interfaces|system-status)-\d{3}$"
)
UNSUPPORTED = re.compile(r"(?:&&|\||;|&|\$\(|`)")
DESTRUCTIVE = re.compile(r"(?:^|\s)(?:rm|dd|mkfs|shutdown|halt|poweroff)(?:\s|$)|apt\s+(?:remove|purge)")


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_command_catalog_has_one_hundred_safe_display_only_templates() -> None:
    catalog = load(CATALOG_PATH)
    templates = catalog["templates"]

    assert catalog["schema_version"] == "2.0.0"
    assert catalog["execution_policy"] == "display_only"
    assert len(templates) == 100
    assert Counter(item["topic"] for item in templates) == TOPIC_COUNTS
    assert len({item["template_id"] for item in templates}) == 100
    assert len({item["canonical_command"] for item in templates}) == 100

    for item in templates:
        assert ID_PATTERN.fullmatch(item["template_id"])
        assert item["execution_policy"] == "display_only"
        assert item["risk_level"] in {"read_only", "configuration", "system_change"}
        assert item["risk_notice_ko"]
        assert not UNSUPPORTED.search(item["canonical_command"])
        assert not DESTRUCTIVE.search(item["canonical_command"])


def test_command_catalog_parts_and_evidence_match_v3_manifest() -> None:
    catalog = load(CATALOG_PATH)
    manifest = load(MANIFEST_PATH)
    chunks = {chunk["chunk_id"]: chunk for chunk in manifest["chunks"]}

    for item in catalog["templates"]:
        rebuilt = "".join(part["prefix"] + part["value"] for part in item["parts"])
        assert rebuilt == item["canonical_command"]
        editable_parts = {part["part_id"] for part in item["parts"] if part["editable"]}
        editable_fields = {field["part_id"] for field in item["editable_fields"]}
        assert editable_parts == editable_fields
        assert len(item["evidence_ids"]) == len(item["evidence_checksums"])
        for evidence_id, checksum in zip(item["evidence_ids"], item["evidence_checksums"]):
            assert evidence_id in chunks
            assert chunks[evidence_id]["chunk_checksum"] == checksum
            assert chunks[evidence_id]["official_verified"] is True
            assert chunks[evidence_id]["quality_status"] == "approved"
