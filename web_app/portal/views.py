"""Django views that present existing PiCare service responses."""

from __future__ import annotations

import uuid

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from src.condition_extraction.ui_input import RecommendationFormInput
from src.contracts import ChatResponse

from .forms import QuestionForm, RecommendationForm
from .services import (
    get_citation_presenter,
    get_qa_service,
    get_recommendation_service,
    get_runtime_readiness,
)


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
