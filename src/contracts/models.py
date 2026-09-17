"""Canonical, versioned contracts for integration between project modules."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


CONTRACT_VERSION = "1.1.0"
CHAT_RESPONSE_VERSION = "1.2.0"

NonEmptyText = Annotated[str, Field(min_length=1)]
NonEmptyTextList = Annotated[list[NonEmptyText], Field(min_length=1)]

UseCase = Literal[
    "education_coding",
    "desktop_computing",
    "home_server",
    "camera_monitoring",
    "smart_farm_monitoring",
    "headless_remote_management",
    "gpio_iot",
]
Intent = Literal[
    "product_recommendation",
    "product_comparison",
    "how_to",
    "troubleshooting",
    "support_recall",
    "out_of_scope",
]
Task = Literal[
    "desktop_programming",
    "os_installation",
    "system_configuration",
    "remote_access",
    "camera_setup",
    "gpio_setup",
    "sensor_monitoring",
    "server_operation",
    "troubleshooting",
    "support_recall",
]
SourceType = Literal[
    "documentation",
    "product_page",
    "faq",
    "release_note",
    "support_notice",
    "recall_notice",
]
AnswerStatus = Literal[
    "answered",
    "needs_clarification",
    "insufficient_evidence",
    "out_of_scope",
    "safety_blocked",
    "error",
]


class StrictContract(BaseModel):
    """Reject undeclared fields so independently developed modules cannot drift."""

    model_config = ConfigDict(extra="forbid")


class QuizEvidence(StrictContract):
    """One final Q&A citation reused as the source body for a quiz question."""

    citation_id: Annotated[str, Field(pattern=r"^C[1-9][0-9]*$")]
    document_id: NonEmptyText
    chunk_id: NonEmptyText
    content: NonEmptyText

    @field_validator("document_id", "chunk_id", "content")
    @classmethod
    def validate_non_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("quiz evidence text must not be blank")
        return value


class QuizQuoteCandidate(StrictContract):
    """An exact, quote-safe substring selected from one quiz evidence body."""

    quote_id: Annotated[str, Field(pattern=r"^C[1-9][0-9]*-Q[1-9][0-9]*$")]
    evidence_id: Annotated[str, Field(pattern=r"^C[1-9][0-9]*$")]
    content: NonEmptyText

    @field_validator("content")
    @classmethod
    def validate_non_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("quiz quote candidate content must not be blank")
        return value


class QuizGenerationRequest(StrictContract):
    """Input passed to QuizGenerator after a grounded Q&A response is complete."""

    request_id: str
    answer: str
    evidence: list[QuizEvidence]
    quote_candidates: list[QuizQuoteCandidate] = Field(default_factory=list)
    max_questions: int = Field(ge=1, le=3)


class QuizChoice(StrictContract):
    """One generated answer choice; detailed choice validation is service-owned."""

    id: Literal["A", "B", "C", "D"]
    text: str


class QuizQuestion(StrictContract):
    """A generated quiz question before deterministic service validation."""

    question_id: str
    question: str
    choices: list[QuizChoice]
    correct_choice_id: Literal["A", "B", "C", "D"]
    explanation: str
    evidence_ids: list[str]
    supporting_quotes: list[str]


class QuizDraftQuestion(StrictContract):
    """LLM-only quiz shape; the server materializes the exact quote by ID."""

    question_id: str
    question: str
    choices: list[QuizChoice]
    correct_choice_id: Literal["A", "B", "C", "D"]
    explanation: str
    evidence_ids: list[str]
    supporting_quote_id: str


class QuizDraftResponse(StrictContract):
    """Raw model response before an exact quote candidate is materialized."""

    status: Literal["available", "insufficient_content", "generation_failed"]
    questions: list[QuizDraftQuestion]

    @model_validator(mode="after")
    def validate_status_questions(self) -> "QuizDraftResponse":
        if self.status == "available" and not self.questions:
            raise ValueError("available quiz responses must contain at least one question")
        if self.status != "available" and self.questions:
            raise ValueError("non-available quiz responses must not contain questions")
        return self


class QuizResponse(StrictContract):
    """Structured result returned by QuizGenerator."""

    status: Literal["available", "insufficient_content", "generation_failed"]
    questions: list[QuizQuestion]

    @model_validator(mode="after")
    def validate_status_questions(self) -> "QuizResponse":
        if self.status == "available" and not self.questions:
            raise ValueError("available quiz responses must contain at least one question")
        if self.status != "available" and self.questions:
            raise ValueError("non-available quiz responses must not contain questions")
        return self


SummaryStatus = Literal["available", "generation_failed", "not_applicable", "unsupported"]


class QaSummaryResult(StrictContract):
    """Independent title and answer-summary outcomes for one completed Q&A."""

    question_title: str | None
    question_title_status: SummaryStatus
    answer_summary: str | None
    answer_summary_status: SummaryStatus

    @model_validator(mode="after")
    def validate_status_text_pairs(self) -> "QaSummaryResult":
        for field_name, status in (
            ("question_title", self.question_title_status),
            ("answer_summary", self.answer_summary_status),
        ):
            value = getattr(self, field_name)
            if status != "available":
                if value is not None:
                    raise ValueError(f"{field_name} must be null unless available")
                continue
            if value is None or not value.strip():
                raise ValueError(f"available {field_name} must not be blank")
            if value != value.strip() or "\n" in value or "\r" in value:
                raise ValueError(f"{field_name} must be one trimmed line")
            limit = 200 if field_name == "question_title" else 500
            if len(value) > limit:
                raise ValueError(f"{field_name} exceeds {limit} characters")
        return self


class ConditionPayload(StrictContract):
    """Complete sLLM condition output; unmentioned user constraints are null."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"needs_clarification": {"const": True}}},
                    "then": {"properties": {"clarification_questions": {"minItems": 1}}},
                    "else": {"properties": {"clarification_questions": {"maxItems": 0}}},
                }
            ]
        },
    )

    schema_version: Literal[CONTRACT_VERSION]
    intent: Intent
    use_case: UseCase | None
    product_models: NonEmptyTextList | None
    os_versions: NonEmptyTextList | None
    task: Task | None
    performance_priority: Literal["low", "medium", "high"] | None
    wireless_required: bool | None
    camera_required: bool | None
    gpio_required: bool | None
    monitor_available: bool | None
    remote_access_required: bool | None
    user_level: Literal["beginner", "intermediate", "advanced"] | None
    additional_use_cases: list[UseCase] = Field(default_factory=list, max_length=7)
    additional_tasks: list[Task] = Field(default_factory=list, max_length=10)
    ethernet_required: bool | None = None
    min_camera_connectors: int | None = Field(default=None, ge=1, le=8)
    min_display_outputs: int | None = Field(default=None, ge=1, le=8)
    unverified_requirements: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list, max_length=20
    )
    needs_clarification: bool
    clarification_questions: list[NonEmptyText]

    @model_validator(mode="after")
    def validate_clarification(self) -> "ConditionPayload":
        if self.needs_clarification and not self.clarification_questions:
            raise ValueError("clarification_questions is required when needs_clarification is true")
        if not self.needs_clarification and self.clarification_questions:
            raise ValueError("clarification_questions must be empty when needs_clarification is false")
        return self


class SearchFilters(StrictContract):
    """Metadata filters applied by the integration layer before retrieval."""

    product_models: list[NonEmptyText]
    use_cases: list[NonEmptyText]
    os_versions: list[NonEmptyText]
    # catalog 추천 경로에서 후보 근거 문서로만 검색 범위를 제한할 때 사용한다.
    # 기본값은 기존 검색 계약과의 호환을 위한 제한 없음이다.
    document_ids: list[NonEmptyText] = Field(default_factory=list)
    source_types: list[SourceType]
    official_only: bool


class SearchResultMetadata(StrictContract):
    """One citation-safe retrieved chunk returned by the RAG module."""

    citation_id: Annotated[str, Field(pattern=r"^C[1-9][0-9]*$")]
    rank: Annotated[int, Field(ge=1)]
    document_id: NonEmptyText
    chunk_id: NonEmptyText
    chunk_index: Annotated[int, Field(ge=0)]
    title: NonEmptyText
    publisher: NonEmptyText
    section: NonEmptyText
    content: NonEmptyText
    source_url: HttpUrl
    source_anchor: NonEmptyText | None
    language: Annotated[str, Field(pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")]
    source_type: SourceType
    published_at: date | None
    updated_at: date | None
    collected_at: date
    indexed_at: datetime
    document_version: NonEmptyText | None
    license: NonEmptyText
    product_models: list[NonEmptyText]
    use_cases: list[NonEmptyText]
    tasks: list[NonEmptyText]
    categories: list[NonEmptyText]
    os_versions: list[NonEmptyText]
    document_checksum: NonEmptyText
    chunk_checksum: NonEmptyText
    embedding_checksum: NonEmptyText
    parser_version: NonEmptyText
    official_verified: Literal[True]
    quality_status: Literal["approved"]
    image_url: HttpUrl | None
    video_url: HttpUrl | None


class SearchResponse(StrictContract):
    """RAG-to-chatbot response contract."""

    schema_version: Literal[CONTRACT_VERSION]
    query_id: NonEmptyText
    query_language: Annotated[str, Field(pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")]
    retrieval_method: Literal["dense", "bm25", "hybrid"]
    top_k: Annotated[int, Field(ge=1, le=20)]
    applied_filters: SearchFilters
    results: list[SearchResultMetadata]

    @model_validator(mode="after")
    def validate_rank_and_citation_order(self) -> "SearchResponse":
        for expected_rank, result in enumerate(self.results, start=1):
            if result.rank != expected_rank or result.citation_id != f"C{expected_rank}":
                raise ValueError("results must be ordered and use citation IDs C1, C2, ...")
        chunk_ids = [result.chunk_id for result in self.results]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("results must not contain duplicate chunk_id values")
        return self


class ChatCitation(StrictContract):
    """Server-built source card referenced from the answer with [C1], [C2], ..."""

    citation_id: Annotated[str, Field(pattern=r"^C[1-9][0-9]*$")]
    document_id: NonEmptyText
    chunk_id: NonEmptyText
    title: NonEmptyText
    publisher: NonEmptyText
    section: NonEmptyText
    source_url: HttpUrl
    source_anchor: NonEmptyText | None
    document_version: NonEmptyText | None
    published_at: date | None
    updated_at: date | None
    collected_at: date
    license: NonEmptyText
    quote: NonEmptyText


class ProductRecommendation(StrictContract):
    """Structured card for product recommendation or comparison UI."""

    product_id: NonEmptyText
    product_model: NonEmptyText
    recommendation: NonEmptyText
    matched_conditions: list[NonEmptyText]
    limitations: list[NonEmptyText]
    citation_ids: NonEmptyTextList
    product_url: HttpUrl
    image_url: HttpUrl | None


class MediaItem(StrictContract):
    """Official image or video linked to a verified citation."""

    # ``media-<sha>`` is used by the generated document-media manifest, while
    # reviewed asset registries use stable IDs such as ``rpi-video-0001``.
    # Both are server-owned identifiers; they never come from LLM output.
    media_id: Annotated[
        str,
        Field(pattern=r"^(?:media-[0-9a-f]{20}|rpi-(?:product|guide|video)-[0-9]{4})$"),
    ]
    media_type: Literal["image", "video"]
    title: NonEmptyText
    url: HttpUrl
    alt_text: NonEmptyText | None
    display_mode: Literal["inline", "external_embed"]
    license: NonEmptyText
    attribution: NonEmptyText
    source_citation_id: Annotated[str, Field(pattern=r"^C[1-9][0-9]*$")]

    @model_validator(mode="after")
    def validate_display_mode(self) -> "MediaItem":
        expected = "inline" if self.media_type == "image" else "external_embed"
        if self.display_mode != expected:
            raise ValueError(f"{self.media_type} media must use {expected} display mode")
        return self


class ChatResponse(StrictContract):
    """Stable chatbot-to-Streamlit response contract."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"status": {"const": "answered"}}},
                    "then": {"properties": {"citations": {"minItems": 1}}},
                },
                {
                    "if": {"properties": {"status": {"const": "needs_clarification"}}},
                    "then": {"properties": {"clarification_questions": {"minItems": 1}}},
                },
            ]
        },
    )

    schema_version: Literal[CHAT_RESPONSE_VERSION]
    request_id: NonEmptyText
    status: AnswerStatus
    language: Annotated[str, Field(pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")]
    answer: NonEmptyText
    conditions: ConditionPayload | None
    citations: list[ChatCitation]
    products: list[ProductRecommendation]
    media: list[MediaItem]
    clarification_questions: list[NonEmptyText]
    warnings: list[NonEmptyText]

    @model_validator(mode="after")
    def validate_status_and_citations(self) -> "ChatResponse":
        citation_ids = {citation.citation_id for citation in self.citations}
        if len(citation_ids) != len(self.citations):
            raise ValueError("citations must not contain duplicate citation_id values")
        referenced_ids = set(re.findall(r"\[(C[1-9][0-9]*)\]", self.answer))
        if not referenced_ids.issubset(citation_ids):
            raise ValueError("answer references a citation ID missing from citations")
        if self.status == "answered" and (not self.citations or not referenced_ids):
            raise ValueError("answered responses require at least one inline citation")
        if self.status == "needs_clarification" and not self.clarification_questions:
            raise ValueError("needs_clarification responses require clarification_questions")
        product_citation_ids = {item for product in self.products for item in product.citation_ids}
        media_citation_ids = {item.source_citation_id for item in self.media}
        media_ids = [item.media_id for item in self.media]
        if len(media_ids) != len(set(media_ids)):
            raise ValueError("media items must not contain duplicate media_id values")
        if not product_citation_ids.issubset(citation_ids):
            raise ValueError("product cards reference a citation ID missing from citations")
        if not media_citation_ids.issubset(citation_ids):
            raise ValueError("media items reference a citation ID missing from citations")
        return self
