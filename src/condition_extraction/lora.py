"""Base와 같은 프롬프트에 학습된 QLoRA adapter를 결합해 추론한다."""

from __future__ import annotations
from collections.abc import Callable

from .extractor import DEFAULT_MODEL_ID, HuggingFaceConditionExtractor
from src.contracts import ConditionPayload

from .schema import SurveyResponse


class LoraConditionExtractor(HuggingFaceConditionExtractor):
    """QLoRA adapter를 적용하며 실패 시 Base fallback도 지원하는 추출기다."""

    def __init__(
        self,
        adapter_path: str,
        *,
        model_id: str = DEFAULT_MODEL_ID,
        load_in_4bit: bool = True,
        device: str = "auto",
    ) -> None:
        """adapter 경로를 검증하고 Base 모델 위에 LoRA를 로드한다."""

        if not adapter_path.strip():
            raise ValueError("adapter_path가 필요합니다.")
        super().__init__(
            model_id=model_id,
            adapter_path=adapter_path,
            include_few_shots=True,
            load_in_4bit=load_in_4bit,
            device=device,
        )

    def extract_without_adapter(
        self, survey: SurveyResponse, *, cancel_requested: Callable[[], bool] | None = None
    ) -> ConditionPayload:
        """모델을 중복 로드하지 않고 adapter만 꺼서 Base fallback을 수행한다."""

        with self.model.disable_adapter():
            return self.extract(survey, cancel_requested=cancel_requested)
