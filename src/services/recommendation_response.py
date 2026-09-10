"""추천 후보와 공식 RAG 결과를 팀 공통 ChatResponse로 조립한다."""

from __future__ import annotations

from src.contracts import (
    ChatCitation,
    ChatResponse,
    ConditionPayload,
    ProductRecommendation,
    SearchResponse,
)

from .recommendation_agent import RecommendationAgentResult


def _citation(result) -> ChatCitation:
    """검증된 검색 metadata 한 건을 화면용 인용 카드로 변환한다."""

    return ChatCitation(
        citation_id=result.citation_id,
        document_id=result.document_id,
        chunk_id=result.chunk_id,
        title=result.title,
        publisher=result.publisher,
        section=result.section,
        source_url=result.source_url,
        source_anchor=result.source_anchor,
        document_version=result.document_version,
        published_at=result.published_at,
        updated_at=result.updated_at,
        collected_at=result.collected_at,
        license=result.license,
        quote=result.content,
    )


def condition_evidence_fields(conditions: ConditionPayload) -> tuple[str, ...]:
    """사용자 조건이 실제로 근거를 요구하는 evidence_by_field 필드를 고른다.

    후보를 고른 이유가 된 조건만 근거를 요구한다. 요구하지 않은 조건까지
    근거를 강제하면 정상 후보도 사라지고, 반대로 제품 근거 전체를 인정하면
    다른 제품의 사양 문서가 이 후보의 근거로 붙는다. v1.1 잔재인
    ``recommendation_profile`` 묶음 근거는 어느 조건에도 매핑하지 않는다.
    """

    fields = ["identity"]
    if conditions.use_case is not None or conditions.additional_use_cases:
        fields.append("recommended_use_cases")
    if conditions.task is not None or conditions.additional_tasks:
        fields.append("recommended_tasks")
    if conditions.performance_priority is not None:
        fields.append("performance_tier")
    if conditions.user_level == "beginner":
        fields.append("beginner_friendly")
    if conditions.wireless_required is True:
        fields.append("wireless")
    if conditions.camera_required is True or conditions.min_camera_connectors is not None:
        fields.append("camera_connector_count")
    if conditions.gpio_required is True:
        fields.append("gpio_header")
    if conditions.monitor_available is True or conditions.min_display_outputs is not None:
        fields.append("display_output_count")
    if conditions.ethernet_required is True:
        fields.append("ethernet")
    if conditions.remote_access_required is True:
        fields.extend(("wireless", "ethernet"))
    return tuple(dict.fromkeys(fields))


def candidate_condition_document_ids(
    candidate, conditions: ConditionPayload
) -> frozenset[str]:
    """후보의 조건 관련 필드만 뒷받침하는 공식 문서 ID를 모은다."""

    evidence = candidate.evidence_by_field
    return frozenset(
        document_id
        for field_name in condition_evidence_fields(conditions)
        for document_id in getattr(evidence, field_name)
    )


def result_supports_candidate(
    *,
    document_id: str,
    product_models,
    candidate,
    conditions: ConditionPayload,
) -> bool:
    """검색 결과 한 건이 이 후보의 조건 판단을 실제로 뒷받침하는지 본다.

    문서 ID가 후보의 조건 근거에 있어도, 그 청크가 이 제품을 다루지 않으면
    근거가 아니다. 두 조건을 모두 만족해야 후보·인용으로 인정한다.
    """

    if candidate.name not in product_models:
        return False
    return document_id in candidate_condition_document_ids(candidate, conditions)


def build_recommendation_chat_response(
    *,
    request_id: str,
    agent_result: RecommendationAgentResult,
    search_response: SearchResponse,
    language: str = "ko",
    answer: str | None = None,
    used_citation_ids: set[str] | None = None,
) -> ChatResponse:
    """공식 인용과 연결된 후보만 최종 공통 응답에 담는다.

    ``answer``가 없으면 기존의 결정적 카드 요약을 사용한다. 실제 Qwen 답변을
    전달할 때는 이미 검증한 ``used_citation_ids``도 함께 넘겨 출처 카드가
    모델 본문과 제품 카드 양쪽의 인용을 모두 포함하도록 한다.
    """

    decision = agent_result.decision
    common = {
        "schema_version": "1.2.0",
        "request_id": request_id,
        "language": language,
        "conditions": decision.conditions,
        "warnings": agent_result.warnings,
    }

    if decision.status.value == "needs_clarification":
        return ChatResponse(
            **common,
            status="needs_clarification",
            answer="제품을 추천하려면 추가 조건이 필요합니다.",
            citations=[],
            products=[],
            media=[],
            clarification_questions=decision.clarification_questions,
        )
    if decision.status.value == "out_of_scope":
        return ChatResponse(
            **common,
            status="out_of_scope",
            answer="이 요청은 제품 추천 범위가 아닙니다.",
            citations=[],
            products=[],
            media=[],
            clarification_questions=[],
        )
    if decision.status.value == "no_match":
        return ChatResponse(
            **common,
            status="insufficient_evidence",
            answer="현재 공식 제품 카탈로그에서 모든 필수 조건을 만족하는 후보를 찾지 못했습니다.",
            citations=[],
            products=[],
            media=[],
            clarification_questions=decision.clarification_questions,
        )

    contract_products: list[ProductRecommendation] = []
    answer_lines: list[str] = []
    response_citation_ids: set[str] = set(used_citation_ids or ())
    result_by_citation = {item.citation_id: item for item in search_response.results}

    for candidate in decision.candidates:
        citation_ids = [
            item.citation_id
            for item in search_response.results
            if result_supports_candidate(
                document_id=item.document_id,
                product_models=item.product_models,
                candidate=candidate,
                conditions=decision.conditions,
            )
        ]
        if not citation_ids:
            continue
        response_citation_ids.update(citation_ids)
        recommendation = ", ".join(candidate.matched_conditions) or "입력 조건 충족"
        limitations = list(candidate.tradeoffs)
        limitations.extend(
            f"필수 구성품: {accessory}" for accessory in candidate.required_accessories
        )
        limitations.extend(
            f"조건부 구성품({accessory.condition}): {accessory.item}"
            for accessory in candidate.conditional_accessories
        )
        contract_products.append(
            ProductRecommendation(
                product_id=candidate.product_id,
                product_model=candidate.name,
                recommendation=recommendation,
                matched_conditions=candidate.matched_conditions,
                limitations=limitations,
                citation_ids=citation_ids,
                product_url=candidate.product_url,
                image_url=candidate.image_url,
            )
        )
        if answer is None:
            answer_lines.append(f"{candidate.name}: {recommendation} [{citation_ids[0]}]")

    if not contract_products:
        return ChatResponse(
            **common,
            status="insufficient_evidence",
            answer="추천 후보는 찾았지만 이를 뒷받침하는 공식 검색 근거가 부족합니다.",
            citations=[],
            products=[],
            media=[],
            clarification_questions=[],
        )

    citations = [
        _citation(result_by_citation[citation_id])
        for citation_id in result_by_citation
        if citation_id in response_citation_ids
    ]
    return ChatResponse(
        **common,
        status="answered",
        answer=answer if answer is not None else "\n".join(answer_lines),
        citations=citations,
        products=contract_products,
        # Product card images remain in ProductRecommendation.image_url.
        # ChatResponse.media is reserved for citation-linked guide media.
        media=[],
        clarification_questions=[],
    )


__all__ = [
    "build_recommendation_chat_response",
    "candidate_condition_document_ids",
    "condition_evidence_fields",
    "result_supports_candidate",
]
