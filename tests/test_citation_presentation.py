"""Canonical RAG metadata를 바꾸지 않는 사용자용 출처 표시를 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

from src.contracts import ChatCitation
from src.presentation import CitationPresenter, load_citation_presenter


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "document_pipeline" / "data" / "manifest_v3.json"
LABELS_PATH = ROOT / "data" / "presentation" / "citation_labels_ko.json"


def _citation_for(chunk_id: str) -> ChatCitation:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    chunk = next(item for item in manifest["chunks"] if item["chunk_id"] == chunk_id)
    return ChatCitation(
        citation_id="C1",
        document_id=chunk["document_id"],
        chunk_id=chunk["chunk_id"],
        title=chunk["title"],
        publisher=chunk["publisher"],
        section=chunk["section"],
        source_url=chunk["source_url"],
        source_anchor=chunk["source_anchor"],
        document_version=chunk["document_version"],
        published_at=chunk["published_at"],
        updated_at=chunk["updated_at"],
        collected_at=chunk["collected_at"],
        license=chunk["license"],
        quote=chunk["content"],
    )


def test_multicam_citation_uses_compact_korean_three_line_display() -> None:
    presenter = load_citation_presenter(MANIFEST_PATH)
    display = presenter.present(
        _citation_for("rpi-doc-camera-multicam-004"),
        preferred_use_case="smart_farm_monitoring",
    )

    assert display.cli_lines() == (
        "[C1] 다중 카메라 설정",
        "섹션: 소프트웨어 동기화",
        "태그: Raspberry Pi 5 · 카메라 · 스마트팜 모니터링",
    )


def test_general_qa_uses_the_chunk_primary_use_case() -> None:
    presenter = load_citation_presenter(MANIFEST_PATH)
    display = presenter.present(_citation_for("rpi-doc-camera-multicam-004"))

    assert display.tags == ("Raspberry Pi 5", "카메라", "카메라 모니터링")


def test_labels_cover_current_v3_documents_and_filter_enums() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    chunks = manifest["chunks"]

    assert {item["document_id"] for item in chunks} <= set(labels["document_labels"])
    assert {value for item in chunks for value in item["categories"]} <= set(labels["category_labels"])
    assert {value for item in chunks for value in item["use_cases"]} <= set(labels["use_case_labels"])
    assert {value for item in chunks for value in item["tasks"]} <= set(labels["task_labels"])


def test_known_document_uses_document_label_for_unmapped_section() -> None:
    presenter = CitationPresenter(
        labels={"document_labels": {"known-doc": "검수된 문서 제목"}},
        chunks_by_id={},
    )
    citation = ChatCitation(
        citation_id="C8",
        document_id="known-doc",
        chunk_id="known-doc-001",
        title="Official title",
        publisher="Raspberry Pi Ltd",
        section="Parent > Newly added heading",
        source_url="https://www.raspberrypi.com/documentation/",
        source_anchor=None,
        document_version=None,
        published_at=None,
        updated_at=None,
        collected_at="2026-09-10",
        license="CC-BY-SA-4.0",
        quote="Official content.",
    )

    assert presenter.present(citation).section_label == "검수된 문서 제목"


def test_unknown_metadata_falls_back_without_exposing_canonical_id() -> None:
    presenter = CitationPresenter(labels={}, chunks_by_id={})
    citation = ChatCitation(
        citation_id="C9",
        document_id="future-doc",
        chunk_id="future-doc-000",
        title="Future official title",
        publisher="Raspberry Pi Ltd",
        section="One > Two",
        source_url="https://www.raspberrypi.com/documentation/",
        source_anchor=None,
        document_version=None,
        published_at=None,
        updated_at=None,
        collected_at="2026-08-31",
        license="CC-BY-SA-4.0",
        quote="Future official content.",
    )

    display = presenter.present(citation)

    assert display.document_label == "Future official title"
    assert display.section_label == "Two"
    assert "future-doc" not in "\n".join(display.cli_lines())
