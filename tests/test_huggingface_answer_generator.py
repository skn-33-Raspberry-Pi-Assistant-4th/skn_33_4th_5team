"""실제 Qwen 다운로드 없이 Hugging Face QA 생성기의 계약을 검증한다."""

from __future__ import annotations

from contextlib import nullcontext
from threading import Event
from unittest.mock import Mock

import pytest

from src.lang import PromptEvidence
from src.rag_to_llm import HuggingFaceAnswerGenerator
from src.rag_to_llm.answer_generator import AnswerGenerationError
from src.rag_to_llm.cancellation import GenerationCancelled


class FakeInputIds:
    shape = (1, 3)


class FakeEncoded(dict):
    def __init__(self) -> None:
        super().__init__(input_ids=FakeInputIds())
        self.device = None

    def to(self, device):
        self.device = device
        return self


class FakeTokenizer:
    pad_token_id = 0
    eos_token_id = 2
    eos_token = "</s>"

    def __init__(self) -> None:
        self.messages = None
        self.options = None
        self.response = "SSH는 Raspberry Pi Imager에서 활성화할 수 있습니다. [C1]"

    def apply_chat_template(self, messages, **kwargs):
        self.messages = messages
        self.options = kwargs
        return FakeEncoded()

    def decode(self, token_ids, *, skip_special_tokens):
        assert token_ids == [7, 8]
        assert skip_special_tokens is True
        return self.response


class FakeModel:
    device = "cuda:0"

    def __init__(self) -> None:
        self.generate_kwargs = None

    def generate(self, **kwargs):
        self.generate_kwargs = kwargs
        return [[1, 2, 3, 7, 8]]


class FakeTorch:
    @staticmethod
    def inference_mode():
        return nullcontext()


def _messages():
    return ({"role": "system", "content": "근거만 사용하세요."},)


def _evidence():
    return (PromptEvidence(citation_id="C1", content="Enable SSH in Imager."),)


def test_huggingface_generator_is_lazy_and_decodes_only_new_tokens(monkeypatch) -> None:
    generator = HuggingFaceAnswerGenerator(model_id="Qwen/test", max_new_tokens=32)
    tokenizer = FakeTokenizer()
    model = FakeModel()
    load_calls = 0

    def fake_load_model() -> None:
        nonlocal load_calls
        if generator.is_loaded:
            return
        load_calls += 1
        generator._tokenizer = tokenizer
        generator._model = model
        generator._torch = FakeTorch()

    monkeypatch.setattr(generator, "_load_model", fake_load_model)

    assert generator.is_loaded is False
    response = generator.generate(_messages(), _evidence())

    assert load_calls == 1
    assert generator.is_loaded is True
    assert response.provider == "huggingface"
    assert response.model_id == "Qwen/test"
    assert response.text.endswith("[C1]")
    assert tokenizer.messages == list(_messages())
    assert tokenizer.options["add_generation_prompt"] is True
    assert tokenizer.options["enable_thinking"] is False
    assert tokenizer.options["return_tensors"] == "pt"
    assert model.generate_kwargs["max_new_tokens"] == 32
    assert model.generate_kwargs["do_sample"] is False

    generator.generate(_messages(), _evidence())
    assert load_calls == 1


def test_huggingface_generator_structured_path_returns_raw_json_once(monkeypatch) -> None:
    generator = HuggingFaceAnswerGenerator(model_id="Qwen/test", max_new_tokens=32)
    tokenizer = FakeTokenizer()
    tokenizer.response = '{"status":"insufficient_content","questions":[]}'
    model = FakeModel()
    load_calls = 0

    def fake_load_model() -> None:
        nonlocal load_calls
        if generator.is_loaded:
            return
        load_calls += 1
        generator._tokenizer = tokenizer
        generator._model = model
        generator._torch = FakeTorch()

    monkeypatch.setattr(generator, "_load_model", fake_load_model)
    monkeypatch.setattr(
        "src.rag_to_llm.answer_generator.validate_grounded_answer",
        Mock(side_effect=AssertionError("QA validator must not run")),
    )

    result = generator.generate_structured(_messages(), max_new_tokens=64)

    assert result.text == '{"status":"insufficient_content","questions":[]}'
    assert result.attempts == 1
    assert load_calls == 1
    assert model.generate_kwargs["max_new_tokens"] == 64
    assert model.generate_kwargs["do_sample"] is False

    generator.generate_structured(_messages(), max_new_tokens=16)
    assert load_calls == 1
    assert model.generate_kwargs["max_new_tokens"] == 16

    generator.generate_structured(_messages(), max_new_tokens=1024)
    assert load_calls == 1
    assert model.generate_kwargs["max_new_tokens"] == 1024
    assert "stopping_criteria" not in model.generate_kwargs


def test_structured_cancellation_before_load_skips_model(monkeypatch) -> None:
    generator = HuggingFaceAnswerGenerator(model_id="Qwen/test")
    load = Mock(side_effect=AssertionError("model load must be skipped"))
    monkeypatch.setattr(generator, "_load_model", load)
    cancellation = Event()
    cancellation.set()

    with pytest.raises(GenerationCancelled):
        generator.generate_structured(
            _messages(), max_new_tokens=64, cancel_requested=cancellation.is_set
        )

    load.assert_not_called()


def test_structured_cancellation_stops_during_generation(monkeypatch) -> None:
    generator = HuggingFaceAnswerGenerator(model_id="Qwen/test")
    cancellation = Event()
    tokenizer = FakeTokenizer()

    class CancellingModel(FakeModel):
        def generate(self, **kwargs):
            self.generate_kwargs = kwargs
            cancellation.set()
            assert kwargs["stopping_criteria"][0]([[1, 2, 3, 7]], None) is True
            cancellation.clear()  # A non-sticky callback must not expose partial output.
            return [[1, 2, 3, 7, 8]]

    model = CancellingModel()

    def fake_load_model() -> None:
        generator._tokenizer = tokenizer
        generator._model = model
        generator._torch = FakeTorch()

    monkeypatch.setattr(generator, "_load_model", fake_load_model)

    with pytest.raises(GenerationCancelled):
        generator.generate_structured(
            _messages(), max_new_tokens=64, cancel_requested=cancellation.is_set
        )

    assert model.generate_kwargs["max_new_tokens"] == 64
    assert generator._model is model


@pytest.mark.parametrize("max_new_tokens", [0, 1025])
def test_huggingface_generator_structured_path_rejects_unsafe_token_limit(max_new_tokens: int) -> None:
    generator = HuggingFaceAnswerGenerator(model_id="Qwen/test")

    with pytest.raises(ValueError, match="max_new_tokens"):
        generator.generate_structured(_messages(), max_new_tokens=max_new_tokens)


def test_huggingface_generator_allows_qa_token_limit_up_to_1024() -> None:
    generator = HuggingFaceAnswerGenerator(model_id="Qwen/test", max_new_tokens=1024)

    assert generator.max_new_tokens == 1024


def test_huggingface_generator_rejects_qa_token_limit_above_1024() -> None:
    with pytest.raises(ValueError, match="max_new_tokens"):
        HuggingFaceAnswerGenerator(model_id="Qwen/test", max_new_tokens=1025)


def test_invalid_generation_retries_once_with_original_evidence_not_failed_claim(monkeypatch):
    generator = HuggingFaceAnswerGenerator(model_id="Qwen/test")
    monkeypatch.setattr(generator, "_load_model", lambda: None)
    generate = Mock(side_effect=["근거에 없는 위험한 주장입니다. [C99]", "SSH를 활성화하세요. [C1]"])
    monkeypatch.setattr(generator, "_generate_text", generate)
    result = generator.generate(_messages(), _evidence())
    assert result.text == "SSH를 활성화하세요. [C1]"
    assert generate.call_count == 2
    retry_messages = generate.call_args.args[0]
    assert retry_messages[:-1] == list(_messages())
    assert "위험한 주장" not in str(retry_messages)
    assert "최대 6개 항목" in retry_messages[-1]["content"]
    assert "최대 3개의 짧은" not in retry_messages[-1]["content"]


def test_repeated_invalid_output_fails_closed_after_two_attempts(monkeypatch):
    generator = HuggingFaceAnswerGenerator(model_id="Qwen/test")
    monkeypatch.setattr(generator, "_load_model", lambda: None)
    generate = Mock(return_value="출처를 확인하세요 https://example.com. [C1]")
    monkeypatch.setattr(generator, "_generate_text", generate)
    with pytest.raises(AnswerGenerationError):
        generator.generate(_messages(), _evidence())
    assert generate.call_count == 2


def test_mixed_abstention_is_regenerated_without_exposing_explanation(monkeypatch):
    generator = HuggingFaceAnswerGenerator(model_id="Qwen/test")
    monkeypatch.setattr(generator, "_load_model", lambda: None)
    generate = Mock(side_effect=["모델이 추측한 설명 [INSUFFICIENT_EVIDENCE]", "[INSUFFICIENT_EVIDENCE]"])
    monkeypatch.setattr(generator, "_generate_text", generate)
    assert generator.generate(_messages(), _evidence()).text == "[INSUFFICIENT_EVIDENCE]"
    assert generate.call_count == 2


def test_standalone_abstention_marker_discards_all_surrounding_claims(monkeypatch):
    generator = HuggingFaceAnswerGenerator(model_id="Qwen/test")
    monkeypatch.setattr(generator, "_load_model", lambda: None)
    generate = Mock(return_value="검증되지 않은 주장을 포함한 설명 [C99]\n\n[INSUFFICIENT_EVIDENCE]")
    monkeypatch.setattr(generator, "_generate_text", generate)
    result = generator.generate(_messages(), _evidence())
    assert result.text == "[INSUFFICIENT_EVIDENCE]"
    assert "C99" not in result.text
    assert generate.call_count == 1


def test_grouped_citations_are_normalized_but_literal_commands_are_preserved(monkeypatch):
    generator = HuggingFaceAnswerGenerator(model_id="Qwen/test")
    monkeypatch.setattr(generator, "_load_model", lambda: None)
    generate = Mock(return_value="명령 `echo [ C1 ]`의 원문을 확인하세요 [ C1, C2 ].")
    monkeypatch.setattr(generator, "_generate_text", generate)
    evidence = (*_evidence(), PromptEvidence(citation_id="C2", content="A second official excerpt."))
    result = generator.generate(_messages(), evidence)
    assert result.text == "명령 `echo [ C1 ]`의 원문을 확인하세요 [C1] [C2]."
    assert generate.call_count == 1


def test_normalizing_grouped_citations_does_not_accept_unknown_ids(monkeypatch):
    generator = HuggingFaceAnswerGenerator(model_id="Qwen/test")
    monkeypatch.setattr(generator, "_load_model", lambda: None)
    generate = Mock(return_value="알려지지 않은 인용을 포함합니다 [ C1, C99 ].")
    monkeypatch.setattr(generator, "_generate_text", generate)
    with pytest.raises(AnswerGenerationError):
        generator.generate(_messages(), _evidence())
    assert generate.call_count == 2
