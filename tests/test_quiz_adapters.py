from datetime import date

from src.contracts import ChatCitation, ChatResponse
from src.services.quiz_adapters import chat_response_to_quiz_request


def citation(*, citation_id: str, chunk_id: str, quote: str) -> ChatCitation:
    return ChatCitation(
        citation_id=citation_id,
        document_id=f"document-{citation_id}",
        chunk_id=chunk_id,
        title="Raspberry Pi documentation",
        publisher="Raspberry Pi Ltd",
        section="Remote access",
        source_url="https://www.raspberrypi.com/documentation/",
        source_anchor=None,
        document_version="commit-abc",
        published_at=None,
        updated_at=None,
        collected_at=date(2026, 9, 12),
        license="CC BY-SA 4.0",
        quote=quote,
    )


def answered_response(*, citations: list[ChatCitation]) -> ChatResponse:
    citation_suffix = " ".join(f"[{item.citation_id}]" for item in citations)
    return ChatResponse(
        schema_version="1.2.0",
        request_id="qa-request-001",
        status="answered",
        language="ko",
        answer=f"SSH는 기본적으로 비활성화되어 있습니다. {citation_suffix}",
        conditions=None,
        citations=citations,
        products=[],
        media=[],
        clarification_questions=[],
        warnings=[],
    )


def test_adapter_copies_final_citation_evidence_in_order() -> None:
    first = citation(
        citation_id="C1",
        chunk_id="ssh-001",
        quote="Raspberry Pi OS disables SSH by default.",
    )
    second = citation(
        citation_id="C2",
        chunk_id="ssh-002",
        quote="Enable SSH in Raspberry Pi Imager.",
    )

    request = chat_response_to_quiz_request(answered_response(citations=[first, second]))

    assert request is not None
    assert request.answer == "SSH는 기본적으로 비활성화되어 있습니다. [C1] [C2]"
    assert len(request.evidence) == 2
    assert [item.citation_id for item in request.evidence] == ["C1", "C2"]
    assert [item.document_id for item in request.evidence] == ["document-C1", "document-C2"]
    assert [item.chunk_id for item in request.evidence] == ["ssh-001", "ssh-002"]
    assert [item.content for item in request.evidence] == [first.quote, second.quote]


def test_adapter_preserves_requested_question_limit() -> None:
    response = answered_response(
        citations=[citation(citation_id="C1", chunk_id="ssh-001", quote="SSH is disabled by default.")]
    )

    request = chat_response_to_quiz_request(response, max_questions=1)

    assert request is not None
    assert request.max_questions == 1


def test_adapter_skips_non_answered_response() -> None:
    response = ChatResponse(
        schema_version="1.2.0",
        request_id="qa-request-002",
        status="insufficient_evidence",
        language="ko",
        answer="근거가 부족합니다.",
        conditions=None,
        citations=[],
        products=[],
        media=[],
        clarification_questions=[],
        warnings=[],
    )

    assert chat_response_to_quiz_request(response) is None


def test_adapter_skips_answered_response_without_citations() -> None:
    response = ChatResponse.model_construct(
        request_id="qa-request-003",
        status="answered",
        answer="비정상 응답입니다.",
        citations=[],
    )

    assert chat_response_to_quiz_request(response) is None
