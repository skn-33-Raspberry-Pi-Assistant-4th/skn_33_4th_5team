"""근거 기반 답변 생성기의 교체 가능한 계약과 구현을 제공한다."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
import re
from time import perf_counter
from typing import Mapping, Protocol, Sequence

from src.lang.prompts import PromptEvidence
from src.lang.safety import (
    AnswerSafetyError,
    INSUFFICIENT_EVIDENCE_MARKER,
    is_evidence_abstention,
    validate_grounded_answer,
)
from src.model_runtime import InferenceDeviceError, resolve_inference_runtime


class AnswerGenerationError(RuntimeError):
    """답변 모델을 준비하거나 생성하는 과정에서 발생한 명시적 오류다."""


@dataclass(frozen=True)
class GenerationResult:
    """답변 본문과 추론 provider 정보를 함께 전달하는 생성 결과다."""

    text: str
    provider: str
    model_id: str
    elapsed_ms: float
    attempts: int = 1

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("생성된 답변 본문은 비어 있을 수 없습니다.")
        if not self.provider.strip() or not self.model_id.strip():
            raise ValueError("생성 provider와 model_id는 비어 있을 수 없습니다.")
        if self.elapsed_ms < 0:
            raise ValueError("elapsed_ms cannot be negative.")


class AnswerGenerator(Protocol):
    """공식 근거 프롬프트를 받아 인용 가능한 답변을 생성하는 제공자 계약이다."""

    def generate(
        self,
        messages: Sequence[Mapping[str, str]],
        evidence: Sequence[PromptEvidence],
    ) -> GenerationResult:
        """인용 ID가 포함된 답변과 실행 정보를 반환한다."""


_URL_PATTERN = re.compile(r"(?i)(?:https?://|www\.)[^\s)>\]]+")
_CITATION_GROUP_PATTERN = re.compile(r"\[\s*(C[1-9][0-9]*(?:\s*,\s*C[1-9][0-9]*)*)\s*\]")
_MAX_STRUCTURED_NEW_TOKENS = 1024


def _normalize_citation_groups(answer: str) -> str:
    """공백·쉼표가 있는 인용만 정규화하며 명령어와 코드 원문은 보존한다."""

    pieces = re.split(r"(```[\s\S]*?```|`[^`]*`)", answer)
    for index in range(0, len(pieces), 2):
        pieces[index] = _CITATION_GROUP_PATTERN.sub(
            lambda match: " ".join(f"[{item.strip()}]" for item in match.group(1).split(",")),
            pieces[index],
        )
    return "".join(pieces)


class EvidenceTemplateGenerator:
    """실제 생성 LLM 없이 공식 원문 근거를 안전하게 표시하는 로컬 생성기."""

    provider = "template"
    model_id = "evidence-template"

    @staticmethod
    def _without_urls(content: str) -> str:
        """답변 본문에 URL을 넣지 않는 안전 정책에 맞춰 URL만 제거한다."""

        return _URL_PATTERN.sub("[원문 링크는 출처 카드 참조]", content).strip()

    def generate(
        self,
        messages: Sequence[Mapping[str, str]],
        evidence: Sequence[PromptEvidence],
    ) -> GenerationResult:
        """각 검색 청크를 자체 인용과 함께 출력한다."""

        if not messages or not evidence:
            raise ValueError("템플릿 답변에는 질문 메시지와 공식 근거가 필요합니다.")
        started_at = perf_counter()
        first_id = evidence[0].citation_id
        lines = [f"공식 문서에서 확인된 관련 근거입니다. [{first_id}]"]
        for item in evidence:
            # 검증기는 모든 비어 있지 않은 줄에 인용을 요구한다. 의미 단위 청크에는
            # 코드·표 등 여러 줄 본문이 포함될 수 있으므로, 로컬 템플릿에서는 한 줄로
            # 정규화해 근거와 인용의 1:1 관계를 유지한다.
            content = " ".join(self._without_urls(item.content).split())
            lines.append(f"- {content} [{item.citation_id}]")
        return GenerationResult(
            text="\n".join(lines),
            provider=self.provider,
            model_id=self.model_id,
            elapsed_ms=(perf_counter() - started_at) * 1000,
        )


class HuggingFaceAnswerGenerator:
    """선택된 CUDA·MPS·CPU 장치에서 Qwen Instruct를 호출하는 lazy 생성기.

    조건 JSON 추출용 LoRA adapter는 적용하지 않는다. 이 구현은 공식 검색 근거를
    받은 뒤에만 Qwen3-4B Base Instruct를 로드해 한국어 답변을 생성한다.
    """

    provider = "huggingface"

    def __init__(
        self,
        *,
        model_id: str,
        model_revision: str = "main",
        load_in_4bit: bool = True,
        max_new_tokens: int = 512,
        device: str = "auto",
    ) -> None:
        if not model_id.strip():
            raise ValueError("model_id must not be empty.")
        if not model_revision.strip():
            raise ValueError("model_revision must not be empty.")
        if not 1 <= max_new_tokens <= 512:
            raise ValueError("max_new_tokens must be between 1 and 512.")
        self.model_id = model_id
        self.model_revision = model_revision
        self.load_in_4bit = load_in_4bit
        self.max_new_tokens = max_new_tokens
        self.device = device
        self._model = None
        self._tokenizer = None
        self._torch = None

    @property
    def is_loaded(self) -> bool:
        """모델과 tokenizer가 선택된 추론 장치에 준비됐는지 반환한다."""

        return self._model is not None and self._tokenizer is not None and self._torch is not None

    def _load_model(self) -> None:
        """최초 생성 요청에서만 Transformers 의존성과 Base 모델을 준비한다."""

        if self.is_loaded:
            return
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise AnswerGenerationError(
                "Qwen QA 추론 패키지가 없습니다. "
                "`pip install -r requirements-gpu.txt`를 실행하세요."
            ) from exc

        try:
            runtime = resolve_inference_runtime(
                torch,
                requested_device=self.device,
                load_in_4bit=self.load_in_4bit,
            )
        except InferenceDeviceError as exc:
            raise AnswerGenerationError(str(exc)) from exc
        self.device = runtime.device
        self.load_in_4bit = runtime.load_in_4bit

        model_kwargs: dict[str, object] = {
            "revision": self.model_revision,
            "torch_dtype": runtime.dtype,
        }
        if runtime.device == "cuda":
            model_kwargs["device_map"] = "auto"
        if runtime.load_in_4bit:
            try:
                from transformers import BitsAndBytesConfig
            except ImportError as exc:
                raise AnswerGenerationError(
                    "CUDA 4-bit 추론에는 bitsandbytes가 필요합니다. "
                    "requirements-gpu.txt를 설치하세요."
                ) from exc
            model_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
            )
        try:
            tokenizer = AutoTokenizer.from_pretrained(
                self.model_id,
                revision=self.model_revision,
            )
            if tokenizer.pad_token_id is None:
                tokenizer.pad_token = tokenizer.eos_token
            model = AutoModelForCausalLM.from_pretrained(self.model_id, **model_kwargs)
            if runtime.device != "cuda":
                model.to(runtime.device)
            model.eval()
        except Exception as exc:
            raise AnswerGenerationError(
                f"Qwen 모델을 로드하지 못했습니다: {self.model_id}@{self.model_revision}. "
                "선택한 추론 장치, Hugging Face 접근 권한, HF_HOME cache를 확인하세요."
            ) from exc

        self._torch = torch
        self._tokenizer = tokenizer
        self._model = model

    @staticmethod
    def _prompt_length(input_ids: object) -> int:
        """Tensor와 테스트용 list 양쪽에서 입력 토큰 길이를 구한다."""

        shape = getattr(input_ids, "shape", None)
        if shape is not None:
            return int(shape[-1])
        return len(input_ids[0])  # type: ignore[index]

    @staticmethod
    def _completion_ids(output_ids: object, prompt_length: int) -> object:
        """모델 전체 출력에서 새로 생성된 토큰만 분리한다."""

        try:
            return output_ids[0, prompt_length:]  # type: ignore[index]
        except TypeError:
            return output_ids[0][prompt_length:]  # type: ignore[index]

    def generate(
        self,
        messages: Sequence[Mapping[str, str]],
        evidence: Sequence[PromptEvidence],
    ) -> GenerationResult:
        """같은 근거로 최대 두 번 생성하며 인용·형식 실패는 표시하지 않는다."""

        if not messages or not evidence:
            raise ValueError("Qwen 답변 생성에는 질문 메시지와 공식 근거가 필요합니다.")
        started_at = perf_counter()
        self._load_model()
        attempt_messages = list(messages)
        for attempt in range(2):
            answer = _normalize_citation_groups(self._generate_text(attempt_messages))
            # 모델이 독립된 보류 표식과 설명을 함께 썼다면 설명 전체를 버린다.
            # 혼합 답변을 검증 통과시키지 않고, 출처·주장이 없는 보류만 반환한다.
            if INSUFFICIENT_EVIDENCE_MARKER in {line.strip() for line in answer.splitlines()}:
                answer = INSUFFICIENT_EVIDENCE_MARKER
            if is_evidence_abstention(answer):
                break
            try:
                validate_grounded_answer(
                    answer,
                    allowed_citation_ids=[item.citation_id for item in evidence],
                    require_korean=True,
                )
                break
            except AnswerSafetyError as exc:
                if attempt == 1:
                    raise AnswerGenerationError(
                        "Qwen 답변이 두 차례 인용·형식 검사를 통과하지 못해 표시를 보류합니다."
                    ) from exc
                # 실패한 답변을 새 근거로 넣거나 인용을 서버가 임의로 붙이지 않는다.
                # 원래 질문·검색 근거는 그대로 유지하고 표시 형식만 재요청한다.
                attempt_messages = [*messages, {
                    "role": "user",
                    "content": (
                        "이전 생성은 인용·출력 형식 검사를 통과하지 못했습니다. "
                        "원래 질문과 제공된 공식 근거만 다시 검토하여 새로 답하세요. "
                        "서론·제목·맺음말·하위 목록 없이 최대 3개의 짧은 번호 항목만 쓰고, "
                        "각 항목을 완성된 한국어 문장과 허용된 인용 ID로 끝내세요. "
                        "URL이나 근거에 없는 명령어·사실을 추가하지 마세요. "
                        f"질문의 핵심 답을 근거에서 확인할 수 없으면 {INSUFFICIENT_EVIDENCE_MARKER} "
                        "한 줄만 출력하고 설명이나 인용을 덧붙이지 마세요."
                    ),
                }]
        return GenerationResult(
            text=answer,
            provider=self.provider,
            model_id=self.model_id,
            elapsed_ms=(perf_counter() - started_at) * 1000,
            attempts=attempt + 1,
        )

    def generate_structured(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        max_new_tokens: int,
    ) -> GenerationResult:
        """Generate one raw structured response without QA answer validation.

        Structured consumers own their JSON parsing and evidence validation.
        This method deliberately bypasses the Q&A-only citation normalizer,
        citation validator, and repair loop while sharing this instance's lazy
        model, tokenizer, and deterministic generation path.
        """

        if not messages:
            raise ValueError("구조화 생성에는 최소 하나의 메시지가 필요합니다.")
        if not 1 <= max_new_tokens <= _MAX_STRUCTURED_NEW_TOKENS:
            raise ValueError(
                f"max_new_tokens must be between 1 and {_MAX_STRUCTURED_NEW_TOKENS}."
            )

        started_at = perf_counter()
        self._load_model()
        text = self._generate_text(messages, max_new_tokens=max_new_tokens)
        return GenerationResult(
            text=text,
            provider=self.provider,
            model_id=self.model_id,
            elapsed_ms=(perf_counter() - started_at) * 1000,
        )

    def _generate_text(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        max_new_tokens: int | None = None,
    ) -> str:
        """신규 토큰만 decode한다. 재시도에서도 같은 모델·생성 설정을 사용한다."""

        assert self._model is not None
        assert self._tokenizer is not None
        assert self._torch is not None

        encoded = self._tokenizer.apply_chat_template(
            list(messages),
            add_generation_prompt=True,
            enable_thinking=False,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        )
        model_device = getattr(self._model, "device", None)
        if model_device is not None and hasattr(encoded, "to"):
            encoded = encoded.to(model_device)
        prompt_length = self._prompt_length(encoded["input_ids"])
        inference_mode = getattr(self._torch, "inference_mode", None)
        context = inference_mode() if callable(inference_mode) else nullcontext()
        with context:
            output_ids = self._model.generate(
                **encoded,
                max_new_tokens=max_new_tokens or self.max_new_tokens,
                do_sample=False,
                pad_token_id=self._tokenizer.pad_token_id,
                eos_token_id=self._tokenizer.eos_token_id,
            )
        answer = self._tokenizer.decode(
            self._completion_ids(output_ids, prompt_length),
            skip_special_tokens=True,
        ).strip()
        return answer


__all__ = [
    "AnswerGenerationError",
    "AnswerGenerator",
    "EvidenceTemplateGenerator",
    "GenerationResult",
    "HuggingFaceAnswerGenerator",
]
