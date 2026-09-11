"""Cached Django assembly of the existing PiCare domain services."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if TYPE_CHECKING:
    from src.presentation import CitationPresenter
    from streamlit_app.runtime import RuntimeReadiness


@dataclass(frozen=True)
class DjangoRuntimeReadiness:
    """Fallback used when an optional RAG dependency is not installed yet."""

    ready: bool
    message: str


@lru_cache(maxsize=1)
def get_runtime_readiness() -> "RuntimeReadiness":
    """Check filesystem/config readiness without loading the model."""

    try:
        from streamlit_app.runtime import check_runtime_readiness

        return check_runtime_readiness(PROJECT_ROOT)
    except Exception as exc:
        return DjangoRuntimeReadiness(False, f"RAG 실행 환경 준비 필요: {exc}")


@lru_cache(maxsize=1)
def get_qa_service() -> Any:
    """Keep one QA service assembly per Django worker."""

    from streamlit_app.runtime import build_qa_service

    return build_qa_service(PROJECT_ROOT)


@lru_cache(maxsize=1)
def get_recommendation_service() -> Any:
    """Keep one recommendation service assembly per Django worker."""

    from streamlit_app.runtime import build_recommendation_service

    return build_recommendation_service(PROJECT_ROOT)


@lru_cache(maxsize=1)
def get_citation_presenter() -> "CitationPresenter | None":
    """Citation labels are optional and never block a source card."""

    try:
        from src.presentation import load_citation_presenter
        from src.rag import RagSettings

        return load_citation_presenter(RagSettings.from_env(PROJECT_ROOT).manifest_path)
    except Exception:
        return None
