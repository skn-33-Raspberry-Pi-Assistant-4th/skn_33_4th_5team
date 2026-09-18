#!/usr/bin/env python3
"""Fail fast when an AWS or RunPod deployment bundle is incomplete."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


EXPECTED_CHUNKS = 381
EXPECTED_DOCUMENTS = 23
EXPECTED_COMMANDS = 100


class VerificationError(RuntimeError):
    """배포 자산 검증이 실패했음을 나타낸다."""

    pass


def _read_json(path: Path) -> dict[str, Any]:
    """지정한 JSON 파일을 읽고 객체 형태인지 검증한다."""

    if not path.is_file():
        raise VerificationError(f"missing file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    """파일 내용을 기준으로 SHA-256 체크섬을 계산한다."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_nonempty(path: Path) -> None:
    """필수 파일이 존재하고 비어 있지 않은지 확인한다."""

    if not path.is_file() or path.stat().st_size == 0:
        raise VerificationError(f"missing or empty file: {path}")


def _require_text(path: Path, expected: str) -> None:
    """파일이 존재하고 지정한 문자열을 포함하는지 확인한다."""

    _require_nonempty(path)
    if expected not in path.read_text(encoding="utf-8"):
        raise VerificationError(f"{path} must contain: {expected}")


def verify_runpod(project_root: Path, adapter_path: Path | None, *, skip_adapter: bool) -> dict[str, Any]:
    """RunPod Django 추론 API와 GPU 추론 자산이 배포 가능한 상태인지 검증한다."""

    _require_text(project_root / "Dockerfile.runpod", "EXPOSE 8000")
    _require_text(project_root / "Dockerfile.runpod", 'CMD ["python", "-m", "src.runpod_api"]')
    _require_text(project_root / "requirements-gpu.txt", "-r requirements.txt")
    _require_text(project_root / "requirements.txt", "Django>=5.1,<6")
    _require_text(project_root / "requirements.txt", "gunicorn>=23,<24")
    _require_text(project_root / "src/runpod_api/__main__.py", 'ROOT_URLCONF="src.runpod_api.urls"')
    _require_text(project_root / "src/runpod_api/urls.py", 'path("v1/jobs", app.submit')
    manifest_path = project_root / "document_pipeline/data/manifest_v3.json"
    manifest = _read_json(manifest_path)
    chunks = manifest.get("chunks")
    if not isinstance(chunks, list) or len(chunks) != EXPECTED_CHUNKS:
        raise VerificationError(f"manifest must contain {EXPECTED_CHUNKS} chunks")
    document_ids = {item.get("document_id") for item in chunks if isinstance(item, dict)}
    if None in document_ids or len(document_ids) != EXPECTED_DOCUMENTS:
        raise VerificationError(f"manifest must contain {EXPECTED_DOCUMENTS} unique documents")

    index_root = project_root / "data/indexed/chroma_official_v3"
    index_meta = _read_json(index_root / "picare-index.json")
    if index_meta.get("indexed_chunk_count") != len(chunks):
        raise VerificationError("index and manifest chunk counts differ")
    manifest_sha = _sha256(manifest_path)
    if index_meta.get("manifest_checksum") != f"sha256:{manifest_sha}":
        raise VerificationError("index was not built from this manifest")
    _require_nonempty(index_root / "chroma.sqlite3")

    catalog = _read_json(project_root / "data/products/catalog.json")
    products = catalog.get("products")
    if not isinstance(products, list) or not products:
        raise VerificationError("product catalog has no products")
    _read_json(project_root / "document_pipeline/data/media_manifest_v3.json")
    _read_json(project_root / "document_pipeline/data/media_chunk_map_v3.json")

    adapter_report: dict[str, Any] = {"checked": not skip_adapter}
    if not skip_adapter:
        if adapter_path is None:
            raise VerificationError("LoRA adapter path is required")
        _require_nonempty(adapter_path / "adapter_config.json")
        weights = sorted(adapter_path.glob("*.safetensors"))
        if not weights or any(path.stat().st_size == 0 for path in weights):
            raise VerificationError(f"adapter weights are missing: {adapter_path}")
        adapter_report.update({
            "path": str(adapter_path.resolve()),
            "config_sha256": _sha256(adapter_path / "adapter_config.json"),
            "weight_files": [path.name for path in weights],
        })

    return {
        "manifest_sha256": manifest_sha,
        "documents": len(document_ids),
        "chunks": len(chunks),
        "indexed_chunks": index_meta["indexed_chunk_count"],
        "products": len(products),
        "api_port": 8000,
        "adapter": adapter_report,
    }


def verify_aws(project_root: Path) -> dict[str, Any]:
    """AWS 웹 배포에 필요한 카탈로그와 실행 파일을 검증한다."""

    command_catalog = _read_json(project_root / "data/products/command_catalog.json")
    templates = command_catalog.get("templates")
    if not isinstance(templates, list) or len(templates) != EXPECTED_COMMANDS:
        raise VerificationError(f"command catalog must contain {EXPECTED_COMMANDS} templates")
    if any(item.get("review_status") != "approved" for item in templates if isinstance(item, dict)):
        raise VerificationError("command catalog contains an unapproved template")
    _require_nonempty(project_root / "web_app/manage.py")
    _require_nonempty(project_root / "web_app/picare_web/wsgi.py")
    _require_nonempty(project_root / "Dockerfile.aws")
    _require_nonempty(project_root / "requirements-web.txt")
    _require_nonempty(project_root / "deploy/aws-entrypoint.sh")
    _require_nonempty(project_root / "deploy/aws.env.example")
    return {
        "command_templates": len(templates),
        "command_catalog_sha256": _sha256(project_root / "data/products/command_catalog.json"),
    }


def verify(
    project_root: Path,
    *,
    target: str,
    adapter_path: Path | None = None,
    skip_adapter: bool = False,
) -> dict[str, Any]:
    """선택한 배포 대상의 자산을 검증하고 요약 보고서를 반환한다."""

    root = project_root.resolve()
    report: dict[str, Any] = {"ok": True, "project_root": str(root), "target": target}
    if target in {"all", "runpod"}:
        report["runpod"] = verify_runpod(root, adapter_path, skip_adapter=skip_adapter)
    if target in {"all", "aws"}:
        report["aws"] = verify_aws(root)
    return report


def main() -> int:
    """명령행 인자를 읽어 배포 자산 검증을 실행하고 종료 코드를 반환한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--target", choices=("all", "runpod", "aws"), default="all")
    parser.add_argument(
        "--adapter-path",
        type=Path,
        default=Path(os.environ.get("LORA_ADAPTER_PATH") or os.environ["RECOMMENDATION_ADAPTER_PATH"])
        if os.environ.get("LORA_ADAPTER_PATH") or os.environ.get("RECOMMENDATION_ADAPTER_PATH")
        else None,
    )
    parser.add_argument(
        "--skip-adapter",
        action="store_true",
        help="Only for CPU CI/AWS checks; production RunPod verification must include the adapter.",
    )
    args = parser.parse_args()
    try:
        report = verify(
            args.project_root,
            target=args.target,
            adapter_path=args.adapter_path,
            skip_adapter=args.skip_adapter,
        )
    except VerificationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
