"""Qwen summary adapter reuses one injected answer-generator instance."""

from __future__ import annotations

from unittest.mock import Mock

from src.rag_to_llm import (
    EvidenceTemplateGenerator,
    GenerationResult,
    HuggingFaceAnswerGenerator,
    HuggingFaceQaSummaryTextGenerator,
    build_qa_summary_text_generator,
)


def test_summary_adapter_reuses_the_injected_qwen_for_each_call() -> None:
    answer_generator = Mock(spec=HuggingFaceAnswerGenerator)
    answer_generator.generate_structured.side_effect = [
        GenerationResult('{"question_title":"SSH 설정"}', "huggingface", "Qwen/test", 10.0),
        GenerationResult('{"answer_summary":"SSH를 설정하세요. [C1]"}', "huggingface", "Qwen/test", 12.0),
    ]
    adapter = HuggingFaceQaSummaryTextGenerator(answer_generator, max_new_tokens=192)
    title_messages = [{"role": "user", "content": "title"}]
    summary_messages = [{"role": "user", "content": "summary"}]

    assert adapter.generate(title_messages) == '{"question_title":"SSH 설정"}'
    assert adapter.generate(summary_messages) == '{"answer_summary":"SSH를 설정하세요. [C1]"}'
    assert answer_generator.generate_structured.call_count == 2
    assert answer_generator.generate_structured.call_args_list[0].kwargs == {"max_new_tokens": 192}
    assert answer_generator.generate_structured.call_args_list[1].kwargs == {"max_new_tokens": 192}
    assert adapter.last_result.text == '{"answer_summary":"SSH를 설정하세요. [C1]"}'


def test_adapter_factory_supports_qwen_and_rejects_template() -> None:
    answer_generator = HuggingFaceAnswerGenerator(model_id="Qwen/test")

    adapter = build_qa_summary_text_generator(answer_generator)

    assert isinstance(adapter, HuggingFaceQaSummaryTextGenerator)
    assert adapter._answer_generator is answer_generator
    assert build_qa_summary_text_generator(EvidenceTemplateGenerator()) is None
