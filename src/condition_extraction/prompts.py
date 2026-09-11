"""Base 추론·QLoRA 학습·LoRA 추론이 공유하는 단일 조건 추출 프롬프트다."""

from __future__ import annotations

import json
from typing import Any

from src.contracts import ConditionPayload

from .schema import SurveyAnswer, SurveyResponse


SYSTEM_PROMPT = """당신은 Raspberry Pi 서비스의 조건 추출기입니다.
사용자의 설문 답변에 명시된 정보만 제공된 JSON Schema로 변환하세요.
제품을 직접 추천하거나 제품 사양, 가격, 재고, URL, 출처를 만들지 마세요.
언급되지 않은 선택 조건은 null로 두고, false는 사용자가 아니라고 명시한 경우에만 사용하세요.
product_models와 os_versions는 값이 있으면 배열, 없으면 null입니다.
답변이 충돌하거나 핵심 목적이 모호하면 needs_clarification을 true로 하고 최대 3개의 짧은 한국어 확인 질문을 작성하세요.
JSON 객체 하나만 출력하고 Markdown 코드 블록이나 설명을 덧붙이지 마세요.

짧은 추천 입력 처리:
- 제품 추천 설문에서는 “홈 서버를 만들고 싶어요”처럼 목적만 있어도 product_recommendation입니다.
- Wi-Fi·카메라·GPIO·성능·수준을 말하지 않아도 목적을 알면 추천할 수 있습니다. 누락된 선택 조건을 확인 질문으로 요구하지 마세요.
- 목적 자체가 없거나 모호할 때만 목적을 확인하세요.

긴 입력 처리:
- 처음부터 끝까지 읽고 주 목적은 use_case, 부 목적들은 additional_use_cases에, 부 작업들은 additional_tasks에 담으세요.
- 목적이 여러 개라는 이유만으로 확인 질문을 하지 마세요. 기존 enum에 해당하지 않는 요구는 unverified_requirements에 짧게 보존하세요.
- 예산, 크기, 소음, 전력, 메모리 등 스키마로 검증하지 못하는 요구도 unverified_requirements에 보존하세요. 충족한다고 추측하지 마세요.
- ethernet_required는 유선 LAN 필수 여부, min_camera_connectors와 min_display_outputs는 명시된 최소 커넥터/출력 수입니다.
- 보유 제품이나 단순 예시로 언급한 제품은 product_models에 넣지 마세요. 추천 대상을 그 제품으로 제한하거나 비교해 달라고 한 경우에만 넣으세요.
- 희망 사항과 필수 조건을 구분하고, 나중에 명시적으로 정정한 조건을 적용하세요. 해결되지 않은 필수 조건 충돌만 확인하세요.

필드 경계:
- intent는 사용자가 요청하는 응답의 종류입니다. 제품이나 모델을 골라 달라는 요청만 product_recommendation이고,
  이미 보유하거나 지정한 제품의 설치·연결·설정 절차를 묻는 요청은 how_to입니다.
- use_case는 Raspberry Pi를 사용하는 전체 용도·시나리오이고, task는 그 시나리오에서 명시적으로 수행할
  구체 작업입니다. 두 필드의 허용값을 서로 바꿔 넣지 마세요.
- use_case가 있어도 구체 작업이 명시되지 않으면 task는 null입니다. desktop_programming은 코딩, 프로그래밍,
  IDE 또는 개발 도구 사용이 명시된 경우에만 쓰고, 문서 작업·웹 브라우징·일반 데스크톱 사용만 있으면 null입니다.
- smart_farm_monitoring은 use_case이고 sensor_monitoring은 task입니다. gpio_iot은 use_case이고
  gpio_setup은 task입니다.

허용값:
- intent: product_recommendation, product_comparison, how_to, troubleshooting, support_recall, out_of_scope
- use_case: education_coding, desktop_computing, home_server, camera_monitoring, smart_farm_monitoring, headless_remote_management, gpio_iot
- task: desktop_programming, os_installation, system_configuration, remote_access, camera_setup, gpio_setup, sensor_monitoring, server_operation, troubleshooting, support_recall
- performance_priority: low, medium, high
- user_level: beginner, intermediate, advanced
"""


def _target(**overrides: Any) -> ConditionPayload:
    """few-shot 예시용 기본 조건에 필요한 정답 필드만 덮어쓴다."""

    payload: dict[str, Any] = {
        "schema_version": "1.1.0",
        "intent": "product_recommendation",
        "use_case": None,
        "product_models": None,
        "os_versions": None,
        "task": None,
        "performance_priority": None,
        "wireless_required": None,
        "camera_required": None,
        "gpio_required": None,
        "monitor_available": None,
        "remote_access_required": None,
        "user_level": None,
        "needs_clarification": False,
        "clarification_questions": [],
    }
    payload.update(overrides)
    return ConditionPayload.model_validate(payload)


FEW_SHOT_EXAMPLES = (
    (
        SurveyResponse(
            answers=[
                SurveyAnswer(
                    question_id="purpose",
                    question="사용 목적이 무엇인가요?",
                    answer="초등학생이 처음 파이썬과 스크래치를 배우는 교육용이에요.",
                ),
                SurveyAnswer(
                    question_id="environment",
                    question="어떤 환경에서 사용하나요?",
                    answer="집의 모니터에 연결하고 Wi-Fi를 쓸 거예요.",
                ),
            ]
        ),
        _target(
            use_case="education_coding",
            task="desktop_programming",
            user_level="beginner",
            wireless_required=True,
            monitor_available=True,
        ),
    ),
    (
        SurveyResponse(
            answers=[
                SurveyAnswer(
                    question_id="purpose",
                    question="사용 목적이 무엇인가요?",
                    answer="스마트팜의 온습도 센서를 달아 화면 없이 원격으로 확인하고 싶어요.",
                ),
                SurveyAnswer(
                    question_id="features",
                    question="꼭 필요한 기능은 무엇인가요?",
                    answer="GPIO와 Wi-Fi가 꼭 필요하고 카메라는 필요 없어요.",
                ),
            ]
        ),
        _target(
            use_case="smart_farm_monitoring",
            task="sensor_monitoring",
            wireless_required=True,
            camera_required=False,
            gpio_required=True,
            monitor_available=False,
            remote_access_required=True,
        ),
    ),
)


def schema_text() -> str:
    """공통 ConditionPayload JSON Schema를 한국어 보존 문자열로 만든다."""

    return json.dumps(ConditionPayload.model_json_schema(), ensure_ascii=False, indent=2)


def user_message(survey: SurveyResponse) -> str:
    """JSON Schema와 사용자의 설문 답변을 하나의 모델 입력으로 조합한다."""

    return f"JSON Schema:\n{schema_text()}\n\n설문 답변:\n{survey.to_prompt_text()}"


def build_inference_messages(
    survey: SurveyResponse, *, include_few_shots: bool = True
) -> list[dict[str, str]]:
    """선택적 few-shot 예시를 포함한 Qwen chat 메시지 배열을 만든다."""

    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if include_few_shots:
        for example_survey, example_target in FEW_SHOT_EXAMPLES:
            messages.extend(
                [
                    {"role": "user", "content": user_message(example_survey)},
                    {"role": "assistant", "content": example_target.model_dump_json()},
                ]
            )
    messages.append({"role": "user", "content": user_message(survey)})
    return messages


def build_training_example(
    survey: SurveyResponse, target: ConditionPayload
) -> dict[str, list[dict[str, str]]]:
    """정답 completion에만 loss를 적용할 TRL 대화형 학습 샘플을 만든다."""

    return {
        "prompt": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message(survey)},
        ],
        "completion": [{"role": "assistant", "content": target.model_dump_json()}],
    }
