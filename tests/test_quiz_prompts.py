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


def test_quiz_repair_prompt_calls_out_the_known_json_structure_failures() -> None:
    messages = build_quiz_generation_messages(make_request(), repair=True)

    system_prompt = messages[0]["content"]
    assert "이전 출력은 JSON 계약을 통과하지 못했습니다" in system_prompt
    assert '"choices" 배열은 네 번째 선택지 객체 뒤에서 `]`로 닫으세요' in system_prompt
    assert "마지막 항목 뒤에는 쉼표를 쓰지 마세요" in system_prompt
    assert '"correct_choice_id"' in system_prompt


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
    assert "evidence_ids에는 허용된 evidence ID 하나만" in QUIZ_GENERATION_SYSTEM_PROMPT
    assert "supporting_quote_id에는" in QUIZ_GENERATION_SYSTEM_PROMPT
    assert "supporting_quotes 필드를 출력하지 마세요" in QUIZ_GENERATION_SYSTEM_PROMPT
    assert '"supporting_quote_id": "C1-Q1"' in QUIZ_GENERATION_SYSTEM_PROMPT


def test_quiz_system_prompt_requires_grounded_explanation_and_single_answer_choices() -> None:
    assert "explanation은 선택한 quote 후보와 answer의 범위를 넘어서면 안 됩니다" in QUIZ_GENERATION_SYSTEM_PROMPT
    assert "선택지 4개" in QUIZ_GENERATION_SYSTEM_PROMPT
    assert '"옳지 않은 것은", "틀린 것은", "모두 고르시오"' in QUIZ_GENERATION_SYSTEM_PROMPT


def test_quiz_system_prompt_forbids_external_knowledge_and_duplicate_questions() -> None:
    assert "모델의 사전 지식, 추측, 일반 정보는 사용하지 마세요" in QUIZ_GENERATION_SYSTEM_PROMPT
    assert "기본적으로 1문항을 만들고" in QUIZ_GENERATION_SYSTEM_PROMPT
    assert "문항 수를 채우려고 같은 사실을 표현만 바꿔 반복하지 마세요" in QUIZ_GENERATION_SYSTEM_PROMPT
    assert "제공된 자료만으로 오답임을 판단할 수 있어야 하며" in QUIZ_GENERATION_SYSTEM_PROMPT
