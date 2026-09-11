import hashlib
import json
import sys
import types
from pathlib import Path

import pytest

from src.contracts.retrieval_text import build_e5_passage
from src.rag import (
    DenseRetrievalError,
    DocumentChunk,
    HybridRetriever,
    RagFilters,
    RagSettings,
    RagSettingsError,
    RetrievalDecision,
    build_chroma_index,
    evaluate_rankings,
    rrf_fuse,
)
from src.rag import demo

from src.contracts.retrieval_text import build_e5_passage
from src.rag.chroma_metadata import chroma_where, chunk_to_chroma_metadata, tag_flag_key
from src.rag.demo import DEMO_QUERIES, create_parser, prompt_for_query, select_query

def make_chunk(chunk_id: str, content: str, use_cases: tuple[str, ...]) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id="doc-1",
        title="Official Raspberry Pi documentation",
        section="Test section",
        content=content,
        source_url="https://www.raspberrypi.com/documentation/",
        retrieved_at="2026-08-27",
        document_version="test",
        license="CC BY-SA 4.0",
        use_cases=use_cases,
        official_verified=True,
        quality_status="approved",
        embedding_checksum="sha256:" + "e" * 64,
    )


def test_rrf_rewards_a_chunk_returned_by_both_rankers() -> None:
    assert rrf_fuse([["a", "b"], ["b", "c"]])[0] == "b"


def test_metadata_filter_is_applied_before_bm25_ranking() -> None:
    retriever = HybridRetriever(
        [
            make_chunk("camera", "camera cable connector", ("camera",)),
            make_chunk("learn", "learning coding", ("learning",)),
            make_chunk("server", "server storage", ("server",)),
        ]
    )
    results = retriever.search("camera", RagFilters(use_cases=("camera",)))
    assert [result.chunk_id for result in results] == ["camera"]
    assert results[0].source_url.startswith("https://www.raspberrypi.com/")


def test_unapproved_chunk_is_excluded_from_bm25_results() -> None:
    approved = make_chunk("approved", "camera connector setup", ("camera",))
    pending = DocumentChunk(
        **{
            **approved.__dict__,
            "chunk_id": "pending",
            "content": "unrelated pending-review installation note",
            "quality_status": "needs_review",
        }
    )
    unrelated = DocumentChunk(
        **{**approved.__dict__, "chunk_id": "unrelated", "content": "boot storage network"}
    )
    retriever = HybridRetriever([approved, pending, unrelated])

    results = retriever.search("camera connector", RagFilters())

    assert [result.chunk_id for result in results] == ["approved"]


def test_document_id_filter_limits_bm25_candidates_to_catalog_evidence() -> None:
    first = make_chunk("pi5", "server storage setup", ("server",))
    second = DocumentChunk(**{**first.__dict__, "chunk_id": "zero", "document_id": "doc-zero"})
    second = DocumentChunk(**{**second.__dict__, "content": "camera connector setup", "use_cases": ("camera",)})
    first = DocumentChunk(**{**first.__dict__, "document_id": "doc-pi5"})
    third = DocumentChunk(**{**first.__dict__, "chunk_id": "four", "document_id": "doc-pi4"})
    retriever = HybridRetriever([first, second, third])

    results = retriever.search("camera", RagFilters(document_ids=("doc-zero",)))

    assert [result.chunk_id for result in results] == ["zero"]


def test_strict_product_filter_rejects_untagged_and_other_product_chunks() -> None:
    base = make_chunk("untagged", "generic connector setup", ("camera",))
    pi5 = DocumentChunk(
        **{
            **base.__dict__,
            "chunk_id": "pi5",
            "content": "camera connector setup",
            "product_models": ("Raspberry Pi 5",),
        }
    )
    pico = DocumentChunk(
        **{**base.__dict__, "chunk_id": "pico", "product_models": ("Raspberry Pi Pico",)}
    )
    retriever = HybridRetriever([base, pi5, pico])

    results = retriever.search(
        "camera",
        RagFilters(product_models=("Raspberry Pi 5",), strict_product_match=True),
    )

    assert [result.chunk_id for result in results] == ["pi5"]


def test_official_filter_rejects_unapproved_bm25_chunks() -> None:
    approved = make_chunk("approved", "camera connector", ("camera",))
    unreviewed = DocumentChunk(
        **{**approved.__dict__, "chunk_id": "unreviewed", "quality_status": "unreviewed"}
    )
    unrelated = [
        make_chunk(f"other-{index}", f"unrelated topic {index}", ("server",))
        for index in range(3)
    ]
    retriever = HybridRetriever([approved, unreviewed, *unrelated])

    assert [result.chunk_id for result in retriever.search("camera")] == ["approved"]


def test_evaluation_reports_hit_and_mrr() -> None:
    report = evaluate_rankings({"q1": ["x", "a"]}, {"q1": {"a"}}, k=2)
    assert report.hit_at_k == 1.0
    assert report.mrr == 0.5


def test_settings_reads_dotenv_and_resolves_project_relative_paths(tmp_path, monkeypatch) -> None:
    manifest = tmp_path / "data" / "manifest.json"
    manifest.parent.mkdir()
    manifest.write_text('{"chunks": []}', encoding="utf-8")
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "DOCUMENT_MANIFEST=data/manifest.json",
                "CHROMA_PATH=data/indexed/chroma",
                "CHROMA_COLLECTION_NAME=test_collection",
                "E5_MODEL_NAME=intfloat/multilingual-e5-base",
                "TOP_K=3",
                "MEDIA_CHUNK_MAP=document_pipeline/data/media_chunk_map_v3.json",
            ]
        ),
        encoding="utf-8",
    )
    for name in ("DOCUMENT_MANIFEST", "CHROMA_PATH", "CHROMA_COLLECTION_NAME", "E5_MODEL_NAME", "TOP_K",
                 "MEDIA_MANIFEST", "MEDIA_CHUNK_MAP", "DENSE_MAX_DISTANCE"):
        monkeypatch.delenv(name, raising=False)

    settings = RagSettings.from_env(tmp_path)

    assert settings.manifest_path == manifest
    assert settings.chroma_path == tmp_path / "data" / "indexed" / "chroma"
    assert settings.chroma_collection_name == "test_collection"
    assert settings.top_k == 3
    assert settings.dense_max_distance == 0.48
    assert settings.media_chunk_map_path == tmp_path / "document_pipeline" / "data" / "media_chunk_map_v3.json"


def test_settings_rejects_invalid_top_k(tmp_path, monkeypatch) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"chunks": []}', encoding="utf-8")
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "DOCUMENT_MANIFEST=manifest.json",
                "CHROMA_PATH=data/chroma",
                "CHROMA_COLLECTION_NAME=test_collection",
                "E5_MODEL_NAME=intfloat/multilingual-e5-base",
                "TOP_K=0",
            ]
        ),
        encoding="utf-8",
    )
    for name in ("DOCUMENT_MANIFEST", "CHROMA_PATH", "CHROMA_COLLECTION_NAME", "E5_MODEL_NAME", "TOP_K"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RagSettingsError, match="TOP_K"):
        RagSettings.from_env(tmp_path)


def test_settings_rejects_invalid_dense_distance(tmp_path, monkeypatch) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"chunks": []}', encoding="utf-8")
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "DOCUMENT_MANIFEST=manifest.json",
                "CHROMA_PATH=data/chroma",
                "CHROMA_COLLECTION_NAME=test_collection",
                "E5_MODEL_NAME=intfloat/multilingual-e5-base",
                "TOP_K=3",
                "DENSE_MAX_DISTANCE=2",
            ]
        ),
        encoding="utf-8",
    )
    for name in (
        "DOCUMENT_MANIFEST",
        "CHROMA_PATH",
        "CHROMA_COLLECTION_NAME",
        "E5_MODEL_NAME",
        "TOP_K",
        "DENSE_MAX_DISTANCE",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RagSettingsError, match="DENSE_MAX_DISTANCE"):
        RagSettings.from_env(tmp_path)


def test_bm25_all_zero_returns_insufficient_evidence_and_search_stays_compatible() -> None:
    retriever = HybridRetriever([make_chunk("camera", "camera setup", ("camera",))])

    decision = retriever.search_with_decision("스마트팜을 만들고 싶어요")

    assert isinstance(decision, RetrievalDecision)
    assert decision.status == "insufficient_evidence"
    assert decision.reason == "bm25_all_zero"
    assert decision.results == ()
    assert retriever.search("스마트팜을 만들고 싶어요") == []


def _mock_dense_response(monkeypatch, response: dict[str, list[list[object]]]) -> None:
    class FakeCollection:
        def query(self, **kwargs: object) -> dict[str, list[list[object]]]:
            return response

    class FakeClient:
        def get_collection(self, name: str) -> FakeCollection:
            assert name == "rpi_official"
            return FakeCollection()

    class FakeSentenceTransformer:
        def __init__(self, name: str) -> None:
            assert name == "test-e5"

        def encode(self, texts: list[str], normalize_embeddings: bool) -> list[list[float]]:
            assert normalize_embeddings is True
            return [[0.1, 0.2]]

    monkeypatch.setitem(sys.modules, "chromadb", types.SimpleNamespace(PersistentClient=lambda path: FakeClient()))
    monkeypatch.setitem(
        sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer)
    )


def test_dense_distance_over_threshold_returns_insufficient_evidence(monkeypatch) -> None:
    _mock_dense_response(monkeypatch, {"ids": [["camera"]], "distances": [[0.49]]})
    retriever = HybridRetriever(
        [make_chunk("camera", "camera setup", ("camera",))],
        chroma_path="test-chroma",
        embedding_model_name="test-e5",
        dense_max_distance=0.48,
    )

    decision = retriever.search_with_decision("스마트팜을 만들고 싶어요")

    assert decision.status == "insufficient_evidence"
    assert decision.reason == "bm25_all_zero_and_dense_below_threshold"


def test_hybrid_returns_dense_result_when_bm25_is_zero(monkeypatch) -> None:
    _mock_dense_response(monkeypatch, {"ids": [["camera"]], "distances": [[0.20]]})
    retriever = HybridRetriever(
        [make_chunk("camera", "camera setup", ("camera",))],
        chroma_path="test-chroma",
        embedding_model_name="test-e5",
    )

    decision = retriever.search_with_decision("카메라를 연결하고 싶어요")

    assert decision.status == "retrieved"
    assert [result.chunk_id for result in decision.results] == ["camera"]


def test_hybrid_keeps_bm25_result_when_dense_is_below_threshold(monkeypatch) -> None:
    _mock_dense_response(monkeypatch, {"ids": [["camera"]], "distances": [[0.90]]})
    retriever = HybridRetriever(
        [
            make_chunk("camera", "camera setup", ("camera",)),
            make_chunk("learn", "learning coding", ("learning",)),
            make_chunk("server", "server storage", ("server",)),
        ],
        chroma_path="test-chroma",
        embedding_model_name="test-e5",
    )

    decision = retriever.search_with_decision("camera")

    assert decision.status == "retrieved"
    assert [result.chunk_id for result in decision.results] == ["camera"]


def test_demo_parser_has_no_fixed_filter_and_accepts_optional_use_case() -> None:
    default_args = create_parser().parse_args([])
    filtered_args = create_parser().parse_args(["--query", "카메라", "--use-case", "camera"])

    assert default_args.use_cases is None
    assert filtered_args.query == "카메라"
    assert filtered_args.use_cases == ["camera"]


def test_demo_uses_a_random_example_query_only_when_no_query_is_provided(monkeypatch) -> None:
    monkeypatch.setattr(demo.random, "choice", lambda values: values[-1])

    assert select_query(None) == DEMO_QUERIES[-1]
    assert select_query("직접 입력한 질문") == "직접 입력한 질문"


def test_demo_console_input_returns_text_or_none_for_empty_input(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _: "  SSH를 활성화하려면?  ")
    assert prompt_for_query() == "SSH를 활성화하려면?"

    monkeypatch.setattr("builtins.input", lambda _: "   ")
    assert prompt_for_query() is None


def test_chroma_metadata_and_where_include_tag_filters() -> None:
    chunk = make_chunk("pi5-camera", "camera setup", ("camera",))
    chunk = DocumentChunk(
        **{**chunk.__dict__, "product_models": ("Raspberry Pi 5",), "os_versions": ("Raspberry Pi OS",)}
    )
    metadata = chunk_to_chroma_metadata(chunk)

    assert metadata[tag_flag_key("product_models", "Raspberry Pi 5")] is True
    assert metadata[tag_flag_key("use_cases", "camera")] is True
    assert metadata[tag_flag_key("os_versions", "Raspberry Pi OS")] is True
    assert metadata["filter_all_product_models"] is False

    where = chroma_where(
        RagFilters(product_models=("Raspberry Pi 5",), use_cases=("camera",), os_versions=("Raspberry Pi OS",))
    )
    assert where is not None
    conditions = where["$and"]
    assert {"official_verified": True} in conditions
    assert {"quality_status": "approved"} in conditions
    tag_conditions = [condition["$or"] for condition in conditions if "$or" in condition]
    assert any(
        {tag_flag_key("product_models", "Raspberry Pi 5"): True} in options
        for options in tag_conditions
    )
    assert any(
        {tag_flag_key("use_cases", "camera"): True} in options
        for options in tag_conditions
    )

    strict_where = chroma_where(
        RagFilters(product_models=("Raspberry Pi 5",), strict_product_match=True)
    )
    assert strict_where is not None
    assert strict_where["$and"][2] == {
        tag_flag_key("product_models", "Raspberry Pi 5"): True
    }

    document_where = chroma_where(RagFilters(document_ids=("doc-pi5", "doc-zero")))
    assert document_where == {
        "$and": [
            {"official_verified": True},
            {"quality_status": "approved"},
            {"document_id": {"$in": ["doc-pi5", "doc-zero"]}},
        ]
    }


def test_dense_configuration_error_is_not_silently_hidden(monkeypatch) -> None:
    retriever = HybridRetriever([make_chunk("camera", "camera", ("camera",))], chroma_path="missing-chroma")
    # Chroma import 자체가 실패한 상황을 흉내 내어 BM25 fallback이 아닌 명시적 오류를 확인한다.
    monkeypatch.setitem(sys.modules, "chromadb", None)

    with pytest.raises(DenseRetrievalError, match="Dense retrieval failed"):
        retriever.search("camera")


def test_indexer_reset_deletes_existing_collection_and_writes_scalar_metadata(tmp_path, monkeypatch) -> None:
    manifest_path = tmp_path / "manifest.json"
    embedding_input = build_e5_passage(
        title="Camera", section="Setup", content="camera setup"
    )
    embedding_checksum = "sha256:" + hashlib.sha256(
        embedding_input.encode("utf-8")
    ).hexdigest()
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.1.0",
                "generated_at": "2026-08-31T00:00:00+00:00",
                "source_registry": "document_pipeline/data/source_registry_v3.csv",
                "processing": {},
                "chunks": [
                    {
                        "chunk_id": "camera",
                        "document_id": "doc-1",
                        "title": "Camera",
                        "section": "Setup",
                        "content": "camera setup",
                        "source_url": "https://www.raspberrypi.com/documentation/",
                        "source_anchor": None,
                        "collected_at": "2026-08-28",
                        "document_version": None,
                        "license": "CC BY-SA 4.0",
                        "product_models": ["Raspberry Pi 5"],
                        "use_cases": ["camera"],
                        "os_versions": ["Raspberry Pi OS"],
                        "official_verified": True,
                        "quality_status": "approved",
                        "embedding_checksum": "sha256:" + hashlib.sha256(
                                build_e5_passage(
                                    title="Camera",
                                    section="Setup",
                                    content="camera setup",
                                ).encode("utf-8")
                            ).hexdigest(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    class FakeCollection:
        def __init__(self) -> None:
            self.upserted: dict[str, object] | None = None

        def upsert(self, **kwargs: object) -> None:
            self.upserted = kwargs

        def get(self) -> dict[str, list[str]]:
            return {"ids": []}

    class FakeClient:
        def __init__(self) -> None:
            self.collection = FakeCollection()
            self.deleted: list[str] = []

        def list_collections(self) -> list[str]:
            return ["rpi_official"]

        def delete_collection(self, name: str) -> None:
            self.deleted.append(name)

        def get_or_create_collection(self, name: str) -> FakeCollection:
            assert name == "rpi_official"
            return self.collection

    class FakeSentenceTransformer:
        def __init__(self, name: str) -> None:
            assert name == "test-e5"

        def encode(self, texts: list[str], normalize_embeddings: bool) -> list[list[float]]:
            assert texts == [embedding_input]
            assert normalize_embeddings is True
            return [[0.1, 0.2]]

    client = FakeClient()
    monkeypatch.setitem(sys.modules, "chromadb", types.SimpleNamespace(PersistentClient=lambda path: client))
    monkeypatch.setitem(
        sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer)
    )

    count = build_chroma_index(manifest_path, tmp_path / "chroma", embedding_model_name="test-e5", reset=True)

    assert count == 1
    assert client.deleted == ["rpi_official"]
    assert client.collection.upserted is not None
    metadata = client.collection.upserted["metadatas"][0]
    assert metadata[tag_flag_key("product_models", "Raspberry Pi 5")] is True
    assert (tmp_path / "chroma" / "picare-index.json").is_file()


def test_manifest_adapter_rejects_legacy_manifest_schema(tmp_path) -> None:
    legacy_manifest = {
        "chunks": [
            {
                "chunk_id": "legacy-camera-001",
                "document_id": "legacy-camera",
                "title": "Legacy camera fixture",
                "section": "Setup",
                "content": "Legacy fixture content.",
                "source_url": "https://example.test/legacy-camera",
                "retrieved_at": "2026-08-28",
                "document_version": None,
                "license": "CC BY-SA 4.0",
                "product_models": [],
                "use_cases": ["camera"],
                "os_versions": ["Raspberry Pi OS"],
                "source_type": "documentation",
                "official_verified": True,
            }
        ]
    }
    path = tmp_path / "legacy-manifest.json"
    path.write_text(json.dumps(legacy_manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version 1.1.0"):
        HybridRetriever.from_manifest(path)
