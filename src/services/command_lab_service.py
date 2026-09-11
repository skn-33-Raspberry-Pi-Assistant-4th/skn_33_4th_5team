"""Catalog-grounded, display-only command lab, independent of the web framework.

No shell, subprocess or model inference is involved in command reconstruction.
The web backend owns authentication and storage of the returned drawer payload.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shlex
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
UNSAFE = re.compile(r"[\r\n\x00-\x1f\x7f;|&`$<>\\]")


class CommandLabError(ValueError):
    """A user input or catalog item cannot be used safely and reliably."""


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class CommandLabService:
    def __init__(self, root: Path = ROOT):
        self.catalog = read_json(root / "data/products/command_catalog.json")
        manifest = read_json(root / "document_pipeline/data/manifest_v3.json")
        self.chunks = {c["chunk_id"]: c for c in manifest["chunks"]}
        products = read_json(root / "data/products/catalog.json")["products"]
        self.products = {p["product_id"]: p for p in products}
        self.templates = {t["template_id"]: t for t in self.catalog["templates"]}
        if len(self.templates) != len(self.catalog["templates"]):
            raise CommandLabError("중복 명령어 ID가 있습니다.")
        if self.catalog.get("execution_policy") != "display_only":
            raise CommandLabError("실행 정책이 display_only가 아닙니다.")

    def _validate(self, item: dict) -> None:
        if item.get("execution_policy") != "display_only":
            raise CommandLabError("허용되지 않은 실행 정책입니다.")
        parts = item["parts"]
        if len({p["part_id"] for p in parts}) != len(parts):
            raise CommandLabError("중복 구성 요소 ID입니다.")
        if "".join(p["prefix"] + p["value"] for p in parts) != item["canonical_command"]:
            raise CommandLabError("명령어 재조합 결과가 원본과 다릅니다.")
        fields = item["editable_fields"]
        if len({f["part_id"] for f in fields}) != len(fields) or {
            p["part_id"] for p in parts if p["editable"]
        } != {f["part_id"] for f in fields}:
            raise CommandLabError("편집 가능 필드 계약이 다릅니다.")
        ids, sums = item["evidence_ids"], item["evidence_checksums"]
        if not ids or len(ids) != len(sums):
            raise CommandLabError("공식 근거가 없거나 체크섬 수가 다릅니다.")
        for chunk_id, checksum in zip(ids, sums, strict=True):
            c = self.chunks.get(chunk_id)
            if not c or c["chunk_checksum"] != checksum:
                raise CommandLabError(f"근거가 누락되거나 변경되었습니다: {chunk_id}")
            if c.get("official_verified") is not True or c.get("quality_status") != "approved":
                raise CommandLabError(f"승인된 공식 근거가 아닙니다: {chunk_id}")
            url = urlsplit(c["source_url"])
            if url.scheme != "https" or url.hostname not in {"www.raspberrypi.com", "raspberrypi.com"}:
                raise CommandLabError("공식 출처 URL이 아닙니다.")

    def audit(self) -> dict:
        errors = []
        for item in self.templates.values():
            try:
                self._validate(item)
            except CommandLabError as exc:
                errors.append({"template_id": item["template_id"], "error": str(exc)})
        return {"total": len(self.templates), "approved": sum(
            t.get("review_status") == "approved" for t in self.templates.values()
        ), "draft": sum(t.get("review_status") != "approved" for t in self.templates.values()),
            "errors": errors}

    def list_templates(self, *, topic: str | None = None) -> list[dict]:
        result = []
        for item in self.templates.values():
            if item.get("review_status") != "approved" or (topic and item["topic"] != topic):
                continue
            try:
                self._validate(item)
            except CommandLabError:
                continue
            result.append(deepcopy(item))
        return result

    def _item(self, template_id: str) -> dict:
        if not isinstance(template_id, str):
            raise CommandLabError("명령어 ID는 문자열이어야 합니다.")
        item = self.templates.get(template_id)
        if not item or item.get("review_status") != "approved":
            raise CommandLabError("검수 완료된 명령어를 선택해 주세요.")
        self._validate(item)
        return item

    def compose(self, template_id: str, values: dict[str, str] | None = None,
                *, product_id: str | None = None) -> dict:
        item = self._item(template_id)
        values = {} if values is None else values
        fields = {f["part_id"]: f for f in item["editable_fields"]}
        if not isinstance(values, dict) or set(values) - fields.keys():
            raise CommandLabError("고정 구성 요소나 알 수 없는 필드는 수정할 수 없습니다.")
        parts = deepcopy(item["parts"])
        for part in parts:
            key = part["part_id"]
            if key not in values:
                continue
            value = values[key]
            if not isinstance(value, str) or not 1 <= len(value) <= 160 or UNSAFE.search(value):
                raise CommandLabError("입력값은 1~160자로 입력하고 쉘 연산자·줄바꿈은 제외해 주세요.")
            if value != value.strip() or not value.strip() or value.startswith("-"):
                raise CommandLabError("입력값에 빈 값, 앞뒤 공백 또는 추가 옵션을 넣을 수 없습니다.")
            if not re.fullmatch(fields[key]["validation_pattern"], value):
                raise CommandLabError("입력값 형식이 올바르지 않습니다.")
            if part["value"] == "learner@raspberrypi.local" and not re.fullmatch(
                r"[a-zA-Z_][a-zA-Z0-9_.-]*@[a-zA-Z0-9][a-zA-Z0-9.-]*", value
            ):
                raise CommandLabError("SSH 대상은 사용자명@호스트 또는 사용자명@IPv4 형식입니다.")
            part["value"] = shlex.quote(value)
        command = "".join(p["prefix"] + p["value"] for p in parts)
        evidence = [deepcopy(self.chunks[k]) for k in item["evidence_ids"]]
        product = None
        if product_id is not None:
            if not isinstance(product_id, str):
                raise CommandLabError("제품 ID는 문자열이어야 합니다.")
            if product_id not in self.products:
                raise CommandLabError("등록되지 않은 제품입니다.")
            p = self.products[product_id]
            documented = any(p["name"] in c.get("product_models", []) for c in evidence)
            product = {"product_id": p["product_id"], "name": p["name"],
                       "product_url": p["product_url"], "document_scope_match": documented,
                       "notice": "문서의 제품 범위 연결이며 실제 장치에서의 실행 성공을 보장하지 않습니다."}
        result = {"schema_version": "1.0.0", "template_id": template_id,
                  "catalog_version": self.catalog["catalog_version"],
                  "execution_policy": "display_only", "command": command, "parts": parts,
                  "effect_ko": item["effect_ko"], "execution_context": item["execution_context"],
                  "risk_level": item["risk_level"], "risk_notice_ko": item["risk_notice_ko"],
                  "limitations_ko": item["limitations_ko"], "evidence": evidence,
                  "product": product, "values": dict(values)}
        return result

    def analyze(self, command: str) -> dict:
        if not isinstance(command, str) or not 1 <= len(command.strip()) <= 2000 or UNSAFE.search(command):
            raise CommandLabError("한 줄 명령어를 입력해 주세요. 쉘 연산자는 지원하지 않습니다.")
        try:
            incoming = shlex.split(command)
        except ValueError as exc:
            raise CommandLabError("따옴표를 확인해 주세요.") from exc
        for item in self.list_templates():
            if incoming == shlex.split(item["canonical_command"]):
                return self.compose(item["template_id"])
            parts = item["parts"]
            if len(incoming) != len(parts):
                continue
            if all(p["editable"] or incoming[i] == shlex.split(p["value"])[0]
                   for i, p in enumerate(parts)):
                return self.compose(item["template_id"], {
                    p["part_id"]: incoming[i] for i, p in enumerate(parts) if p["editable"]})
        raise CommandLabError("검수된 템플릿과 일치하지 않습니다. 명령어 목록에서 선택해 주세요.")

    def drawer_payload(self, template_id: str, values: dict[str, str] | None = None,
                       *, product_id: str | None = None) -> dict:
        result = self.compose(template_id, values, product_id=product_id)
        return {"schema_version": "1.0.0", "kind": "command_lab",
                "template_id": template_id, "catalog_version": result["catalog_version"],
                "values": result["values"], "product_id": product_id,
                "command_snapshot": result["command"],
                "command_checksum": "sha256:" + hashlib.sha256(result["command"].encode()).hexdigest(),
                "evidence_ids": [c["chunk_id"] for c in result["evidence"]],
                "evidence_checksums": [c["chunk_checksum"] for c in result["evidence"]]}

    def qa_question(self, template_id: str, values: dict[str, str] | None = None,
                    *, product_id: str | None = None) -> str:
        result = self.compose(template_id, values, product_id=product_id)
        model = result["product"]["name"] if result["product"] else "Raspberry Pi"
        return f"{model}에서 {result['command']} 명령의 사용 조건과 주의사항을 공식 문서로 설명해 주세요."

    def restore_drawer(self, saved: dict) -> dict:
        """Revalidate E-owned saved data before displaying it after a data update."""
        if not isinstance(saved, dict) or saved.get("schema_version") != "1.0.0" or saved.get("kind") != "command_lab":
            raise CommandLabError("지원하지 않는 서랍 데이터입니다.")
        current = self.drawer_payload(saved.get("template_id"), saved.get("values"),
                                      product_id=saved.get("product_id"))
        for key in ("catalog_version", "command_checksum", "command_snapshot", "evidence_ids", "evidence_checksums"):
            if saved.get(key) != current[key]:
                raise CommandLabError("저장 이후 명령 또는 근거가 변경되었습니다. 실험실에서 다시 확인해 주세요.")
        return self.compose(saved["template_id"], saved.get("values"), product_id=saved.get("product_id"))
