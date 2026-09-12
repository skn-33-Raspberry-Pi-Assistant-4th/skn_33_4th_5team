import pytest

from src.contracts import QuizEvidence, QuizGenerationRequest
from src.lang import QUIZ_GENERATION_SYSTEM_PROMPT, build_quiz_generation_messages


def make_request(**overrides: object) -> QuizGenerationRequest:
    values: dict[str, object] = {
        "request_id": "request-001",
        "answer": "SSH는 기본적으로 비활성화되어 있습니다. [C1]",
        "evidence": [
            QuizEvidence(
                citation_id="C1",
                document_id="computers-remote-access-ssh",
                chunk_id="computers-remote-access-ssh-001",
                content="Raspberry Pi OS disables SSH by default.",
            )
        ],
        "max_questions": 3,
    }
    values.update(overrides)
    return QuizGenerationRequest(**values)


def test_quiz_prompt_includes_answer() -> None:
    messages = build_quiz_generation_messages(make_request())

    assert "SSH는 기본적으로 비활성화되어 있습니다. [C1]" in messages[1]["content"]


def test_quiz_prompt_includes_citation_document_chunk_and_content() -> None:
    messages = build_quiz_generation_messages(make_request())
    prompt = messages[1]["content"]

    assert 'citation_id="C1"' in prompt
    assert 'document_id="computers-remote-access-ssh"' in prompt
    assert 'chunk_id="computers-remote-access-ssh-001"' in prompt
    assert "Raspberry Pi OS disables SSH by default." in prompt


def test_quiz_prompt_lists_only_allowed_evidence_ids() -> None:
    messages = build_quiz_generation_messages(make_request())

    assert "<allowed_evidence_ids>\nC1\n</allowed_evidence_ids>" in messages[1]["content"]


def test_quiz_prompt_rejects_duplicate_evidence_ids() -> None:
    duplicate = QuizEvidence(
        citation_id="C1",
        document_id="computers-remote-access-ssh",
        chunk_id="computers-remote-access-ssh-002",
        content="Enable SSH in Raspberry Pi Imager.",
    )

    with pytest.raises(ValueError, match="중복된 인용 ID"):
        build_quiz_generation_messages(make_request(evidence=[*make_request().evidence, duplicate]))


def test_quiz_prompt_reflects_requested_question_limit() -> None:
    messages = build_quiz_generation_messages(make_request(max_questions=2))

    assert "최대 2개의 미니 챌린지" in messages[1]["content"]


def test_quiz_prompt_escapes_html_special_characters_in_answer_and_evidence() -> None:
    messages = build_quiz_generation_messages(
        make_request(
            answer="<answer> & <script>alert('x')</script>",
            evidence=[
                QuizEvidence(
                    citation_id="C1",
                    document_id='doc<&"',
                    chunk_id='chunk<&"',
                    content="<evidence> & <script>alert('x')</script>",
                )
            ],
        )
    )
    prompt = messages[1]["content"]

    assert "&lt;answer&gt; &amp; &lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in prompt
    assert 'document_id="doc&lt;&amp;&quot;"' in prompt
    assert 'chunk_id="chunk&lt;&amp;&quot;"' in prompt
    assert "&lt;evidence&gt; &amp; &lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in prompt


def test_quiz_system_prompt_requires_answer_evidence_intersection_and_single_evidence() -> None:
    assert "<answer>에 명시적으로 있는 사실만 확인" in QUIZ_GENERATION_SYSTEM_PROMPT
    assert "evidence에만 있거나 answer에만 있는 사실은 출제하지 마세요" in QUIZ_GENERATION_SYSTEM_PROMPT
    assert "evidence_ids에 허용된 evidence ID 하나만" in QUIZ_GENERATION_SYSTEM_PROMPT
    assert "supporting_quotes에는 그 evidence 원문에서 연속된 문자열" in QUIZ_GENERATION_SYSTEM_PROMPT


def test_quiz_system_prompt_requires_grounded_explanation_and_single_answer_choices() -> None:
    assert "정답과 explanation을 직접 뒷받침" in QUIZ_GENERATION_SYSTEM_PROMPT
    assert "explanation은 그 범위를 넘어서면 안 됩니다" in QUIZ_GENERATION_SYSTEM_PROMPT
    assert "선택지 4개" in QUIZ_GENERATION_SYSTEM_PROMPT
    assert '"옳지 않은 것은", "틀린 것은", "모두 고르시오"' in QUIZ_GENERATION_SYSTEM_PROMPT


def test_quiz_system_prompt_forbids_external_knowledge_and_duplicate_questions() -> None:
    assert "모델의 사전 지식, 추측, 일반 정보는 사용하지 마세요" in QUIZ_GENERATION_SYSTEM_PROMPT
    assert "같은 핵심 사실을 표현만 바꿔 여러 문항으로 반복하지 마세요" in QUIZ_GENERATION_SYSTEM_PROMPT
    assert "제공된 자료만으로 오답임을 판단할 수 있어야 하며" in QUIZ_GENERATION_SYSTEM_PROMPT
