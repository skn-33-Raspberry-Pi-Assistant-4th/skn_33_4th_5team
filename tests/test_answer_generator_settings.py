"""답변 생성기 provider 설정과 로컬 기본값을 검증한다."""

from __future__ import annotations

import sys
import types

import pytest

from src.rag_to_llm import AnswerGeneratorSettings, AnswerGeneratorSettingsError, HuggingFaceAnswerGenerator
from src.rag_to_llm.factory import build_answer_generator


def test_answer_generator_settings_defaults_to_template(tmp_path, monkeypatch) -> None:
    for name in (
        "ANSWER_GENERATOR",
        "ANSWER_MODEL_ID",
        "ANSWER_MODEL_REVISION",
        "ANSWER_LOAD_IN_4BIT",
        "ANSWER_MAX_NEW_TOKENS",
        "INFERENCE_DEVICE",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = AnswerGeneratorSettings.from_env(tmp_path)

    assert settings.provider == "template"
    assert settings.max_new_tokens == 768
    assert settings.device == "auto"


def test_huggingface_settings_build_generator_without_loading_model(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANSWER_GENERATOR", "huggingface")
    monkeypatch.setenv("ANSWER_MODEL_ID", "Qwen/test")
    monkeypatch.setenv("ANSWER_MODEL_REVISION", "revision-test")
    monkeypatch.setenv("ANSWER_LOAD_IN_4BIT", "true")
    monkeypatch.setenv("ANSWER_MAX_NEW_TOKENS", "32")
    monkeypatch.setenv("INFERENCE_DEVICE", "mps")

    settings = AnswerGeneratorSettings.from_env(tmp_path)
    generator = build_answer_generator(settings)

    assert isinstance(generator, HuggingFaceAnswerGenerator)
    assert generator.model_id == "Qwen/test"
    assert generator.device == "mps"
    assert generator.is_loaded is False


def test_answer_generator_settings_reject_invalid_provider(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ANSWER_GENERATOR", "runpod")

    with pytest.raises(AnswerGeneratorSettingsError, match="ANSWER_GENERATOR"):
        AnswerGeneratorSettings.from_env(tmp_path)


def test_answer_generator_settings_rejects_invalid_inference_device(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("INFERENCE_DEVICE", "metal")

    with pytest.raises(AnswerGeneratorSettingsError, match="INFERENCE_DEVICE"):
        AnswerGeneratorSettings.from_env(tmp_path)


@pytest.mark.parametrize(
    ("requested_device", "cuda_available", "mps_available", "expected_device", "expected_dtype", "uses_cuda_options"),
    [
        ("auto", True, True, "cuda", "bfloat16", True),
        ("mps", False, True, "mps", "float16", False),
        ("cpu", False, False, "cpu", "float32", False),
    ],
)
def test_huggingface_loader_applies_resolved_device_configuration(
    monkeypatch,
    requested_device,
    cuda_available,
    mps_available,
    expected_device,
    expected_dtype,
    uses_cuda_options,
) -> None:
    """모델 다운로드 없이 장치별 로딩 옵션과 4-bit 정책을 검증한다."""

    class FakeModel:
        def __init__(self) -> None:
            self.to_calls: list[str] = []
            self.evaluated = False

        def to(self, device: str) -> "FakeModel":
            self.to_calls.append(device)
            return self

        def eval(self) -> "FakeModel":
            self.evaluated = True
            return self

    class FakeTokenizer:
        pad_token_id = None
        eos_token = "</s>"

    class FakeAutoTokenizer:
        @classmethod
        def from_pretrained(cls, *_args, **_kwargs):
            return FakeTokenizer()

    class FakeAutoModel:
        calls: list[dict] = []
        model = FakeModel()

        @classmethod
        def from_pretrained(cls, _model_id, **kwargs):
            cls.calls.append(kwargs)
            return cls.model

    class FakeBitsAndBytesConfig:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    fake_torch = types.ModuleType("torch")
    fake_torch.bfloat16 = "bfloat16"
    fake_torch.float16 = "float16"
    fake_torch.float32 = "float32"
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: cuda_available)
    fake_torch.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: mps_available)
    )
    fake_transformers = types.ModuleType("transformers")
    fake_transformers.AutoModelForCausalLM = FakeAutoModel
    fake_transformers.AutoTokenizer = FakeAutoTokenizer
    fake_transformers.BitsAndBytesConfig = FakeBitsAndBytesConfig
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    generator = HuggingFaceAnswerGenerator(
        model_id="Qwen/test",
        load_in_4bit=True,
        device=requested_device,
    )
    generator._load_model()

    kwargs = FakeAutoModel.calls[0]
    assert generator.device == expected_device
    assert generator.load_in_4bit is uses_cuda_options
    assert kwargs["torch_dtype"] == expected_dtype
    assert ("device_map" in kwargs) is uses_cuda_options
    assert ("quantization_config" in kwargs) is uses_cuda_options
    assert FakeAutoModel.model.to_calls == ([] if uses_cuda_options else [expected_device])
    assert FakeAutoModel.model.evaluated is True


def test_huggingface_loader_rejects_unavailable_explicit_device(monkeypatch) -> None:
    """선택한 장치가 없으면 모델 다운로드 전 명확한 설정 오류를 낸다."""

    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    fake_torch.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: False)
    )
    fake_transformers = types.ModuleType("transformers")
    fake_transformers.AutoModelForCausalLM = object
    fake_transformers.AutoTokenizer = object
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    generator = HuggingFaceAnswerGenerator(model_id="Qwen/test", device="mps")

    from src.rag_to_llm import AnswerGenerationError

    with pytest.raises(AnswerGenerationError, match="Apple MPS is unavailable"):
        generator._load_model()
