"""Base와 LoRA가 함께 쓰는 Hugging Face 조건 추출 인터페이스를 구현한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from collections.abc import Callable

from .parser import parse_condition_output
from .prompts import build_inference_messages
from src.contracts import ConditionPayload
from src.model_runtime import InferenceDeviceError, resolve_inference_runtime
from src.rag_to_llm.cancellation import GenerationCancelled, raise_if_cancelled

from .schema import SurveyResponse


DEFAULT_MODEL_ID = "Qwen/Qwen3-4B-Instruct-2507"


class ConditionExtractor(Protocol):
    """Agent가 추출기 구현 종류와 무관하게 호출할 공통 인터페이스다."""

    def extract(self, survey: SurveyResponse, *, cancel_requested: Callable[[], bool] | None = None) -> ConditionPayload:
        """설문 답변을 팀 공통 조건 스키마로 변환한다."""


@dataclass(frozen=True)
class ExtractionResult:
    """검증된 조건과 오류 분석용 원본 모델 출력을 함께 보관한다."""

    conditions: ConditionPayload
    raw_output: str


class HuggingFaceConditionExtractor:
    """선택적 PEFT adapter와 고정 프롬프트로 조건 JSON을 생성한다."""

    def __init__(
        self,
        *,
        model_id: str = DEFAULT_MODEL_ID,
        adapter_path: str | None = None,
        include_few_shots: bool = True,
        load_in_4bit: bool = True,
        device: str = "auto",
        max_new_tokens: int = 2048,
    ) -> None:
        """모델·tokenizer를 로드하고 필요하면 4-bit 양자화와 LoRA를 적용한다."""

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "모델 추론 패키지가 없습니다. requirements-training.txt를 설치하세요."
            ) from exc

        try:
            runtime = resolve_inference_runtime(
                torch,
                requested_device=device,
                load_in_4bit=load_in_4bit,
            )
        except InferenceDeviceError as exc:
            raise RuntimeError(str(exc)) from exc

        self.model_id = model_id
        self.adapter_path = adapter_path
        self.include_few_shots = include_few_shots
        self.max_new_tokens = max_new_tokens
        self.device = runtime.device
        self.load_in_4bit = runtime.load_in_4bit
        self.tokenizer = AutoTokenizer.from_pretrained(adapter_path or model_id)
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        model_kwargs: dict[str, object] = {"torch_dtype": runtime.dtype}
        if runtime.device == "cuda":
            model_kwargs["device_map"] = "auto"
        if runtime.load_in_4bit:
            from transformers import BitsAndBytesConfig

            model_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
            )

        model = AutoModelForCausalLM.from_pretrained(model_id, **model_kwargs)
        if runtime.device != "cuda":
            model.to(runtime.device)
        if adapter_path:
            try:
                from peft import PeftModel
            except ImportError as exc:
                raise RuntimeError("LoRA 추론에는 peft 패키지가 필요합니다.") from exc
            model = PeftModel.from_pretrained(model, adapter_path)
        model.eval()
        self.model = model

    def extract_with_raw(self, survey: SurveyResponse, *, cancel_requested: Callable[[], bool] | None = None) -> ExtractionResult:
        """결정적 생성 후 원문과 스키마 검증을 통과한 조건을 함께 반환한다."""

        import torch

        raise_if_cancelled(cancel_requested)

        messages = build_inference_messages(
            survey, include_few_shots=self.include_few_shots
        )
        encoded = self.tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        )
        encoded = encoded.to(getattr(self.model, "device", self.device))
        prompt_length = encoded["input_ids"].shape[-1]
        context_limit = getattr(self.model.config, "max_position_embeddings", None)
        if context_limit and prompt_length + self.max_new_tokens > context_limit:
            raise ValueError("모델 문맥 한도를 초과했습니다. 입력을 줄여 주세요. 원문은 자동으로 자르지 않습니다.")
        generation_kwargs = {}
        if cancel_requested is not None:
            from transformers import StoppingCriteria, StoppingCriteriaList

            class CancelWhenRequested(StoppingCriteria):
                cancelled = False

                def __call__(self, input_ids, scores, **kwargs):
                    self.cancelled = self.cancelled or cancel_requested()
                    return self.cancelled

            cancellation = CancelWhenRequested()
            generation_kwargs["stopping_criteria"] = StoppingCriteriaList([cancellation])
        raise_if_cancelled(cancel_requested)
        with torch.inference_mode():
            output_ids = self.model.generate(
                **encoded,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id,
                **generation_kwargs,
            )
        if cancel_requested is not None and cancellation.cancelled:
            raise GenerationCancelled("조건 추출이 취소됐습니다.")
        raise_if_cancelled(cancel_requested)
        raw_output = self.tokenizer.decode(
            output_ids[0, prompt_length:], skip_special_tokens=True
        ).strip()
        return ExtractionResult(
            conditions=parse_condition_output(raw_output), raw_output=raw_output
        )

    def extract(self, survey: SurveyResponse, *, cancel_requested: Callable[[], bool] | None = None) -> ConditionPayload:
        """Agent가 사용할 검증 완료 조건 객체만 반환한다."""

        return self.extract_with_raw(survey, cancel_requested=cancel_requested).conditions
