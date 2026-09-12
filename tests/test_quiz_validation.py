from src.contracts import QuizChoice, QuizEvidence, QuizQuestion
from src.services.quiz_validation import (
    supporting_quote_matches,
    validate_question_evidence,
    validate_question_structure,
)


def question_with(**overrides: object) -> QuizQuestion:
    payload: dict[str, object] = {
        "question_id": "generated-001",
        "question": "SSH의 기본 상태는 무엇인가요?",
        "choices": [
            QuizChoice(id="A", text="기본적으로 비활성화"),
            QuizChoice(id="B", text="기본적으로 활성화"),
            QuizChoice(id="C", text="설치 중에만 활성화"),
            QuizChoice(id="D", text="네트워크 연결에 따라 달라짐"),
        ],
        "correct_choice_id": "A",
        "explanation": "공식 문서는 SSH가 기본적으로 비활성화된다고 설명합니다.",
        "evidence_ids": ["C1"],
        "supporting_quotes": ["Raspberry Pi OS disables SSH by default."],
    }
    payload.update(overrides)
    return QuizQuestion.model_construct(**payload)


def evidence_by_id() -> dict[str, QuizEvidence]:
    evidence = QuizEvidence(
        citation_id="C1",
        document_id="computers-remote-access-ssh",
        chunk_id="computers-remote-access-ssh-001",
        content="Raspberry Pi OS disables SSH by default.",
    )
    return {evidence.citation_id: evidence}


def test_question_structure_accepts_a_valid_four_choice_question() -> None:
    assert validate_question_structure(question_with()) == []


def test_question_structure_rejects_three_choices() -> None:
    question = question_with(choices=question_with().choices[:3])

    assert "choices_count_must_be_4" in validate_question_structure(question)


def test_question_structure_rejects_duplicate_choice_ids() -> None:
    question = question_with(
        choices=[
            QuizChoice(id="A", text="첫 번째 보기"),
            QuizChoice(id="A", text="두 번째 보기"),
            QuizChoice(id="C", text="세 번째 보기"),
            QuizChoice(id="D", text="네 번째 보기"),
        ]
    )

    assert "choice_ids_must_be_A_B_C_D_once_each" in validate_question_structure(question)


def test_question_structure_rejects_choice_ids_outside_a_to_d() -> None:
    invalid_choice = QuizChoice.model_construct(id="E", text="잘못된 ID 보기")
    question = question_with(choices=[*question_with().choices[:3], invalid_choice])

    assert "choice_ids_must_be_A_B_C_D_once_each" in validate_question_structure(question)


def test_question_structure_rejects_missing_correct_choice() -> None:
    question = question_with(
        correct_choice_id="D",
        choices=question_with().choices[:3],
    )

    assert "correct_choice_id_must_match_a_choice" in validate_question_structure(question)


def test_question_structure_rejects_duplicate_choice_text() -> None:
    question = question_with(
        choices=[
            QuizChoice(id="A", text="같은 보기"),
            QuizChoice(id="B", text="같은 보기"),
            QuizChoice(id="C", text="세 번째 보기"),
            QuizChoice(id="D", text="네 번째 보기"),
        ]
    )

    assert "choice_texts_must_be_unique" in validate_question_structure(question)


def test_question_structure_rejects_blank_question_explanation_and_choice_text() -> None:
    question = question_with(
        question="  ",
        explanation="\n",
        choices=[
            QuizChoice(id="A", text="  "),
            QuizChoice(id="B", text="두 번째 보기"),
            QuizChoice(id="C", text="세 번째 보기"),
            QuizChoice(id="D", text="네 번째 보기"),
        ],
    )

    errors = validate_question_structure(question)

    assert "question_must_not_be_blank" in errors
    assert "explanation_must_not_be_blank" in errors
    assert "choice_text_must_not_be_blank" in errors


def test_question_evidence_accepts_one_allowed_evidence_id_and_quote() -> None:
    assert validate_question_evidence(question_with(), evidence_by_id()) == []


def test_question_evidence_rejects_unknown_evidence_id() -> None:
    errors = validate_question_evidence(question_with(evidence_ids=["C9"]), evidence_by_id())

    assert "evidence_ids_must_be_allowed" in errors


def test_question_evidence_rejects_missing_evidence_id() -> None:
    errors = validate_question_evidence(question_with(evidence_ids=[]), evidence_by_id())

    assert "evidence_ids_must_contain_exactly_one" in errors


def test_question_evidence_rejects_missing_supporting_quote() -> None:
    errors = validate_question_evidence(question_with(supporting_quotes=[]), evidence_by_id())

    assert "supporting_quotes_must_contain_exactly_one" in errors


def test_question_evidence_rejects_multiple_evidence_ids() -> None:
    allowed_evidence = evidence_by_id()
    allowed_evidence["C2"] = QuizEvidence(
        citation_id="C2",
        document_id="computers-remote-access-ssh",
        chunk_id="computers-remote-access-ssh-002",
        content="Enable SSH in Raspberry Pi Imager.",
    )
    errors = validate_question_evidence(
        question_with(
            evidence_ids=["C1", "C2"],
            supporting_quotes=["첫 번째 근거", "두 번째 근거"],
        ),
        allowed_evidence,
    )

    assert "evidence_ids_must_contain_exactly_one" in errors
    assert "supporting_quotes_must_contain_exactly_one" in errors
    assert "evidence_ids_must_be_allowed" not in errors


def test_supporting_quote_matches_exact_evidence_sentence() -> None:
    assert supporting_quote_matches(
        "Raspberry Pi OS disables SSH by default.",
        "Raspberry Pi OS disables SSH by default. Enable SSH in Imager.",
    )


def test_supporting_quote_matches_when_only_line_breaks_differ() -> None:
    assert supporting_quote_matches(
        "Raspberry Pi OS disables SSH by default.",
        "Raspberry Pi OS\ndisables SSH by default.",
    )


def test_supporting_quote_matches_when_only_whitespace_differs() -> None:
    assert supporting_quote_matches(
        "  Raspberry Pi OS disables   SSH by default.  ",
        "Raspberry Pi OS disables SSH by default.",
    )


def test_supporting_quote_rejects_text_outside_evidence() -> None:
    assert not supporting_quote_matches(
        "Raspberry Pi OS enables SSH by default.",
        "Raspberry Pi OS disables SSH by default.",
    )


def test_supporting_quote_rejects_too_short_text() -> None:
    assert not supporting_quote_matches("SSH", "SSH is disabled by default.")


def test_supporting_quote_rejects_too_long_text() -> None:
    quote = "a" * 241
    assert not supporting_quote_matches(quote, quote)


def test_question_evidence_rejects_quote_missing_from_its_evidence_body() -> None:
    errors = validate_question_evidence(
        question_with(supporting_quotes=["Raspberry Pi OS enables SSH by default."]),
        evidence_by_id(),
    )

    assert "supporting_quote_must_match_evidence_content" in errors
