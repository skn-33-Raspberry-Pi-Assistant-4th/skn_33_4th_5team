"""GPU-only smoke test for the real Qwen grounded quiz path.

This test deliberately uses fixed final-answer evidence.  It does not create a
Retriever, open Chroma, or require an index: it verifies only
``answer + evidence -> Qwen -> parser -> validator -> QuizResponse``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from time import perf_counter

import pytest

from src.contracts import QuizEvidence, QuizGenerationRequest
from src.rag_to_llm import HuggingFaceAnswerGenerator, HuggingFaceQuizTextGenerator
from src.rag_to_llm.settings import DEFAULT_ANSWER_MODEL_ID, DEFAULT_ANSWER_MODEL_REVISION
from src.services.quiz_generator import QuizGenerator
from src.services.quiz_parser import QuizOutputError, parse_quiz_response
from src.services.quiz_validation import supporting_quote_matches


@dataclass(frozen=True)
class SmokeCase:
    """One short, self-contained SSH or OS-installation evidence fixture."""

    request_id: str
    answer: str
    evidence: str


_CASES = (
    SmokeCase(
        "ssh_disabled_default",
        "Raspberry Pi OS에서는 SSH가 기본적으로 비활성화되어 있습니다.",
        "SSH is disabled by default on Raspberry Pi OS.",
    ),
    SmokeCase(
        "ssh_imager_enable",
        "Raspberry Pi Imager의 사용자 지정 옵션에서 SSH를 활성화할 수 있습니다.",
        "Enable SSH in the Raspberry Pi Imager customisation options.",
    ),
    SmokeCase(
        "ssh_imager_credentials",
        "Imager 사용자 지정 옵션에서 원격 접속에 사용할 사용자 이름과 비밀번호를 설정할 수 있습니다.",
        "Set the username and password in the Raspberry Pi Imager customisation options.",
    ),
    SmokeCase(
        "ssh_network_requirement",
        "SSH로 접속하려면 Raspberry Pi가 네트워크에 연결되어 있어야 합니다.",
        "The Raspberry Pi must be connected to a network before you can connect using SSH.",
    ),
    SmokeCase(
        "ssh_host_name",
        "같은 네트워크에서는 호스트 이름을 사용하여 SSH 접속을 시도할 수 있습니다.",
        "On the same network, you can try to connect using the Raspberry Pi hostname.",
    ),
    SmokeCase(
        "os_imager_role",
        "Raspberry Pi Imager는 선택한 운영체제 이미지를 저장 장치에 기록합니다.",
        "Raspberry Pi Imager writes the selected operating system image to the selected storage device.",
    ),
    SmokeCase(
        "os_storage_selection",
        "운영체제를 기록하기 전에 Imager에서 대상 저장 장치를 선택해야 합니다.",
        "Select the target storage device in Raspberry Pi Imager before writing the operating system.",
    ),
    SmokeCase(
        "os_write_action",
        "운영체제와 저장 장치를 고른 뒤 WRITE를 선택하면 이미지 기록이 시작됩니다.",
        "After choosing an operating system and storage device, select WRITE to begin writing the image.",
    ),
    SmokeCase(
        "os_verify_option",
        "Imager는 기록한 운영체제 이미지를 검증하는 옵션을 제공합니다.",
        "Raspberry Pi Imager provides an option to verify the written operating system image.",
    ),
    SmokeCase(
        "os_remove_storage",
        "이미지 기록이 완료된 뒤에 저장 장치를 안전하게 제거할 수 있습니다.",
        "When writing is complete, you can safely remove the storage device.",
    ),
)


def _require_cuda() -> None:
    """Skip only an otherwise working non-CUDA environment."""

    import torch

    if not torch.cuda.is_available():
        pytest.skip("Qwen grounded smoke test requires a CUDA GPU")


def _request(case: SmokeCase) -> QuizGenerationRequest:
    return QuizGenerationRequest(
        request_id=case.request_id,
        answer=case.answer,
        evidence=[
            QuizEvidence(
                citation_id="C1",
                document_id="smoke-official-doc",
                chunk_id=f"smoke-{case.request_id}",
                content=case.evidence,
            )
        ],
        max_questions=1,
    )


def _bool_from_environment(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def test_qwen_generates_grounded_quiz_for_fixed_evidence_cases() -> None:
    """Run ten deterministic requests through the real Qwen structured path."""

    _require_cuda()
    assert len(_CASES) == 10

    answer_generator = HuggingFaceAnswerGenerator(
        model_id=os.getenv("ANSWER_MODEL_ID", DEFAULT_ANSWER_MODEL_ID),
        model_revision=os.getenv("ANSWER_MODEL_REVISION", DEFAULT_ANSWER_MODEL_REVISION),
        load_in_4bit=_bool_from_environment("ANSWER_LOAD_IN_4BIT", True),
        max_new_tokens=512,
        device=os.getenv("INFERENCE_DEVICE", "cuda"),
    )
    text_generator = HuggingFaceQuizTextGenerator(answer_generator, max_new_tokens=512)
    quiz_generator = QuizGenerator(text_generator)

    parser_passes = 0
    allowlist_violations = 0
    quote_checks = 0
    quote_matches = 0
    available_cases = 0
    elapsed_ms: list[float] = []
    failures: list[str] = []

    for case in _CASES:
        request = _request(case)
        started_at = perf_counter()
        response = quiz_generator.generate(request)
        total_elapsed_ms = (perf_counter() - started_at) * 1000
        elapsed_ms.append(total_elapsed_ms)

        raw_result = text_generator.last_result
        assert raw_result is not None
        try:
            parsed = parse_quiz_response(raw_result.text)
        except QuizOutputError:
            failures.append(f"{case.request_id}: parser_failed")
            continue

        parser_passes += 1
        evidence_by_id = {item.citation_id: item for item in request.evidence}
        for question in parsed.questions:
            if any(item not in evidence_by_id for item in question.evidence_ids):
                allowlist_violations += 1
            quote_checks += 1
            if (
                len(question.evidence_ids) == 1
                and len(question.supporting_quotes) == 1
                and question.evidence_ids[0] in evidence_by_id
                and supporting_quote_matches(
                    question.supporting_quotes[0],
                    evidence_by_id[question.evidence_ids[0]].content,
                )
            ):
                quote_matches += 1

        if response.status == "available" and response.questions:
            available_cases += 1
        else:
            failures.append(f"{case.request_id}: {response.status}")

    parser_rate = parser_passes / len(_CASES)
    quote_match_rate = quote_matches / quote_checks if quote_checks else 0.0
    available_rate = available_cases / len(_CASES)
    first_case_ms = elapsed_ms[0]
    later_average_ms = sum(elapsed_ms[1:]) / (len(elapsed_ms) - 1)
    average_ms = sum(elapsed_ms) / len(elapsed_ms)

    print(
        "Qwen quiz smoke metrics: "
        f"parser={parser_passes}/10 ({parser_rate:.0%}), "
        f"allowlist_violations={allowlist_violations}, "
        f"quote_matches={quote_matches}/{quote_checks} ({quote_match_rate:.0%}), "
        f"available={available_cases}/10 ({available_rate:.0%}), "
        f"first_case_ms={first_case_ms:.1f}, "
        f"later_average_ms={later_average_ms:.1f}, average_ms={average_ms:.1f}"
    )
    if failures:
        print("Qwen quiz smoke failures: " + ", ".join(failures))

    assert parser_rate >= 0.8
    assert allowlist_violations == 0
    assert quote_checks > 0
    assert quote_match_rate == 1.0
    assert available_rate >= 0.7
