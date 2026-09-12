from src.contracts import QuizChoice, QuizQuestion
from src.services.quiz_validation import validate_question_structure


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
