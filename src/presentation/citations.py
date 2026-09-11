"""RAG canonical metadata를 바꾸지 않고 출처 카드 표시값만 조립한다."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.contracts import ChatCitation


_DEFAULT_LABELS_PATH = Path(__file__).resolve().parents[2] / "data" / "presentation" / "citation_labels_ko.json"


@dataclass(frozen=True)
class CitationDisplay:
    """CLI·Streamlit이 공통으로 사용할 짧은 출처 표시 모델이다."""

    citation_id: str
    document_label: str
    section_label: str
    tags: tuple[str, ...]

    def cli_lines(self) -> tuple[str, str, str]:
        """터미널과 카드가 공유할 세 줄 표현을 반환한다."""

        return (
            f"[{self.citation_id}] {self.document_label}",
            f"섹션: {self.section_label}",
            f"태그: {' · '.join(self.tags)}" if self.tags else "태그: 없음",
        )


class CitationPresenter:
    """manifest 청크 metadata와 표시 사전을 조인하는 읽기 전용 presenter다."""

    def __init__(self, *, labels: Mapping[str, Any], chunks_by_id: Mapping[str, Mapping[str, Any]]) -> None:
        self.labels = labels
        self.chunks_by_id = chunks_by_id

    @staticmethod
    def _label(values: Mapping[str, Any], key: str, fallback: str) -> str:
        value = values.get(key)
        return value if isinstance(value, str) and value.strip() else fallback

    @staticmethod
    def _section_fallback(section: str) -> str:
        """새 section이 추가돼도 긴 경로 대신 마지막 공식 heading만 표시한다."""

        return section.rsplit(" > ", maxsplit=1)[-1]

    @staticmethod
    def _strings(value: object) -> tuple[str, ...]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            return ()
        return tuple(item for item in value if isinstance(item, str) and item)

    def present(
        self,
        citation: ChatCitation,
        *,
        preferred_use_case: str | None = None,
    ) -> CitationDisplay:
        """인용 카드 하나를 한국어 문서·섹션·최대 세 태그로 축약한다."""

        chunk = self.chunks_by_id.get(citation.chunk_id, {})
        document_labels = self.labels.get("document_labels", {})
        section_labels = self.labels.get("section_labels", {})
        section_leaf_labels = self.labels.get("section_leaf_labels", {})
        document_label = self._label(document_labels, citation.document_id, citation.title)
        section_leaf = self._section_fallback(citation.section)
        section_label = self._label(section_labels, citation.section, "")
        if not section_label:
            section_label = self._label(section_leaf_labels, section_leaf, "")
        if not section_label:
            # 새 공식 문서의 세부 heading은 사전이 갱신되기 전에도 영문을 그대로
            # 노출하지 않고, 이미 검수된 문서 한국어 제목으로 안전하게 축약한다.
            section_label = document_label if citation.document_id in document_labels else section_leaf

        tags: list[str] = []
        product_models = self._strings(chunk.get("product_models"))
        if product_models:
            tags.append(product_models[0])

        categories = self._strings(chunk.get("categories"))
        category_labels = self.labels.get("category_labels", {})
        if categories:
            tags.append(self._label(category_labels, categories[0], categories[0]))

        use_cases = self._strings(chunk.get("use_cases"))
        selected_use_case = preferred_use_case if preferred_use_case in use_cases else (use_cases[0] if use_cases else None)
        use_case_labels = self.labels.get("use_case_labels", {})
        if selected_use_case:
            tags.append(self._label(use_case_labels, selected_use_case, selected_use_case))

        return CitationDisplay(
            citation_id=citation.citation_id,
            document_label=document_label,
            section_label=section_label,
            tags=tuple(tags[:3]),
        )


def load_citation_presenter(
    manifest_path: str | Path,
    *,
    labels_path: str | Path = _DEFAULT_LABELS_PATH,
) -> CitationPresenter:
    """v3 manifest와 별도 표시 사전을 읽되 canonical 파일은 수정하지 않는다."""

    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    labels = json.loads(Path(labels_path).read_text(encoding="utf-8"))
    chunks = manifest.get("chunks")
    if not isinstance(chunks, list):
        raise ValueError("citation presenter requires a manifest chunks array")
    chunks_by_id = {
        chunk["chunk_id"]: chunk
        for chunk in chunks
        if isinstance(chunk, dict) and isinstance(chunk.get("chunk_id"), str)
    }
    return CitationPresenter(labels=labels, chunks_by_id=chunks_by_id)
