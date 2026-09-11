"""UI와 분리된 제품 추천과 문서 기반 QA 서비스를 공개한다.

무거운 추천 의존성은 명령어 실험실·미니 챌린지처럼 정적 검수 데이터만 쓰는
기능까지 요구하지 않도록, 기존 공개 심볼을 필요할 때만 불러온다.
"""

from __future__ import annotations

__all__ = [
    "RecommendationAgent",
    "RecommendationAgentResult",
    "RecommendationRagService",
    "build_recommendation_chat_response",
]


def __getattr__(name: str):
    """Keep the former package-level API without eager optional imports."""

    if name in {"RecommendationAgent", "RecommendationAgentResult"}:
        from .recommendation_agent import RecommendationAgent, RecommendationAgentResult

        return {"RecommendationAgent": RecommendationAgent, "RecommendationAgentResult": RecommendationAgentResult}[name]
    if name == "RecommendationRagService":
        from .recommendation_rag_service import RecommendationRagService

        return RecommendationRagService
    if name == "build_recommendation_chat_response":
        from .recommendation_response import build_recommendation_chat_response

        return build_recommendation_chat_response
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
