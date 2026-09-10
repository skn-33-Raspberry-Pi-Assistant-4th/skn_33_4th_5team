import pytest

from src.contracts.input_limits import MAX_INPUT_CHARS, validate_input_text
from src.condition_extraction.schema import SurveyAnswer, SurveyResponse
from src.condition_extraction.prompts import build_inference_messages
from src.recommendation.engine import ProductRecommender
from src.condition_extraction.ui_input import RecommendationFormInput
from src.services.recommendation_response import condition_evidence_fields
from tests.test_recommendation_agent import catalog, conditions


def test_long_input_preserves_final_requirement():
    text = "홈 서버를 만들고 싶습니다. " * 300 + "마지막 조건: 유선 LAN 필수"
    survey = SurveyResponse(answers=[SurveyAnswer(question_id="purpose", question="목적?", answer=text)])
    assert build_inference_messages(survey)[-1]["content"].endswith(text)


@pytest.mark.parametrize("text", ["", "   ", "가" * (MAX_INPUT_CHARS + 1)], ids=["empty", "blank", "too-long"])
def test_invalid_lengths(text):
    with pytest.raises(ValueError):
        validate_input_text(text)
    with pytest.raises(ValueError):
        SurveyAnswer(question_id="purpose", question="목적?", answer=text)


def test_maximum_input_and_trim():
    assert validate_input_text("  " + "가" * MAX_INPUT_CHARS + "  ") == "가" * MAX_INPUT_CHARS


def test_new_hard_conditions_filter_by_actual_capabilities():
    request = conditions(ethernet_required=True, min_camera_connectors=2, min_display_outputs=2)
    for product in catalog().products:
        failures = ProductRecommender._hard_failures(product, request)
        assert ("ethernet" in failures) == (not product.capabilities.ethernet)
        assert ("camera connector count" in failures) == (product.capabilities.camera_connector_count < 2)
        assert ("display output count" in failures) == (product.capabilities.display_output_count < 2)


def test_unverified_requirements_are_visible_in_candidate():
    product = catalog().products[0]
    candidate = ProductRecommender._score(product, conditions(unverified_requirements=["예산 10만원"]))
    assert "충족 여부 확인 필요: 예산 10만원" in candidate.tradeoffs


def test_additional_purpose_changes_ranking_without_duplicate_points():
    product = catalog().products[0]
    purpose = product.recommendation_profile.recommended_use_cases[0]
    base = conditions(use_case=None)
    expanded = conditions(use_case=None, additional_use_cases=[purpose, purpose])
    assert ProductRecommender._score(product, expanded).score == ProductRecommender._score(product, base).score + 10


def test_unselected_form_fields_preserve_extracted_conditions():
    form = RecommendationFormInput(request_id="short", free_text="카메라를 만들고 싶어요")
    extracted = conditions(camera_required=True, wireless_required=True, monitor_available=False)
    assert len(form.to_survey().answers) == 1
    assert form.apply_explicit_values(extracted) == extracted


def test_explicit_false_is_different_from_unselected():
    form = RecommendationFormInput(request_id="explicit", free_text="홈 서버", wireless_required=False)
    assert form.apply_explicit_values(conditions(wireless_required=True)).wireless_required is False
    assert form.to_survey().answers[-1].answer == "아니요"


@pytest.mark.parametrize("use_case", ["home_server", "camera_monitoring", "smart_farm_monitoring", "education_coding"])
def test_purpose_alone_is_enough_to_recommend(use_case):
    from pathlib import Path
    from src.recommendation.schema import ProductCatalog

    real_catalog = ProductCatalog.model_validate_json(Path("data/products/catalog.json").read_text(encoding="utf-8"))
    minimal = conditions(use_case=use_case, task=None, performance_priority=None, user_level=None,
                         wireless_required=None, camera_required=None, gpio_required=None,
                         monitor_available=None, remote_access_required=None)
    decision = ProductRecommender(real_catalog).recommend(minimal)
    assert decision.status.value == "recommended"
    assert decision.candidates


def test_new_conditions_require_their_field_evidence():
    request = conditions(use_case=None, task=None, ethernet_required=True,
                         min_camera_connectors=2, min_display_outputs=2,
                         additional_use_cases=["home_server"], additional_tasks=["server_operation"])
    fields = condition_evidence_fields(request)
    assert {"ethernet", "camera_connector_count", "display_output_count", "recommended_use_cases", "recommended_tasks"} <= set(fields)


@pytest.mark.parametrize("text", ["", " " * 3, "가" * (MAX_INPUT_CHARS + 1)], ids=["empty", "blank", "too-long"])
def test_invalid_service_input_returns_contract_without_invoking_dependencies(text):
    from unittest.mock import Mock
    from src.services.rag_qa_service import RagQaService
    from src.services.recommendation_rag_service import RecommendationRagService

    dependency = Mock()
    qa = RagQaService(retriever=dependency, answer_generator=dependency)
    recommendation = RecommendationRagService(recommendation_agent=dependency, retriever=dependency, metadata_by_chunk_id={})
    for response in (
        qa.answer(request_id="qa-length", question=text, retrieval_mode="hybrid"),
        recommendation.answer(request_id="recommend-length", question=text),
    ):
        assert response.status == "needs_clarification"
        assert response.clarification_questions
        assert "input_length_invalid" in response.warnings
    assert not dependency.mock_calls


def test_old_condition_payload_still_parses_without_new_fields():
    from tests.test_condition_extraction import condition_payload
    from src.contracts import ConditionPayload

    legacy = ConditionPayload.model_validate(condition_payload())
    assert legacy.additional_use_cases == []
    assert legacy.additional_tasks == []
    assert legacy.ethernet_required is None
    assert legacy.min_camera_connectors is None
    assert legacy.min_display_outputs is None
    assert legacy.unverified_requirements == []
