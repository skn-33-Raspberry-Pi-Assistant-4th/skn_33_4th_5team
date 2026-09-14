"""언어 체인 조합 계층.

프롬프트와 체인 구성 코드를 이 패키지에 둡니다.
모델 클라이언트는 ``src.rag_to_llm``에서 관리하며, import 시 외부 연결을 만들지 않습니다.
"""

from __future__ import annotations

from .prompts import (
    GROUNDED_ANSWER_SYSTEM_PROMPT,
    RECOMMENDATION_ANSWER_SYSTEM_PROMPT,
    PromptBuildError,
    PromptEvidence,
    build_citation_repair_messages,
    build_grounded_answer_messages,
    build_recommendation_answer_messages,
)
from .quiz_prompts import (
    QUIZ_GENERATION_SYSTEM_PROMPT,
    build_quiz_generation_messages,
)
from .safety import (
    INSUFFICIENT_EVIDENCE_MARKER,
    AnswerSafetyError,
    SafetyDecision,
    evaluate_request,
    extract_citation_ids,
    has_korean_prose,
    is_evidence_abstention,
    validate_grounded_answer,
)

__all__ = [
    "INSUFFICIENT_EVIDENCE_MARKER",
    "AnswerSafetyError",
    "GROUNDED_ANSWER_SYSTEM_PROMPT",
    "RECOMMENDATION_ANSWER_SYSTEM_PROMPT",
    "QUIZ_GENERATION_SYSTEM_PROMPT",
    "PromptBuildError",
    "PromptEvidence",
    "build_citation_repair_messages",
    "SafetyDecision",
    "build_grounded_answer_messages",
    "build_recommendation_answer_messages",
    "build_quiz_generation_messages",
    "evaluate_request",
    "extract_citation_ids",
    "has_korean_prose",
    "is_evidence_abstention",
    "validate_grounded_answer",
]
