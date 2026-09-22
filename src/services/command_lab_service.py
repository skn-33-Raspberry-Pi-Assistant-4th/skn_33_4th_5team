"""Catalog-grounded, display-only command lab, independent of the web framework.

No shell, subprocess or model inference is involved in command reconstruction.
The web backend owns authentication and storage of the returned drawer payload.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import shlex
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
UNSAFE = re.compile(r"[\r\n\x00-\x1f\x7f;|&`$<>\\]")
PLACEHOLDER = re.compile(r"<[^<>]+>")
USERNAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,31}")
HOST_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


def _placeholder_fragment(placeholder: str) -> str:
    label = placeholder[1:-1].casefold()
    if label == "username":
        return r"[A-Za-z_][A-Za-z0-9_.-]*"
    if "ip" in label:
        return r"(?:\[[0-9A-Fa-f:.%]+\]|[A-Za-z0-9][A-Za-z0-9.-]*)"
    if label == "port":
        return r"[0-9]{1,5}"
    if label in {"row", "column"}:
        return r"[0-9]+"
    if "ssid" in label:
        return r"[^\r\n]{1,32}"
    if label.endswith(".tga"):
        return r"[^\s]+\.tga"
    return r"[^\s]+"


def _placeholder_pattern(example: str) -> re.Pattern[str]:
    """Keep the documented literal shape while replacing placeholder values."""
    cursor = 0
    fragments: list[str] = []
    for match in PLACEHOLDER.finditer(example):
        fragments.append(re.escape(example[cursor:match.start()]))
        fragments.append(_placeholder_fragment(match.group()))
        cursor = match.end()
    fragments.append(re.escape(example[cursor:]))
    return re.compile("^" + "".join(fragments) + "$")


def _editable_value_matches(part: dict, value: str) -> bool:
    example = part["value"]
    return PLACEHOLDER.search(example) is None or _placeholder_pattern(example).fullmatch(value) is not None


def _placeholder_values(example: str, value: str) -> list[tuple[str, str]] | None:
    """Extract values from a catalog example while preserving its literal shape."""

    cursor = 0
    fragments: list[str] = []
    labels: list[str] = []
    for index, match in enumerate(PLACEHOLDER.finditer(example)):
        fragments.append(re.escape(example[cursor:match.start()]))
        fragments.append(f"(?P<value_{index}>{_placeholder_fragment(match.group())})")
        labels.append(match.group()[1:-1].casefold())
        cursor = match.end()
    fragments.append(re.escape(example[cursor:]))
    matched = re.fullmatch("".join(fragments), value)
    if not matched:
        return None
    return [(label, matched.group(f"value_{index}")) for index, label in enumerate(labels)]


def _host_error(host: str) -> str | None:
    candidate = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        ipaddress.ip_address(candidate)
        return None
    except ValueError:
        pass
    if re.fullmatch(r"[0-9.]+", candidate):
        return "IP 주소는 IPv4 각 숫자가 0~255인 올바른 주소여야 합니다."
    if not 1 <= len(candidate) <= 253 or candidate.endswith("."):
        return "호스트 이름은 1~253자의 올바른 이름이어야 합니다."
    labels = candidate.split(".")
    if any(not HOST_LABEL.fullmatch(label) for label in labels):
        return "호스트 이름은 영문, 숫자, 하이픈으로 구성하고 각 구간의 처음과 끝에는 하이픈을 사용할 수 없습니다."
    return None


def _field_kind(part: dict) -> str:
    labels = {match.group()[1:-1].casefold() for match in PLACEHOLDER.finditer(part["value"])}
    if "ssid" in " ".join(labels):
        return "ssid"
    if any(label.endswith(".tga") for label in labels):
        return "image_path"
    if labels & {"row", "column"}:
        return "coordinate"
    if "port" in labels:
        return "network_endpoint"
    if "username" in labels or any("ip" in label for label in labels):
        return "ssh_target"
    if part["value"] == "learner@raspberrypi.local":
        return "ssh_target"
    return "text"


def _field_label(part: dict) -> str:
    kind = _field_kind(part)
    if kind == "ssh_target":
        return "SSH 대상"
    if kind == "network_endpoint":
        return "네트워크 주소"
    if kind == "ssid":
        return "Wi-Fi SSID"
    if kind == "image_path":
        return "TGA 이미지 경로"
    labels = {match.group()[1:-1].casefold() for match in PLACEHOLDER.finditer(part["value"])}
    if "row" in labels:
        return "키보드 행"
    if "column" in labels:
        return "키보드 열"
    return part.get("label_ko", "입력값")


class CommandLabError(ValueError):
    """A user input or catalog item cannot be used safely and reliably."""


class CommandLabFieldError(CommandLabError):
    """An editable field failed validation and can be identified by the UI."""

    def __init__(self, part_id: str, message: str):
        super().__init__(message)
        self.part_id = part_id


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

    @staticmethod
    def _official_field_validation(part: dict) -> dict:
        return {
            "part_id": part["part_id"],
            "label": _field_label(part),
            "kind": _field_kind(part),
            "status": "valid",
            "changed": False,
            "message": "공식 검수 예제 그대로입니다.",
        }

    @staticmethod
    def _raise_field_error(part: dict, message: str) -> None:
        raise CommandLabFieldError(part["part_id"], f"{_field_label(part)}: {message}")

    def _validate_editable_field(self, part: dict, field: dict, value: str) -> dict:
        """Validate one user value and return a displayable validation state."""

        if value == part["value"]:
            return self._official_field_validation(part)
        if not isinstance(value, str) or not 1 <= len(value) <= 160:
            self._raise_field_error(part, "1~160자로 입력해 주세요.")
        if UNSAFE.search(value):
            self._raise_field_error(part, "셸 연산자, 제어 문자, 줄바꿈은 사용할 수 없습니다.")
        if value != value.strip() or not value.strip():
            self._raise_field_error(part, "앞뒤 공백과 빈 값은 사용할 수 없습니다.")
        if value.startswith("-"):
            self._raise_field_error(part, "추가 명령 옵션으로 해석될 수 있는 '-'로 시작할 수 없습니다.")
        if not re.fullmatch(field["validation_pattern"], value):
            self._raise_field_error(part, "입력 가능한 기본 형식과 일치하지 않습니다.")

        extracted = _placeholder_values(part["value"], value)
        if PLACEHOLDER.search(part["value"]) and extracted is None:
            kind = _field_kind(part)
            if kind == "network_endpoint":
                self._raise_field_error(part, f"주소는 예시 구조와 같이 입력해 주세요: {part['value']}")
            if kind == "ssh_target":
                self._raise_field_error(part, f"사용자명@호스트 구조를 예제와 같이 입력해 주세요: {part['value']}")
            if kind == "ssid":
                self._raise_field_error(part, "SSID는 줄바꿈 없이 입력해 주세요.")
            if kind == "image_path":
                self._raise_field_error(part, "파일 경로는 .tga 확장자로 끝나야 합니다.")
            if kind == "coordinate":
                self._raise_field_error(part, "0 이상의 정수로 입력해 주세요.")
            self._raise_field_error(part, f"예제 구조를 유지해 주세요: {part['value']}")

        if extracted is None and _field_kind(part) == "ssh_target":
            if value.count("@") != 1:
                self._raise_field_error(part, "사용자명@호스트 형식으로 입력해 주세요.")
            username, host = value.rsplit("@", 1)
            if not USERNAME.fullmatch(username):
                self._raise_field_error(part, "사용자명은 영문자 또는 밑줄로 시작하고 영문·숫자·점·밑줄·하이픈만 사용할 수 있습니다.")
            if error := _host_error(host):
                self._raise_field_error(part, error)

        for placeholder, entered in extracted or []:
            if placeholder == "username" and not USERNAME.fullmatch(entered):
                self._raise_field_error(part, "사용자명은 영문자 또는 밑줄로 시작하고 영문·숫자·점·밑줄·하이픈만 사용할 수 있습니다.")
            if "ip" in placeholder:
                if error := _host_error(entered):
                    self._raise_field_error(part, error)
            if placeholder == "port":
                port = int(entered)
                if not 1 <= port <= 65535:
                    self._raise_field_error(part, "포트는 1~65535 범위의 숫자여야 합니다.")
            if "ssid" in placeholder and len(entered.encode("utf-8")) > 32:
                self._raise_field_error(part, "SSID는 UTF-8 기준 32바이트 이하여야 합니다.")
            if placeholder in {"row", "column"} and (not entered.isdigit() or int(entered) < 0):
                self._raise_field_error(part, "0 이상의 정수로 입력해 주세요.")
            if placeholder.endswith(".tga"):
                if not entered.casefold().endswith(".tga"):
                    self._raise_field_error(part, "파일 경로는 .tga 확장자로 끝나야 합니다.")
                if ".." in entered.split("/"):
                    self._raise_field_error(part, "상위 경로를 뜻하는 '..'는 사용할 수 없습니다.")

        return {
            "part_id": part["part_id"],
            "label": _field_label(part),
            "kind": _field_kind(part),
            "status": "warning",
            "changed": True,
            "message": "형식 검사를 통과했습니다. 사용자 변경값이므로 실제 장치에서의 실행 성공은 확인되지 않았습니다.",
        }

    def compose(self, template_id: str, values: dict[str, str] | None = None,
                *, product_id: str | None = None) -> dict:
        item = self._item(template_id)
        values = {} if values is None else values
        fields = {f["part_id"]: f for f in item["editable_fields"]}
        if not isinstance(values, dict) or set(values) - fields.keys():
            raise CommandLabError("고정 구성 요소나 알 수 없는 필드는 수정할 수 없습니다.")
        parts = deepcopy(item["parts"])
        field_validation = []
        for part in parts:
            key = part["part_id"]
            part["changed"] = False
            if not part["editable"]:
                continue
            if key not in values:
                field_validation.append(self._official_field_validation(part))
                continue
            value = values[key]
            validation = self._validate_editable_field(part, fields[key], value)
            field_validation.append(validation)
            part["changed"] = validation["changed"]
            if validation["changed"]:
                if part["value"].startswith('"') and part["value"].endswith('"'):
                    part["value"] = value
                else:
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
        has_changes = any(validation["changed"] for validation in field_validation)
        validation_summary = {
            "status": "warning" if has_changes else "valid",
            "changed": has_changes,
            "message": (
                "사용자 변경값의 형식은 올바릅니다. 실제 장치·계정·네트워크 존재 여부와 실행 성공은 확인되지 않았습니다."
                if has_changes else
                "공식 검수 예제입니다. 명령은 실행되지 않으며 구성과 근거만 확인합니다."
            ),
        }
        result = {"schema_version": "1.0.0", "template_id": template_id,
                  "catalog_version": self.catalog["catalog_version"],
                  "execution_policy": "display_only", "command": command, "parts": parts,
                  "effect_ko": item["effect_ko"], "execution_context": item["execution_context"],
                  "risk_level": item["risk_level"], "risk_notice_ko": item["risk_notice_ko"],
                  "limitations_ko": item["limitations_ko"], "evidence": evidence,
                  "product": product, "values": dict(values),
                  "field_validation": field_validation, "validation_summary": validation_summary}
        return result

    def analyze(self, command: str) -> dict:
        if not isinstance(command, str) or not 1 <= len(command.strip()) <= 2000:
            raise CommandLabError("한 줄 명령어를 입력해 주세요. 쉘 연산자는 지원하지 않습니다.")
        templates = self.list_templates()
        for item in templates:
            if command == item["canonical_command"]:
                return self.compose(item["template_id"])
        if UNSAFE.search(command):
            raise CommandLabError("한 줄 명령어를 입력해 주세요. 쉘 연산자는 지원하지 않습니다.")
        try:
            incoming = shlex.split(command)
        except ValueError as exc:
            raise CommandLabError("따옴표를 확인해 주세요.") from exc
        for item in templates:
            if incoming == shlex.split(item["canonical_command"]):
                return self.compose(item["template_id"])

        matches: list[tuple[int, dict, dict[str, str]]] = []
        for item in templates:
            parts = item["parts"]
            if len(incoming) != len(parts):
                continue
            if not all(
                (_editable_value_matches(part, incoming[index]) if part["editable"] else incoming[index] == shlex.split(part["value"])[0])
                for index, part in enumerate(parts)
            ):
                continue
            values = {
                part["part_id"]: incoming[index]
                for index, part in enumerate(parts)
                if part["editable"]
            }
            specificity = sum(len(PLACEHOLDER.sub("", part["value"])) for part in parts if part["editable"])
            matches.append((specificity, item, values))
        if matches:
            best_specificity = max(match[0] for match in matches)
            best = [match for match in matches if match[0] == best_specificity]
            if len(best) > 1:
                raise CommandLabError("여러 검수 템플릿과 일치합니다. 명령어 목록에서 하나를 선택해 주세요.")
            _, item, values = best[0]
            return self.compose(item["template_id"], values)
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
