"""설문 조건 추출과 결정적 제품 추천을 순서대로 조정하는 제한형 Agent다."""

from __future__ import annotations

from enum import Enum
from collections.abc import Callable

from pydantic import Field

from src.condition_extraction.extractor import ConditionExtractor
from src.condition_extraction.schema import SurveyResponse
from src.condition_extraction.ui_input import RecommendationFormInput
from src.contracts import ConditionPayload
from src.contracts.models import StrictContract
from src.recommendation.engine import ProductRecommender
from src.recommendation.schema import RecommendationDecision
from src.rag_to_llm.cancellation import GenerationCancelled, call_cancellable


class ExtractorMode(str, Enum):
    """주 추출기·Base fallback·확인 질문 fallback 실행 상태다."""

    PRIMARY = "primary"
    BASE_FALLBACK = "base_fallback"
    CLARIFICATION_FALLBACK = "clarification_fallback"


class RecommendationAgentResult(StrictContract):
    """RAG 근거와 결합하기 전 UI 독립적인 추천 결과다."""

    decision: RecommendationDecision
    extractor_mode: ExtractorMode
    warnings: list[str] = Field(default_factory=list)


class RecommendationAgent:
    """조건 추출기와 결정적 추천 엔진만 사용해 안전한 흐름을 관리한다."""

    def __init__(
        self,
        *,
        extractor: ConditionExtractor,
        recommender: ProductRecommender,
        fallback_extractor: ConditionExtractor | None = None,
    ) -> None:
        """주 추출기·추천기와 선택적인 Base fallback 추출기를 연결한다."""

        self.extractor = extractor
        self.recommender = recommender
        self.fallback_extractor = fallback_extractor

    def recommend(self, survey: SurveyResponse, *, cancel_requested: Callable[[], bool] | None = None) -> RecommendationAgentResult:
        """일반 설문을 조건으로 추출한 뒤 제품 추천 결과를 반환한다."""

        conditions, mode, warnings = self._extract_conditions(survey, cancel_requested=cancel_requested)
        return self._result(conditions, mode, warnings)

    def recommend_form(
        self, form: RecommendationFormInput, *, cancel_requested: Callable[[], bool] | None = None
    ) -> RecommendationAgentResult:
        """Streamlit 입력을 분석하고 명시적 위젯값을 우선해 추천한다."""

        conditions, mode, warnings = self._extract_conditions(form.to_survey(), cancel_requested=cancel_requested)
        conditions = form.apply_explicit_values(conditions)
        return self._result(conditions, mode, warnings)

    def _result(
        self,
        conditions: ConditionPayload,
        mode: ExtractorMode,
        warnings: list[str],
    ) -> RecommendationAgentResult:
        """추출기 실행 상태와 경고를 추천 결정과 하나의 결과로 묶는다."""

        return RecommendationAgentResult(
            decision=self.recommender.recommend(conditions),
            extractor_mode=mode,
            warnings=warnings,
        )

    def _extract_conditions(
        self, survey: SurveyResponse, *, cancel_requested: Callable[[], bool] | None = None
    ) -> tuple[ConditionPayload, ExtractorMode, list[str]]:
        """주 추출기를 호출하고 실패하면 경고를 남긴 뒤 fallback으로 넘긴다."""

        warnings: list[str] = []
        try:
            return call_cancellable(self.extractor.extract, survey, cancel_requested=cancel_requested), ExtractorMode.PRIMARY, warnings
        except GenerationCancelled:
            raise
        except Exception as primary_error:
            warnings.append(f"기본 조건 추출 실패: {type(primary_error).__name__}")
            conditions, mode = self._fallback(survey, warnings, cancel_requested=cancel_requested)
            return conditions, mode, warnings

    def _fallback(
        self, survey: SurveyResponse, warnings: list[str], *, cancel_requested: Callable[[], bool] | None = None
    ) -> tuple[ConditionPayload, ExtractorMode]:
        """Base 추출을 차례로 시도하고 모두 실패하면 안전한 확인 질문을 만든다."""

        if self.fallback_extractor is not None:
            try:
                return (
                    call_cancellable(self.fallback_extractor.extract, survey, cancel_requested=cancel_requested),
                    ExtractorMode.BASE_FALLBACK,
                )
            except GenerationCancelled:
                raise
            except Exception as fallback_error:
                warnings.append(
                    f"Few-shot fallback 실패: {type(fallback_error).__name__}"
                )

        extract_without_adapter = getattr(self.extractor, "extract_without_adapter", None)
        if callable(extract_without_adapter):
            try:
                return (
                    call_cancellable(extract_without_adapter, survey, cancel_requested=cancel_requested),
                    ExtractorMode.BASE_FALLBACK,
                )
            except GenerationCancelled:
                raise
            except Exception as fallback_error:
                warnings.append(
                    "동일 모델의 adapter 해제 fallback 실패: "
                    f"{type(fallback_error).__name__}"
                )

        return (
            ConditionPayload(
                schema_version="1.1.0",
                intent="product_recommendation",
                use_case=None,
                product_models=None,
                os_versions=None,
                task=None,
                performance_priority=None,
                wireless_required=None,
                camera_required=None,
                gpio_required=None,
                monitor_available=None,
                remote_access_required=None,
                user_level=None,
                needs_clarification=True,
                clarification_questions=[
                    "사용 목적과 반드시 필요한 연결 기능을 다시 알려 주세요."
                ],
            ),
            ExtractorMode.CLARIFICATION_FALLBACK,
        )
