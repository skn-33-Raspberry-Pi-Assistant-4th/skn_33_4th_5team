"""Django views that present existing PiCare service responses."""

from __future__ import annotations

import json
import uuid

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from src.condition_extraction.ui_input import RecommendationFormInput
from src.contracts import ChatResponse

from .forms import CommandInputForm, QuestionForm, RecommendationForm
from .services import (
    get_challenge_service,
    get_citation_presenter,
    get_command_lab_service,
    get_qa_service,
    get_recommendation_service,
    get_runtime_readiness,
)


CHALLENGE_SESSION_KEY = "picare_challenge"


STATUS_LABELS = {
    "answered": "근거 확인 완료",
    "needs_clarification": "추가 정보 필요",
    "insufficient_evidence": "근거 부족",
    "out_of_scope": "답변 범위 외",
    "safety_blocked": "안전 정책으로 보류",
    "error": "실행 오류",
}
BLOCKED_STATUSES = {"needs_clarification", "insufficient_evidence", "out_of_scope", "safety_blocked", "error"}


def _source_cards(response: ChatResponse, *, preferred_use_case: str | None = None) -> list[dict[str, str]]:
    presenter = get_citation_presenter()
    cards = []
    for citation in response.citations:
        if presenter is not None:
            display = presenter.present(citation, preferred_use_case=preferred_use_case)
            title, section, tags = display.document_label, display.section_label, " · ".join(display.tags) or "없음"
        else:
            title = citation.title
            section = citation.section.rsplit(" > ", maxsplit=1)[-1]
            tags = "없음"
        cards.append(
            {
                "citation_id": citation.citation_id,
                "title": title,
                "section": section,
                "tags": tags,
                "url": str(citation.source_url),
                "quote": citation.quote,
            }
        )
    return cards


def _response_context(response: ChatResponse) -> dict:
    preferred_use_case = response.conditions.use_case if response.conditions else None
    return {
        "response": response,
        "status_label": STATUS_LABELS[response.status],
        "is_blocked": response.status in BLOCKED_STATUSES,
        "source_cards": _source_cards(response, preferred_use_case=preferred_use_case),
        "images": [item for item in response.media if item.media_type == "image"],
        "videos": [item for item in response.media if item.media_type != "image"],
    }


def _base_context(*, active_page: str) -> dict:
    readiness = get_runtime_readiness()
    return {"active_page": active_page, "runtime_ready": readiness.ready, "runtime_message": readiness.message}


def _lab_evidence_cards(evidence: list[dict]) -> list[dict[str, str]]:
    """Expose human-readable source information, never manifest checksums."""

    return [
        {
            "chunk_id": item["chunk_id"],
            "title": item["title"],
            "section": item["section"],
            "url": item["source_url"],
        }
        for item in evidence
    ]


def _lab_payload(result: dict) -> dict:
    """A browser/API-safe view of a CommandLabService result."""

    return {
        "template_id": result["template_id"],
        "execution_policy": result["execution_policy"],
        "command": result["command"],
        "parts": result["parts"],
        "effect_ko": result["effect_ko"],
        "execution_context": result["execution_context"],
        "risk_level": result["risk_level"],
        "risk_notice_ko": result["risk_notice_ko"],
        "limitations_ko": result["limitations_ko"],
        "evidence": _lab_evidence_cards(result["evidence"]),
        "product": result["product"],
        "values": result["values"],
    }


def _lab_template_payload(template: dict) -> dict:
    return {
        "template_id": template["template_id"],
        "topic": template["topic"],
        "canonical_command": template["canonical_command"],
        "parts": template["parts"],
        "editable_fields": template["editable_fields"],
        "execution_context": template["execution_context"],
        "effect_ko": template["effect_ko"],
        "risk_level": template["risk_level"],
        "risk_notice_ko": template["risk_notice_ko"],
        "limitations_ko": template["limitations_ko"],
    }


def _lab_context() -> dict:
    service = get_command_lab_service()
    templates = service.list_templates()
    return {
        "lab_templates": templates,
        "lab_products": [
            {"product_id": product["product_id"], "name": product["name"]}
            for product in service.products.values()
        ],
    }


@require_http_methods(["GET"])
def about(request):
    return render(request, "portal/about.html", _base_context(active_page="about"))


@require_http_methods(["GET", "POST"])
def recommend(request):
    context = _base_context(active_page="recommend")
    form = RecommendationForm(request.POST or None, initial={"purpose": "모니터 없이 홈 서버로 사용하고 싶어요."})
    context["form"] = form
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            request_form = RecommendationFormInput.from_widget_values(
                request_id=str(uuid.uuid4()),
                free_text=data["purpose"],
                user_level_label=data["user_level"] or "선택 안 함",
                performance_priority_label=data["performance"] or "선택 안 함",
                wireless_required=RecommendationForm.as_optional_boolean(data["wifi"]),
                camera_required=RecommendationForm.as_optional_boolean(data["camera"]),
                gpio_required=RecommendationForm.as_optional_boolean(data["gpio"]),
                monitor_absent=RecommendationForm.as_optional_boolean(data["monitor_absent"]),
            )
            response = get_recommendation_service().answer_form(form=request_form, trace=True)
            context.update(_response_context(response))
        except Exception as exc:
            context["service_error"] = f"제품 추천 런타임을 준비하지 못했습니다: {exc}"
    return render(request, "portal/recommend.html", context)


@require_http_methods(["GET", "POST"])
def qa(request):
    context = _base_context(active_page="qa")
    form = QuestionForm(request.POST or None)
    context["form"] = form
    if request.method == "POST" and form.is_valid():
        question = form.cleaned_data["question"]
        context["question"] = question
        try:
            response = get_qa_service().answer(
                request_id=str(uuid.uuid4()), question=question, retrieval_mode="hybrid", trace=True
            )
            context.update(_response_context(response))
        except Exception as exc:
            context["service_error"] = f"QA 런타임을 준비하지 못했습니다: {exc}"
    return render(request, "portal/qa.html", context)


@require_http_methods(["GET", "POST"])
def lab(request):
    """Present the catalog-backed command lab; no submitted command is executed."""

    context = _base_context(active_page="lab")
    context["analysis_form"] = CommandInputForm(request.POST or None)
    try:
        context.update(_lab_context())
    except Exception:
        context["lab_error"] = "명령어 실험실 데이터를 준비하지 못했습니다. 잠시 후 다시 시도해 주세요."
        return render(request, "portal/lab.html", context)

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            service = get_command_lab_service()
            if action == "analyze" and context["analysis_form"].is_valid():
                context["lab_result"] = _lab_payload(service.analyze(context["analysis_form"].cleaned_data["command"]))
            elif action == "compose":
                template_id = request.POST.get("template_id", "")
                item = service._item(template_id)
                values = {
                    field["part_id"]: request.POST.get(f"value_{field['part_id']}", "")
                    for field in item["editable_fields"]
                }
                product_id = request.POST.get("product_id") or None
                context["lab_result"] = _lab_payload(service.compose(template_id, values, product_id=product_id))
                context["analysis_form"] = CommandInputForm(initial={"command": context["lab_result"]["command"]})
            elif action not in {"analyze", "compose"}:
                context["lab_error"] = "요청을 확인하지 못했습니다."
        except ValueError as exc:
            context["lab_error"] = str(exc)
        except Exception:
            context["lab_error"] = "명령어 실험실을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요."
    return render(request, "portal/lab.html", context)


@require_http_methods(["GET", "POST"])
def challenge(request):
    """Run a three-question challenge with answer data kept on the server."""

    context = _base_context(active_page="challenge")
    try:
        service = get_challenge_service()
        context["challenge_topics"] = service.topics()
        state = request.session.get(CHALLENGE_SESSION_KEY)
        if request.method == "POST":
            action = request.POST.get("action")
            if action == "start":
                started = service.start(request.POST.get("topic", ""))
                request.session[CHALLENGE_SESSION_KEY] = started["state"]
                context["challenge_question"] = started["question"]
            elif action == "submit":
                outcome = service.submit(
                    state,
                    question_id=request.POST.get("question_id", ""),
                    choice_id=request.POST.get("choice_id", ""),
                )
                context["challenge_result"] = outcome
                if outcome["completed"]:
                    request.session.pop(CHALLENGE_SESSION_KEY, None)
                else:
                    request.session[CHALLENGE_SESSION_KEY] = outcome["state"]
            elif action == "continue":
                context["challenge_question"] = service.current_question(state)
            elif action == "reset":
                request.session.pop(CHALLENGE_SESSION_KEY, None)
            else:
                context["challenge_error"] = "요청을 확인하지 못했습니다."
        elif state:
            context["challenge_question"] = service.current_question(state)
    except ValueError as exc:
        context["challenge_error"] = str(exc)
    except Exception:
        context["challenge_error"] = "미니 챌린지를 준비하지 못했습니다. 잠시 후 다시 시도해 주세요."
    return render(request, "portal/challenge.html", context)


def _json_body(request) -> dict:
    try:
        value = json.loads(request.body)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("JSON 요청 본문을 확인해 주세요.") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON 객체를 보내 주세요.")
    return value


@require_http_methods(["GET"])
def lab_templates_api(request):
    try:
        templates = [_lab_template_payload(item) for item in get_command_lab_service().list_templates()]
        return JsonResponse({"templates": templates})
    except Exception:
        return JsonResponse({"error": "명령어 실험실 데이터를 준비하지 못했습니다."}, status=503)


@require_http_methods(["POST"])
def lab_analyze_api(request):
    try:
        body = _json_body(request)
        return JsonResponse(_lab_payload(get_command_lab_service().analyze(body.get("command"))))
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception:
        return JsonResponse({"error": "명령어 실험실을 처리하지 못했습니다."}, status=503)


@require_http_methods(["POST"])
def lab_compose_api(request):
    try:
        body = _json_body(request)
        return JsonResponse(
            _lab_payload(
                get_command_lab_service().compose(
                    body.get("template_id"), body.get("values"), product_id=body.get("product_id")
                )
            )
        )
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception:
        return JsonResponse({"error": "명령어 실험실을 처리하지 못했습니다."}, status=503)


@require_http_methods(["GET"])
def health(request):
    readiness = get_runtime_readiness()
    return JsonResponse(
        {
            "status": "ok" if readiness.ready else "not_ready",
            "ready": readiness.ready,
            "message": readiness.message,
        }
    )
