"""Cached Django assembly of the existing PiCare domain services."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any


# services.py → portal → web_app → repository root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
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
    """Return the team's RAG readiness check without loading a model.

    Delegates to ``streamlit_app.runtime.check_runtime_readiness`` so Django
    and the existing Streamlit entry point validate the same environment,
    manifest, and Chroma index prerequisites.
    """

    try:
        from streamlit_app.runtime import check_runtime_readiness

        return check_runtime_readiness(PROJECT_ROOT)
    except Exception as exc:
        return DjangoRuntimeReadiness(False, f"RAG 실행 환경 준비 필요: {exc}")


@lru_cache(maxsize=1)
def get_qa_service() -> Any:
    """Build and cache the team's ``RagQaService`` for Django Q&A requests.

    The factory assembles Hybrid retrieval, answer generation, and media
    resolution. Django views only call its public ``answer`` method.
    """

    from streamlit_app.runtime import build_qa_service

    return build_qa_service(PROJECT_ROOT)


@lru_cache(maxsize=1)
def get_recommendation_service() -> Any:
    """Build and cache the team's evidence-backed recommendation service.

    The returned service owns condition extraction, catalog filtering, Hybrid
    RAG retrieval, and grounded recommendation generation.
    """

    from streamlit_app.runtime import build_recommendation_service

    return build_recommendation_service(PROJECT_ROOT)


@lru_cache(maxsize=1)
def get_citation_presenter() -> "CitationPresenter | None":
    """Load the citation display adapter; fall back to raw citation fields.

    Citation presentation is intentionally optional: a formatting failure must
    never hide an otherwise valid official source card from the user.
    """

    try:
        from src.presentation import load_citation_presenter
        from src.rag import RagSettings

        return load_citation_presenter(RagSettings.from_env(PROJECT_ROOT).manifest_path)
    except Exception:
        return None


@lru_cache(maxsize=1)
def get_command_lab_service() -> Any:
    """Build and cache the reviewed, display-only command lab service.

    ``CommandLabService`` validates catalog approval and input safety. It
    analyzes or composes text only and has no command execution capability.
    """

    from src.services.command_lab_service import CommandLabService

    return CommandLabService(PROJECT_ROOT)


@lru_cache(maxsize=1)
def get_challenge_service() -> Any:
    """Build and cache the reviewed question-bank service for web challenges.

    The service keeps answer keys and rationale server-side until a submitted
    choice is validated, for both three-question and Q&A inline challenges.
    """

    from src.services.challenge_service import ChallengeService

    return ChallengeService(PROJECT_ROOT)
