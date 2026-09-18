"""RAG 검색 결과를 근거 기반 QA 응답으로 연결하는 UI 독립 서비스다."""

from __future__ import annotations

from typing import Literal, Protocol, Sequence
from collections.abc import Callable

from src.contracts.input_limits import validate_input_text
from src.contracts import ChatCitation, ChatResponse, MediaItem
from src.lang import (
    AnswerSafetyError,
    PromptBuildError,
    PromptEvidence,
    build_grounded_answer_messages,
    evaluate_request,
    is_evidence_abstention,
)
from src.media import MediaResolver
from src.rag import DenseRetrievalError, RagFilters, RagResult, RetrievalDecision
from src.rag_to_llm import AnswerGenerationError, AnswerGenerator, EvidenceTemplateGenerator
from src.rag_to_llm.cancellation import GenerationCancelled, raise_if_cancelled

from .grounded_generation import CitationRepairError, generate_validated_grounded_answer


RetrievalMode = Literal["bm25", "hybrid"]


class QaRetriever(Protocol):
    """QA 서비스가 RAG 구현과 느슨하게 연결되도록 하는 검색 계약이다."""

    def search_with_decision(
        self,
        query: str,
        filters: RagFilters | None = None,
        top_k: int = 5,
    ) -> RetrievalDecision:
        """검색 결과 또는 근거 부족 상태를 반환한다."""


class RagQaService:
    """안전 검사, RAG, 답변 생성 검증을 순서대로 조정한다.

    1차 QA는 사용자 질문을 그대로 검색한다. sLLM 조건 추출과 제품 catalog 기반
    필터는 제품 추천 통합 단계에서 추가한다.
    """

    def __init__(
        self,
        *,
        retriever: QaRetriever,
        answer_generator: AnswerGenerator | None = None,
        media_resolver: MediaResolver | None = None,
        top_k: int = 5,
    ) -> None:
        if not 1 <= top_k <= 20:
            raise ValueError("top_k must be between 1 and 20.")
        self.retriever = retriever
        self.answer_generator = answer_generator or EvidenceTemplateGenerator()
        self.media_resolver = media_resolver
        self.top_k = top_k

    @staticmethod
    def _status_response(
        *,
        request_id: str,
        status: Literal[
            "needs_clarification",
            "insufficient_evidence",
            "out_of_scope",
            "safety_blocked",
            "error",
        ],
        answer: str,
        warnings: Sequence[str] = (),
        clarification_questions: Sequence[str] = (),
    ) -> ChatResponse:
        """생성 LLM을 호출하지 않는 모든 종료 상태를 공통 형식으로 만든다."""

        questions = list(clarification_questions)
        if status == "needs_clarification" and not questions:
            questions = [answer]
        return ChatResponse(
            schema_version="1.2.0",
            request_id=request_id,
            status=status,
            language="ko",
            answer=answer,
            conditions=None,
            citations=[],
            products=[],
            media=[],
            clarification_questions=questions,
            warnings=list(warnings),
        )

    @staticmethod
    def _prompt_evidence(results: Sequence[RagResult]) -> tuple[PromptEvidence, ...]:
        """검색 순위로 C1, C2 인용 ID를 부여해 생성 프롬프트로 변환한다."""

        return tuple(
            PromptEvidence(
                citation_id=f"C{result.rank}",
                content=result.content,
                title=result.title,
                section=result.section,
            )
            for result in results
        )

    @staticmethod
    def _citation(result: RagResult) -> ChatCitation:
        """프로토타입 RAG 결과의 출처 정보를 공통 citation 계약으로 변환한다."""

        return ChatCitation(
            citation_id=f"C{result.rank}",
            document_id=result.document_id,
            chunk_id=result.chunk_id,
            title=result.title,
            publisher="Raspberry Pi Ltd",
            section=result.section,
            source_url=result.source_url,
            source_anchor=None,
            document_version=result.document_version,
            published_at=None,
            updated_at=None,
            # canonical manifest의 collected_at을 RAG adapter가 기존 필드명
            # retrieved_at으로 호환 변환한 값이다. 실제 검색 시각은 아니다.
            collected_at=result.retrieved_at,
            license=result.license,
            quote=result.content,
        )

    def answer(
        self,
        *,
        request_id: str,
        question: str,
        retrieval_mode: RetrievalMode,
        trace: bool = False,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> ChatResponse:
        """질문 하나를 근거가 검증된 QA 응답으로 변환한다."""

        raise_if_cancelled(cancel_requested)

        try:
            question = validate_input_text(question)
        except ValueError as exc:
            return self._status_response(
                request_id=request_id,
                status="needs_clarification",
                answer=f"질문 길이를 확인해 주세요. {exc}",
                warnings=["input_length_invalid"],
            )
        request_decision = evaluate_request(question)
        if not request_decision.allowed:
            return self._status_response(
                request_id=request_id,
                status=request_decision.status,
                answer=request_decision.message,
                warnings=[
                    f"safety_reason={request_decision.reason_code}",
                    *(["trace.generator_invoked=false"] if trace else []),
                ],
            )

        try:
            decision = self.retriever.search_with_decision(
                question,
                filters=RagFilters(),
                top_k=self.top_k,
            )
        except DenseRetrievalError as exc:
            return self._status_response(
                request_id=request_id,
                status="error",
                answer=(
                    "공식 문서 Dense 검색을 실행하지 못했습니다. Chroma 색인을 확인한 뒤 "
                    "`python3 -m src.services.rag_qa_cli --action index --reset`을 실행해 주세요."
                ),
                warnings=[f"retrieval_mode={retrieval_mode}", f"retrieval_error={type(exc).__name__}"],
            )
        except Exception as exc:  # 검색 구현의 예상하지 못한 오류도 답변으로 노출하지 않는다.
            return self._status_response(
                request_id=request_id,
                status="error",
                answer="공식 문서 검색 중 오류가 발생해 답변을 보류합니다.",
                warnings=[f"retrieval_mode={retrieval_mode}", f"retrieval_error={type(exc).__name__}"],
            )

        raise_if_cancelled(cancel_requested)
        if decision.status == "insufficient_evidence":
            return self._status_response(
                request_id=request_id,
                status="insufficient_evidence",
                answer="검색된 Raspberry Pi 공식 문서에서 질문을 뒷받침할 근거를 찾지 못했습니다.",
                warnings=[
                    f"retrieval_mode={retrieval_mode}",
                    f"retrieval_reason={decision.reason or 'no_qualified_evidence'}",
                    *(
                        ["trace.evidence_chunks=0", "trace.generator_invoked=false"]
                        if trace
                        else []
                    ),
                ],
            )

        results = decision.results
        evidence = self._prompt_evidence(results)
        try:
            messages = build_grounded_answer_messages(question, evidence)
            validated_generation = generate_validated_grounded_answer(
                generator=self.answer_generator,
                messages=messages,
                evidence=evidence,
                require_korean=True,
                cancel_requested=cancel_requested,
            )
            generation = validated_generation.generation
            if is_evidence_abstention(generation.text):
                return self._status_response(
                    request_id=request_id,
                    status="insufficient_evidence",
                    answer="검색된 공식 문서만으로 질문에 답할 수 없어 답변을 보류합니다.",
                    warnings=[
                        "abstention_reason=model_insufficient_evidence",
                        f"answer_generator={generation.provider}",
                        *(
                            [
                                "trace.generator_invoked=true",
                                f"trace.model_id={generation.model_id}",
                                "trace.citation_validation=skipped_abstention",
                            ]
                            if trace
                            else []
                        ),
                    ],
                )
            used_citation_ids = validated_generation.used_citation_ids
        except GenerationCancelled:
            raise
        except AnswerGenerationError as exc:
            return self._status_response(
                request_id=request_id,
                status="error",
                answer=str(exc),
                warnings=[f"generation_error={type(exc).__name__}"],
            )
        except CitationRepairError as exc:
            return self._status_response(
                request_id=request_id,
                status="error",
                answer="생성된 답변이 인용·안전 검사를 통과하지 못해 표시를 보류합니다.",
                warnings=[
                    f"generation_error={type(exc).__name__}",
                    *(
                        [
                            "trace.generation_attempts=2",
                            "trace.citation_repair=failed",
                            f"trace.citation_failure={exc.final_reason_code}",
                        ]
                        if trace
                        else []
                    ),
                ],
            )
        except (AnswerSafetyError, PromptBuildError, ValueError) as exc:
            return self._status_response(
                request_id=request_id,
                status="error",
                answer="생성된 답변이 인용·안전 검사를 통과하지 못해 표시를 보류합니다.",
                warnings=[f"generation_error={type(exc).__name__}"],
            )
        except Exception as exc:
            return self._status_response(
                request_id=request_id,
                status="error",
                answer="답변 생성 중 오류가 발생해 표시를 보류합니다.",
                warnings=[f"generation_error={type(exc).__name__}"],
            )

        citations = [
            self._citation(result)
            for result in results
            if f"C{result.rank}" in used_citation_ids
        ]
        # The server, never the LLM, joins reviewed media to citation chunk IDs
        # that survived grounded-answer validation.
        media = self.media_resolver.resolve(citations) if self.media_resolver is not None else []
        return ChatResponse(
            schema_version="1.2.0",
            request_id=request_id,
            status="answered",
            language="ko",
            answer=generation.text,
            conditions=None,
            citations=citations,
            products=[],
            media=media,
            clarification_questions=[],
            warnings=[
                f"retrieval_mode={retrieval_mode}",
                "metadata_compatibility: canonical collected_at is carried through legacy RagResult.retrieved_at",
                f"answer_generator={generation.provider}",
                *(
                    [
                        f"trace.evidence_chunks={len(evidence)}",
                        f"trace.generator={generation.provider}",
                        f"trace.model_id={generation.model_id}",
                        f"trace.generation_elapsed_ms={generation.elapsed_ms:.1f}",
                        f"trace.generation_attempts={validated_generation.attempts}",
                        f"trace.citation_repair={'applied' if validated_generation.repair_attempted else 'not_needed'}",
                        "trace.citation_validation=passed",
                    ]
                    if trace
                    else []
                ),
            ],
        )


__all__ = ["QaRetriever", "RagQaService", "RetrievalMode"]
