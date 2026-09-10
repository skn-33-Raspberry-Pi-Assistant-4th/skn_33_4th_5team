"""sLLM 조건 추출·catalog·Hybrid RAG·Qwen을 제품 추천으로 연결한다."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Literal, Mapping, Protocol, Sequence

from src.condition_extraction.schema import SurveyAnswer, SurveyResponse
from src.condition_extraction.ui_input import RecommendationFormInput
from src.contracts.input_limits import validate_input_text
from src.contracts import ChatResponse, ConditionPayload
from src.lang import (
    AnswerSafetyError,
    PromptBuildError,
    PromptEvidence,
    build_recommendation_answer_messages,
    evaluate_request,
    is_evidence_abstention,
)
from src.media import MediaResolver
from src.rag import DenseRetrievalError, RagFilters, RagResult, RetrievalDecision
from src.rag_to_llm import AnswerGenerationError, AnswerGenerator, EvidenceTemplateGenerator

from .integration_adapters import (
    RagResultMetadata,
    condition_payload_to_rag_filters,
    rag_results_to_search_response,
)
from .grounded_generation import CitationRepairError, generate_validated_grounded_answer
from .recommendation_agent import RecommendationAgent, RecommendationAgentResult
from .recommendation_response import (
    build_recommendation_chat_response,
    candidate_condition_document_ids,
)


# 답변 본문에서 후보를 부정하는 표현이다. 사양을 설명하는 부정문("Wi-Fi를
# 지원하지 않습니다")은 추천 자체를 부정하지 않으므로 넣지 않는다.
_CANDIDATE_NEGATION_MARKERS = (
    "추천할 수 없",
    "추천하지 않",
    "추천하기 어렵",
    "추천드리기 어렵",
    "추천 대상이 아니",
    "권장하지 않",
    "권장할 수 없",
    "적합하지 않",
    "적절하지 않",
    "근거가 부족",
    "근거 부족",
    "정보가 부족",
    "확인할 수 없",
    "확인되지 않",
    "보류",
)
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|[\n\r]+")


class RecommendationRetriever(Protocol):
    """제품 추천 서비스가 의존하는 최소 Hybrid Retriever 계약이다."""

    def search_with_decision(
        self,
        query: str,
        filters: RagFilters | None = None,
        top_k: int = 5,
    ) -> RetrievalDecision: ...


class RecommendationRagService:
    """자유 제품 추천 요청을 근거가 있는 `ChatResponse`로 완성한다."""

    def __init__(
        self,
        *,
        recommendation_agent: RecommendationAgent,
        retriever: RecommendationRetriever,
        metadata_by_chunk_id: Mapping[str, RagResultMetadata],
        answer_generator: AnswerGenerator | None = None,
        media_resolver: MediaResolver | None = None,
        top_k: int = 8,
    ) -> None:
        if not 1 <= top_k <= 20:
            raise ValueError("top_k must be between 1 and 20.")
        self.recommendation_agent = recommendation_agent
        self.retriever = retriever
        self.metadata_by_chunk_id = metadata_by_chunk_id
        self.answer_generator = answer_generator or EvidenceTemplateGenerator()
        self.media_resolver = media_resolver
        self.top_k = top_k

    @staticmethod
    def _response(
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
        conditions: ConditionPayload | None = None,
        warnings: Sequence[str] = (),
        clarification_questions: Sequence[str] = (),
    ) -> ChatResponse:
        questions = list(clarification_questions)
        if status == "needs_clarification" and not questions:
            questions = [answer]
        return ChatResponse(
            schema_version="1.2.0",
            request_id=request_id,
            status=status,
            language="ko",
            answer=answer,
            conditions=conditions,
            citations=[],
            products=[],
            media=[],
            clarification_questions=questions,
            warnings=list(warnings),
        )

    @staticmethod
    def _survey(question: str) -> SurveyResponse:
        return SurveyResponse(
            answers=[
                SurveyAnswer(
                    question_id="free_text",
                    question="Raspberry Pi 제품 추천 요청",
                    answer=question,
                )
            ]
        )

    @staticmethod
    def _prompt_evidence(results: Sequence[RagResult]) -> tuple[PromptEvidence, ...]:
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
    def _candidate_context(agent_result: RecommendationAgentResult) -> str:
        """LLM이 새 후보를 만들지 않도록 서버가 확정한 후보만 짧게 전달한다."""

        lines = []
        for candidate in agent_result.decision.candidates:
            conditions = ", ".join(candidate.matched_conditions) or "입력 조건 충족"
            lines.append(f"- 제품: {candidate.name}; 서버 선정 조건: {conditions}")
        return "\n".join(lines)

    def _reject_unselected_catalog_products(
        self,
        answer: str,
        agent_result: RecommendationAgentResult,
        *,
        provider: str,
    ) -> None:
        """모델이 catalog 안의 비선정 제품을 새 추천으로 추가하지 못하게 막는다."""

        # 로컬 template은 모델 추천문이 아니라 검색 청크 원문을 인용별로
        # 표시한다. 비교 문서에 다른 제품명이 단순 등장해도 변조가 아니다.
        if provider == "template":
            return
        selected = {candidate.name for candidate in agent_result.decision.candidates}
        for product in self.recommendation_agent.recommender.catalog.products:
            if product.name not in selected and product.name in answer:
                raise ValueError(f"선정되지 않은 제품을 답변에 추가했습니다: {product.name}")

    def _retrieval_supports_candidate(
        self,
        results: Sequence[RagResult],
        candidate,
        conditions: ConditionPayload,
    ) -> bool:
        """검색 결과가 이 후보의 조건 판단을 실제로 뒷받침하는지 확인한다.

        제품 근거 전체가 아니라 조건 관련 필드 근거만 인정하고, 그 청크가
        이 제품을 다루는지도 함께 본다. 문서 번호만 겹치면 다른 제품의
        사양 문서가 이 후보의 근거로 붙기 때문이다.
        """

        supporting_document_ids = candidate_condition_document_ids(candidate, conditions)
        for result in results:
            if result.document_id not in supporting_document_ids:
                continue
            metadata = self.metadata_by_chunk_id.get(result.chunk_id)
            if metadata is not None and candidate.name in metadata.product_models:
                return True
        return False

    @staticmethod
    def _drop_candidates_negated_by_answer(
        answer: str, agent_result: RecommendationAgentResult, *, provider: str
    ) -> RecommendationAgentResult:
        """본문이 부정 문맥으로만 언급한 후보를 제품 카드에서 제외한다.

        "Pi 5는 근거가 부족해 추천할 수 없다"처럼 부정으로만 등장한 제품의
        카드가 남으면 본문과 카드가 서로 어긋난다. 긍정 문장이 한 번이라도
        있거나 아예 언급되지 않은 후보는 그대로 둔다.

        로컬 template은 검색 청크 원문을 그대로 보여주는 개발용 생성기라
        추천 문장을 만들지 않으므로 검사하지 않는다.
        """

        if provider == "template":
            return agent_result
        sentences = [
            sentence
            for sentence in _SENTENCE_BOUNDARY.split(answer)
            if sentence.strip()
        ]
        kept = []
        for candidate in agent_result.decision.candidates:
            mentions = [
                sentence for sentence in sentences if candidate.name in sentence
            ]
            negated_only = bool(mentions) and all(
                any(marker in sentence for marker in _CANDIDATE_NEGATION_MARKERS)
                for sentence in mentions
            )
            if not negated_only:
                kept.append(candidate)
        if len(kept) == len(agent_result.decision.candidates):
            return agent_result
        decision = agent_result.decision.model_copy(update={"candidates": kept})
        return agent_result.model_copy(update={"decision": decision})

    @staticmethod
    def _require_selected_candidate_in_model_answer(
        answer: str, agent_result: RecommendationAgentResult, *, provider: str
    ) -> None:
        """실제 생성 모델의 추천 설명이 서버 선정 후보를 언급하는지 확인한다.

        로컬 template은 검색 근거 표시만 하는 개발용 생성기라 후보명을 만들지 않는다.
        반면 Qwen 같은 실제 모델은 선택 후보 중 하나 이상을 명시해야 제품 카드와
        답변 본문의 연결을 사용자가 확인할 수 있다.
        """

        if provider == "template":
            return
        selected = [candidate.name for candidate in agent_result.decision.candidates]
        if not any(name in answer for name in selected):
            raise ValueError("생성된 추천 답변에 서버가 선정한 제품 후보가 없습니다.")

    @staticmethod
    def _with_warnings(response: ChatResponse, warnings: Sequence[str]) -> ChatResponse:
        return response.model_copy(update={"warnings": [*response.warnings, *warnings]})

    def answer(
        self,
        *,
        request_id: str,
        question: str,
        trace: bool = False,
    ) -> ChatResponse:
        """자유 입력을 조건 추출부터 인용 포함 제품 추천까지 처리한다."""

        try:
            question = validate_input_text(question)
        except ValueError as exc:
            return self._response(
                request_id=request_id,
                status="needs_clarification",
                answer=f"추천 요청 길이를 확인해 주세요. {exc}",
                warnings=["input_length_invalid"],
            )
        request_decision = evaluate_request(question)
        if not request_decision.allowed:
            return self._response(
                request_id=request_id,
                status=request_decision.status,
                answer=request_decision.message,
                warnings=[
                    f"safety_reason={request_decision.reason_code}",
                    *(["trace.generator_invoked=false"] if trace else []),
                ],
            )

        try:
            agent_result = self.recommendation_agent.recommend(self._survey(question))
        except Exception as exc:
            return self._response(
                request_id=request_id,
                status="error",
                answer="제품 추천 조건을 분석하지 못해 답변을 보류합니다.",
                warnings=[f"condition_extraction_error={type(exc).__name__}"],
            )

        return self._answer_from_agent_result(
            request_id=request_id,
            question=question,
            agent_result=agent_result,
            trace=trace,
        )

    def answer_form(
        self,
        *,
        form: RecommendationFormInput,
        trace: bool = False,
    ) -> ChatResponse:
        """Streamlit 폼 입력을 조건 추출부터 인용 포함 제품 추천까지 처리한다.

        위젯의 명시적 선택값(사용자 수준, 성능, Wi-Fi·카메라·GPIO·모니터 여부)은
        `RecommendationAgent.recommend_form`을 통해 sLLM 추출값보다 우선 적용된다.
        """

        request_decision = evaluate_request(form.free_text)
        if not request_decision.allowed:
            return self._response(
                request_id=form.request_id,
                status=request_decision.status,
                answer=request_decision.message,
                warnings=[
                    f"safety_reason={request_decision.reason_code}",
                    *( ["trace.generator_invoked=false"] if trace else [] ),
                ],
            )

        try:
            agent_result = self.recommendation_agent.recommend_form(form)
        except Exception as exc:
            return self._response(
                request_id=form.request_id,
                status="error",
                answer="제품 추천 조건을 분석하지 못해 답변을 보류합니다.",
                warnings=[f"condition_extraction_error={type(exc).__name__}"],
            )

        return self._answer_from_agent_result(
            request_id=form.request_id,
            question=form.free_text,
            agent_result=agent_result,
            trace=trace,
        )

    def _answer_from_agent_result(
        self,
        *,
        request_id: str,
        question: str,
        agent_result: RecommendationAgentResult,
        trace: bool,
    ) -> ChatResponse:
        """조건 추출 이후의 catalog 매칭·RAG 검색·인용 생성을 공통 처리한다."""

        decision = agent_result.decision
        if decision.status.value == "needs_clarification":
            return self._response(
                request_id=request_id,
                status="needs_clarification",
                answer="제품을 추천하려면 추가 조건이 필요합니다.",
                conditions=decision.conditions,
                warnings=agent_result.warnings,
                clarification_questions=decision.clarification_questions,
            )
        if decision.status.value == "out_of_scope":
            return self._response(
                request_id=request_id,
                status="out_of_scope",
                answer="이 요청은 Raspberry Pi 제품 추천 범위가 아닙니다.",
                conditions=decision.conditions,
                warnings=agent_result.warnings,
            )
        if decision.status.value == "no_match":
            return self._response(
                request_id=request_id,
                status="insufficient_evidence",
                answer="현재 공식 제품 카탈로그에서 모든 필수 조건을 만족하는 후보를 찾지 못했습니다.",
                conditions=decision.conditions,
                warnings=agent_result.warnings,
                clarification_questions=decision.clarification_questions,
            )

        candidate_document_ids = tuple(
            sorted(
                {
                    document_id
                    for candidate in decision.candidates
                    for document_id in candidate.evidence_document_ids
                }
            )
        )
        candidate_product_names = tuple(
            candidate.name for candidate in decision.candidates
        )
        filters = replace(
            condition_payload_to_rag_filters(decision.conditions),
            document_ids=candidate_document_ids,
            product_models=candidate_product_names,
            strict_product_match=True,
        )
        retrieval_query = " ".join([question, *(candidate.name for candidate in decision.candidates)])
        try:
            retrieval = self.retriever.search_with_decision(
                retrieval_query,
                filters=filters,
                top_k=self.top_k,
            )
        except DenseRetrievalError as exc:
            return self._response(
                request_id=request_id,
                status="error",
                answer=(
                    "추천 근거를 검색하지 못했습니다. Chroma 색인을 확인한 뒤 "
                    "`python3 -m src.services.rag_qa_cli --action index --reset`을 실행해 주세요."
                ),
                conditions=decision.conditions,
                warnings=[*agent_result.warnings, f"retrieval_error={type(exc).__name__}"],
            )
        except Exception as exc:
            return self._response(
                request_id=request_id,
                status="error",
                answer="추천 근거를 검색하는 중 오류가 발생해 답변을 보류합니다.",
                conditions=decision.conditions,
                warnings=[*agent_result.warnings, f"retrieval_error={type(exc).__name__}"],
            )

        if retrieval.status == "insufficient_evidence":
            return self._response(
                request_id=request_id,
                status="insufficient_evidence",
                answer="선정된 제품 후보를 뒷받침할 공식 문서 근거를 찾지 못했습니다.",
                conditions=decision.conditions,
                warnings=[
                    *agent_result.warnings,
                    f"retrieval_reason={retrieval.reason or 'no_qualified_evidence'}",
                    *( ["trace.generator_invoked=false"] if trace else [] ),
                ],
            )

        supported_candidates = [
            candidate
            for candidate in decision.candidates
            if self._retrieval_supports_candidate(
                retrieval.results, candidate, decision.conditions
            )
        ]
        if not supported_candidates:
            return self._response(
                request_id=request_id,
                status="insufficient_evidence",
                answer="추천 후보는 찾았지만 인용 가능한 공식 근거가 부족합니다.",
                conditions=decision.conditions,
                warnings=[*agent_result.warnings, "retrieval_reason=candidate_evidence_missing"],
            )
        supported_decision = decision.model_copy(update={"candidates": supported_candidates})
        supported_agent_result = agent_result.model_copy(update={"decision": supported_decision})

        try:
            search_response = rag_results_to_search_response(
                retrieval.results,
                query_id=request_id,
                query_language="ko",
                retrieval_method="hybrid",
                top_k=self.top_k,
                applied_filters=filters,
                metadata_by_chunk_id=self.metadata_by_chunk_id,
            )
            evidence = self._prompt_evidence(retrieval.results)
            messages = build_recommendation_answer_messages(
                question,
                selected_candidates=self._candidate_context(supported_agent_result),
                evidence=evidence,
            )
            validated_generation = generate_validated_grounded_answer(
                generator=self.answer_generator,
                messages=messages,
                evidence=evidence,
                require_korean=True,
            )
            generation = validated_generation.generation
            if is_evidence_abstention(generation.text):
                return self._response(
                    request_id=request_id,
                    status="insufficient_evidence",
                    answer="검색된 공식 문서만으로 제품 추천을 뒷받침할 수 없어 답변을 보류합니다.",
                    conditions=decision.conditions,
                    warnings=[
                        *agent_result.warnings,
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
            self._reject_unselected_catalog_products(
                generation.text,
                supported_agent_result,
                provider=generation.provider,
            )
            self._require_selected_candidate_in_model_answer(
                generation.text,
                supported_agent_result,
                provider=generation.provider,
            )
            card_agent_result = self._drop_candidates_negated_by_answer(
                generation.text,
                supported_agent_result,
                provider=generation.provider,
            )
        except AnswerGenerationError as exc:
            return self._response(
                request_id=request_id,
                status="error",
                answer=str(exc),
                conditions=decision.conditions,
                warnings=[*agent_result.warnings, f"generation_error={type(exc).__name__}"],
            )
        except CitationRepairError as exc:
            return self._response(
                request_id=request_id,
                status="error",
                answer="생성된 제품 추천이 인용·안전 검사를 통과하지 못해 표시를 보류합니다.",
                conditions=decision.conditions,
                warnings=[
                    *agent_result.warnings,
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
            return self._response(
                request_id=request_id,
                status="error",
                answer="생성된 제품 추천이 인용·안전 검사를 통과하지 못해 표시를 보류합니다.",
                conditions=decision.conditions,
                warnings=[*agent_result.warnings, f"generation_error={type(exc).__name__}"],
            )
        except Exception as exc:
            return self._response(
                request_id=request_id,
                status="error",
                answer="제품 추천 답변 생성 중 오류가 발생해 표시를 보류합니다.",
                conditions=decision.conditions,
                warnings=[*agent_result.warnings, f"generation_error={type(exc).__name__}"],
            )

        if not card_agent_result.decision.candidates:
            return self._response(
                request_id=request_id,
                status="insufficient_evidence",
                answer=(
                    "생성된 추천 본문이 선정 후보를 모두 부정해 제품 카드를 "
                    "표시하지 않고 답변을 보류합니다."
                ),
                conditions=decision.conditions,
                warnings=[
                    *agent_result.warnings,
                    "abstention_reason=answer_negates_all_candidates",
                ],
            )

        response = build_recommendation_chat_response(
            request_id=request_id,
            agent_result=card_agent_result,
            search_response=search_response,
            answer=None if isinstance(self.answer_generator, EvidenceTemplateGenerator) else generation.text,
            used_citation_ids=used_citation_ids,
        )
        if self.media_resolver is not None:
            final_answer_citations = [
                citation
                for citation in response.citations
                if citation.citation_id in used_citation_ids
            ]
            response = response.model_copy(
                update={"media": self.media_resolver.resolve(final_answer_citations)}
            )
        return self._with_warnings(
            response,
            [
                "retrieval_mode=hybrid",
                f"condition_extractor={supported_agent_result.extractor_mode.value}",
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


__all__ = ["RecommendationRagService", "RecommendationRetriever"]
