from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from document_pipeline.ingestion import run_pipeline
from document_pipeline.ingestion.build_manifest import _processing_metadata, chunk_section, sha256
from document_pipeline.ingestion.fetch import REGISTRY_PATH, included_sources
from document_pipeline.ingestion.parse_asciidoc import parse_asciidoc
from document_pipeline.ingestion.validate_foundation import validate_source_registry
from src.rag.adapters import manifest_chunk_to_document_chunk


class FakeE5Tokenizer:
    """Deterministic tokenizer substitute for boundary tests without model downloads."""

    def encode(self, text: str, *, add_special_tokens: bool = True) -> list[int]:
        return list(range(len(text.split()) + (2 if add_special_tokens else 0)))


def test_parser_preserves_anchor_lists_code_admonitions_and_table() -> None:
    source = """[[networking]]
== Networking

[WARNING]
====
Use a secured network.
====

. Open the terminal.
.. Run the command below.

[source,console]
----
$ nmcli dev wifi list
  --rescan yes
----

|===
| Model | Memory
| Raspberry Pi 5 | 8 GB
|===
"""

    section = parse_asciidoc(source, fallback_title="fallback")[0]

    assert section.source_anchor == "networking"
    assert section.heading_path == ("Networking",)
    assert [block.kind for block in section.blocks] == ["admonition", "list", "code", "table"]
    assert section.blocks[0].severity == "WARNING"
    assert section.blocks[1].items[1].level == 2
    assert section.blocks[2].language == "console"
    assert "  --rescan yes" in section.blocks[2].text
    assert section.blocks[3].headers == ("Model", "Memory")
    assert section.blocks[3].rows == (("Raspberry Pi 5", "8 GB"),)


def test_chunking_uses_whole_semantic_blocks_for_overlap() -> None:
    source = """[[ssh]]
== SSH

Use SSH for remote access.

[source,console]
----
$ nmcli dev wifi list
----

Use a secured password.
"""
    section = parse_asciidoc(source, fallback_title="fallback")[0]

    chunks = chunk_section(section, tokenizer=FakeE5Tokenizer(), target_tokens=8, max_tokens=14, overlap_tokens=6)

    assert chunks
    assert all(not chunk.startswith("cli") for chunk in chunks)
    assert any("```console\n$ nmcli dev wifi list\n```" in chunk for chunk in chunks)


def test_media_macros_are_parsed_but_never_become_retrieval_chunks() -> None:
    section = parse_asciidoc(
        """== Setup

Install the operating system first.

image::images/setup.png[Imager setup]

video::CQtliTJ41ZE[youtube,title="Setup video"]
""",
        fallback_title="Setup",
    )[0]

    assert [block.kind for block in section.blocks] == ["paragraph", "image", "video"]
    assert section.blocks[2].label == "youtube"
    chunks = chunk_section(section, tokenizer=FakeE5Tokenizer())
    assert chunks == ["Install the operating system first."]
    assert all("[IMAGE]" not in chunk and "[VIDEO]" not in chunk for chunk in chunks)


def test_manifest_adapter_maps_collected_at_without_dropping_manifest_contract() -> None:
    chunk = manifest_chunk_to_document_chunk(
        {
            "document_id": "rpi-doc-ssh",
            "chunk_id": "rpi-doc-ssh-000",
            "chunk_index": 0,
            "title": "SSH",
            "publisher": "Raspberry Pi Ltd",
            "section": "SSH",
            "content": "Use SSH.",
            "source_url": "https://www.raspberrypi.com/documentation/computers/remote-access.html#ssh",
            "source_anchor": "ssh",
            "language": "en",
            "source_type": "documentation",
            "published_at": None,
            "updated_at": None,
            "collected_at": "2026-08-28",
            "document_version": "a" * 40,
            "license": "CC-BY-SA-4.0",
            "product_models": [],
            "use_cases": ["headless_remote_management"],
            "tasks": ["remote_access"],
            "categories": ["ssh"],
            "os_versions": ["Raspberry Pi OS"],
            "document_checksum": "sha256:" + "a" * 64,
            "chunk_checksum": "sha256:" + "b" * 64,
            "embedding_checksum": "sha256:" + "c" * 64,
            "parser_version": "asciidoc-semantic-2.0.0",
            "official_verified": True,
            "quality_status": "approved",
            "image_url": None,
            "video_url": None,
        }
    )

    assert chunk.retrieved_at == "2026-08-28"
    assert chunk.use_cases == ("headless_remote_management",)
    assert chunk.official_verified is True
    assert chunk.quality_status == "approved"


V2_REGISTRY_PATH = REGISTRY_PATH.with_name("source_registry_v2.csv")
V3_REGISTRY_PATH = REGISTRY_PATH.with_name("source_registry_v3.csv")


def test_processing_metadata_uses_the_selected_source_registry() -> None:
    processing = _processing_metadata(
        registry_path=V3_REGISTRY_PATH,
        tokenizer_name="test-tokenizer",
        tokenizer_revision="test-revision",
        target_tokens=360,
        max_tokens=460,
        overlap_tokens=60,
    )

    assert processing["source_registry_checksum"] == sha256(V3_REGISTRY_PATH.read_bytes())


def test_original_registry_remains_the_nine_document_baseline() -> None:
    assert validate_source_registry() == (17, 9, 8)


def test_recommendation_mvp_v2_registry_has_15_approved_official_documents() -> None:
    total, included, reference_only = validate_source_registry(V2_REGISTRY_PATH)
    sources = {source.source_id: source for source in included_sources(V2_REGISTRY_PATH)}
    original_sources = {source.source_id: source for source in included_sources()}

    assert (total, included, reference_only) == (23, 15, 8)
    assert set(original_sources).issubset(sources)
    assert all(sources[source_id] == source for source_id, source in original_sources.items())
    assert {
        "rpi-doc-power-supplies",
        "rpi-doc-boot-nvme",
        "rpi-doc-external-storage",
        "rpi-doc-keyboard-computers",
        "rpi-doc-raspberry-pi-connect",
        "rpi-doc-interfaces",
    }.issubset(sources)
    assert sources["rpi-doc-boot-nvme"].product_models == ["Raspberry Pi 5"]
    assert sources["rpi-doc-keyboard-computers"].product_models == [
        "Raspberry Pi 500",
        "Raspberry Pi 400",
    ]
    assert sources["rpi-doc-raspberry-pi-connect"].official_verified is True


def test_catalog_to_rag_v3_registry_keeps_v2_and_adds_command_lab_documents() -> None:
    total, included, reference_only = validate_source_registry(V3_REGISTRY_PATH)
    v2_sources = {source.source_id: source for source in included_sources(V2_REGISTRY_PATH)}
    v3_sources = {source.source_id: source for source in included_sources(V3_REGISTRY_PATH)}

    assert (total, included, reference_only) == (31, 23, 8)
    assert set(v2_sources).issubset(v3_sources)
    assert {
        "rpi-doc-camera-multicam",
        "rpi-doc-frequency-management",
        "rpi-doc-getting-started-setting-up",
        "rpi-doc-config-raspi-config",
        "rpi-doc-config-boot-behaviour",
        "rpi-doc-camera-rpicam-options",
        "rpi-doc-camera-streaming",
        "rpi-doc-camera-rpicam-building",
    }.issubset(v3_sources)
    assert v3_sources["rpi-doc-camera-multicam"].product_models == ["Raspberry Pi 5"]


def test_run_pipeline_forwards_custom_registry_to_fetch_and_manifest(
    tmp_path, monkeypatch
) -> None:
    """v3 CLI가 fetch와 manifest 생성에 같은 registry를 넘기는지 회귀 검증한다."""

    registry = tmp_path / "registry.csv"
    raw_root = tmp_path / "raw"
    processed_root = tmp_path / "processed"
    manifest_path = tmp_path / "manifest.json"
    calls: dict[str, dict[str, object]] = {}
    call_order: list[str] = []

    def fake_fetch_sources(**kwargs):
        call_order.append("fetch")
        calls["fetch"] = kwargs
        return {"commit": "a" * 40, "documents": []}

    def fake_build_manifest(**kwargs):
        call_order.append("manifest")
        calls["build"] = kwargs
        return {"chunks": []}

    def fake_build_media_manifest(**kwargs):
        call_order.append("media_manifest")
        calls["media"] = kwargs
        return {"statistics": {"media_items": 0}}

    def fake_build_media_chunk_map(**kwargs):
        call_order.append("media_chunk_map")
        calls["media_chunk_map"] = kwargs
        return {"summary": {"linked_media": 0, "unmatched_media": 0}}

    def fake_reset_index_for_manifest(**kwargs):
        call_order.append("index")
        calls["index"] = kwargs
        return 0

    monkeypatch.setattr(run_pipeline, "fetch_sources", fake_fetch_sources)
    monkeypatch.setattr(run_pipeline, "build_manifest", fake_build_manifest)
    monkeypatch.setattr(run_pipeline, "build_media_manifest", fake_build_media_manifest)
    monkeypatch.setattr(run_pipeline, "build_media_chunk_map", fake_build_media_chunk_map)
    monkeypatch.setattr(run_pipeline, "_reset_index_for_manifest", fake_reset_index_for_manifest)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_pipeline",
            "--source-registry",
            str(registry),
            "--raw-root",
            str(raw_root),
            "--processed-root",
            str(processed_root),
            "--manifest-path",
            str(manifest_path),
        ],
    )

    run_pipeline.main()

    assert calls["fetch"]["registry_path"] == registry
    assert calls["build"]["registry_path"] == registry
    assert calls["build"]["raw_root"] == raw_root
    assert calls["build"]["processed_root"] == processed_root
    assert calls["build"]["output_path"] == manifest_path
    assert calls["media"]["registry_path"] == registry
    assert calls["media"]["raw_root"] == raw_root
    assert calls["media"]["document_manifest_path"] == manifest_path
    assert calls["media_chunk_map"]["document_manifest_path"] == manifest_path
    assert calls["media_chunk_map"]["output_path"] == run_pipeline.V3_MEDIA_CHUNK_MAP_PATH
    assert calls["index"]["manifest_path"] == manifest_path
    assert calls["index"]["media_manifest_path"] == run_pipeline.V3_MEDIA_MANIFEST_PATH
    assert calls["index"]["media_chunk_map_path"] == run_pipeline.V3_MEDIA_CHUNK_MAP_PATH
    assert call_order == ["fetch", "manifest", "media_manifest", "media_chunk_map", "index"]


def test_run_pipeline_reindexes_the_generated_manifest_with_reset(tmp_path, monkeypatch) -> None:
    manifest_path = tmp_path / "manifest.json"
    repository_root = tmp_path / "repository"
    settings = SimpleNamespace(
        manifest_path=manifest_path,
        media_manifest_path=tmp_path / "media-manifest.json",
        media_chunk_map_path=tmp_path / "media-chunk-map.json",
    )
    calls: dict[str, object] = {}

    monkeypatch.setattr(run_pipeline.RagSettings, "from_env", lambda root: settings)

    def fake_index_from_settings(received_settings, **kwargs):
        calls["settings"] = received_settings
        calls.update(kwargs)
        return 17

    monkeypatch.setattr(run_pipeline, "index_from_settings", fake_index_from_settings)

    assert run_pipeline._reset_index_for_manifest(
        manifest_path=manifest_path,
        media_manifest_path=settings.media_manifest_path,
        media_chunk_map_path=settings.media_chunk_map_path,
        repository_root=repository_root,
    ) == 17
    assert calls == {
        "settings": settings,
        "manifest_path": manifest_path,
        "reset": True,
    }


def test_run_pipeline_rejects_rag_settings_that_point_to_other_outputs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        run_pipeline.RagSettings,
        "from_env",
        lambda root: SimpleNamespace(
            manifest_path=tmp_path / "other-manifest.json",
            media_manifest_path=tmp_path / "media-manifest.json",
            media_chunk_map_path=tmp_path / "media-chunk-map.json",
        ),
    )

    with pytest.raises(ValueError, match="DOCUMENT_MANIFEST"):
        run_pipeline._reset_index_for_manifest(
            manifest_path=tmp_path / "manifest.json",
            media_manifest_path=tmp_path / "media-manifest.json",
            media_chunk_map_path=tmp_path / "media-chunk-map.json",
            repository_root=tmp_path,
        )
