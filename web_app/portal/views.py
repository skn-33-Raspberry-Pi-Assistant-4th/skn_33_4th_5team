"""Django views that present existing PiCare service responses."""

from __future__ import annotations

import json
import uuid

from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.urls import reverse
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
INLINE_CHALLENGE_SESSION_KEY = "picare_inline_challenge"
LAB_DRAWER_SESSION_KEY = "picare_command_lab_drawer"
LAB_DRAWER_LIMIT = 10

LAB_TOPIC_LABELS = {
    "remote_access": "원격 접속",
    "os_installation": "OS 설치",
}


STATUS_LABELS = {
    "answered": "근거 확인 완료",
    "needs_clarification": "추가 정보 필요",
    "insufficient_evidence": "근거 부족",
    "out_of_scope": "답변 범위 외",
    "safety_blocked": "안전 정책으로 보류",
    "error": "실행 오류",
}
BLOCKED_STATUSES = {"needs_clarification", "insufficient_evidence", "out_of_scope", "safety_blocked", "error"}
REMOTE_ACCESS_DOCUMENT_IDS = frozenset({"rpi-doc-remote-access-ssh"})
OS_INSTALLATION_DOCUMENT_IDS = frozenset(
    {"rpi-doc-getting-started-install", "rpi-doc-getting-started-setting-up"}
)


# Display-only sample content for the question archive prototype. Member
# questions, AI summaries, and citations will be replaced by persisted data
# when the archive feature is connected to its service and database.
QUESTION_ARCHIVE_PREVIEWS = (
    {
        "id": 1,
        "topic": "원격 접속",
        "title": "Raspberry Pi에서 SSH를 활성화하는 방법이 궁금해요.",
        "question": "Raspberry Pi Imager로 OS를 설치할 때 SSH를 미리 켜는 방법과, 이미 설치한 뒤 설정하는 방법을 알고 싶어요.",
        "summary": "OS 설치 전에는 Imager의 Customisation에서 Remote Access의 Enable SSH를 켜고, 설치 후에는 raspi-config에서도 설정할 수 있습니다.",
        "author": "라즈베리 입문자",
        "created_at": "2026. 09. 14",
        "source_title": "Raspberry Pi Documentation",
        "source_section": "Remote access > SSH",
        "source_url": "https://www.raspberrypi.com/documentation/computers/remote-access.html",
    },
    {
        "id": 2,
        "topic": "OS 설치",
        "title": "Raspberry Pi Imager에서 어떤 OS를 선택해야 하나요?",
        "question": "처음 Raspberry Pi를 설정합니다. 데스크톱 환경과 홈 서버 용도 중 어떤 Raspberry Pi OS를 선택하면 좋을지 알고 싶어요.",
        "summary": "화면을 연결해 사용하는 입문 환경에는 Desktop, 원격 접속 중심의 가벼운 서버 환경에는 Lite 선택을 먼저 비교해 보세요.",
        "author": "초보 메이커",
        "created_at": "2026. 09. 13",
        "source_title": "Raspberry Pi Documentation",
        "source_section": "Getting started > Install an operating system",
        "source_url": "https://www.raspberrypi.com/documentation/computers/getting-started.html",
    },
    {
        "id": 3,
        "topic": "활용하기",
        "title": "모니터 없이 Raspberry Pi를 처음 연결하려면 무엇이 필요한가요?",
        "question": "집에서 작은 서버로 써 보고 싶습니다. 모니터 없이 처음 전원을 켤 때 준비할 것과 네트워크 연결 순서가 궁금해요.",
        "summary": "Imager에서 네트워크와 원격 접속 정보를 미리 설정한 다음, 같은 네트워크에서 장치 주소를 확인해 접속하는 흐름으로 시작할 수 있습니다.",
        "author": "홈서버 도전자",
        "created_at": "2026. 09. 12",
        "source_title": "Raspberry Pi Documentation",
        "source_section": "Getting started > Set up your Raspberry Pi",
        "source_url": "https://www.raspberrypi.com/documentation/computers/getting-started.html",
    },
)


def _source_cards(response: ChatResponse, *, preferred_use_case: str | None = None) -> list[dict[str, str]]:
    """Convert team RAG citations into template-safe official source cards.

    The presenter may improve labels, but this boundary exposes only the
    citation title, section, tags, URL, and reviewed quote to the browser.
    """
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
    """Map a ``ChatResponse`` contract to common Q&A/recommendation context."""
    preferred_use_case = response.conditions.use_case if response.conditions else None
    return {
        "response": response,
        "status_label": STATUS_LABELS[response.status],
        "is_blocked": response.status in BLOCKED_STATUSES,
        "source_cards": _source_cards(response, preferred_use_case=preferred_use_case),
        "images": [item for item in response.media if item.media_type == "image"],
        "videos": [item for item in response.media if item.media_type != "image"],
    }


def _inline_challenge_topic(response: ChatResponse) -> str | None:
    """Use cited, official document IDs rather than question text to select a topic."""

    if response.status != "answered":
        return None
    document_ids = {getattr(citation, "document_id", "") for citation in response.citations}
    if document_ids & REMOTE_ACCESS_DOCUMENT_IDS:
        return "remote_access"
    if document_ids & OS_INSTALLATION_DOCUMENT_IDS:
        return "os_installation"
    return None


def _inline_challenge_payload(result: dict) -> dict:
    """Return an answer-only browser payload without session or checksum data."""

    return {
        "correct": result["correct"],
        "selected_choice_id": result["selected_choice_id"],
        "correct_choice_id": result["correct_choice_id"],
        "rationale_ko": result["rationale_ko"],
        "choice_feedback": result["choice_feedback"],
        "evidence": result["evidence"],
    }


def _base_context(*, active_page: str) -> dict:
    """Add shared navigation state and non-blocking RAG readiness to a page."""
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
    """Return only catalog fields that a browser needs to render a template."""
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
    """Group approved command templates and selectable products for the lab UI."""
    service = get_command_lab_service()
    templates = service.list_templates()
    grouped_templates: dict[str, list[dict]] = {}
    for template in templates:
        grouped_templates.setdefault(template["topic"], []).append(template)
    return {
        "lab_templates": templates,
        "lab_topics": [
            {
                "id": topic,
                "label": LAB_TOPIC_LABELS.get(topic, topic.replace("_", " ").title()),
                "templates": items,
            }
            for topic, items in grouped_templates.items()
        ],
        "lab_products": [
            {"product_id": product["product_id"], "name": product["name"]}
            for product in service.products.values()
        ],
    }


def _selected_template(templates: list[dict], template_id: str | None) -> dict | None:
    """Find a previously validated template by ID without trusting request data."""
    return next((item for item in templates if item["template_id"] == template_id), None)


def _editable_fields(template: dict | None, values: dict | None) -> list[dict]:
    """Prepare only service-approved editable fields with current UI values."""
    if not template:
        return []
    current_values = values or {}
    return [
        {**field, "current_value": current_values.get(field["part_id"], field["example"])}
        for field in template["editable_fields"]
    ]


def _drawer_items(request, service) -> list[dict]:
    """Restore only current catalog entries; saved payloads stay server-side."""

    saved_items = request.session.get(LAB_DRAWER_SESSION_KEY, [])
    restored = []
    valid_saved = []
    for saved in saved_items:
        try:
            result = service.restore_drawer(saved)
        except ValueError:
            continue
        valid_saved.append(saved)
        restored.append(
            {
                "template_id": result["template_id"],
                "command": result["command"],
                "effect_ko": result["effect_ko"],
            }
        )
    if len(valid_saved) != len(saved_items):
        request.session[LAB_DRAWER_SESSION_KEY] = valid_saved
    return restored


@require_http_methods(["GET"])
def about(request):
    """Render the PiCare landing page and shared runtime readiness state."""
    return render(request, "portal/about.html", _base_context(active_page="about"))


@require_http_methods(["GET", "POST"])
def recommend(request):
    """Validate the recommendation form and delegate generation to team RAG.

    ``RecommendationFormInput`` is the adapter between Django widget labels
    and the recommendation domain contract; policy and evidence selection stay
    inside ``RecommendationRagService``.
    """
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
    """Submit a question to the team's grounded Q&A service and render sources.

    A reviewed one-question challenge is attached only when returned citation
    document IDs identify an SSH or OS-installation answer.
    """
    context = _base_context(active_page="qa")
    form = QuestionForm(request.POST or None, initial={"question": request.GET.get("question", "")})
    context["form"] = form
    if request.method == "POST" and form.is_valid():
        question = form.cleaned_data["question"]
        context["question"] = question
        try:
            response = get_qa_service().answer(
                request_id=str(uuid.uuid4()), question=question, retrieval_mode="hybrid", trace=True
            )
            context.update(_response_context(response))
            topic = _inline_challenge_topic(response)
            if topic:
                try:
                    started = get_challenge_service().start_inline(topic)
                    request.session[INLINE_CHALLENGE_SESSION_KEY] = started["state"]
                    context["inline_challenge"] = {
                        "topic": topic,
                        "topic_label": LAB_TOPIC_LABELS[topic],
                        "question": started["question"],
                        "submit_url": reverse("inline_challenge_submit_api"),
                        "challenge_url": f"{reverse('challenge')}?topic={topic}",
                    }
                except ValueError:
                    context["inline_challenge_error"] = "미니 챌린지 근거를 확인하지 못했습니다. 전체 학습에서 다시 시도해 주세요."
        except Exception as exc:
            context["service_error"] = f"QA 런타임을 준비하지 못했습니다: {exc}"
    return render(request, "portal/qa.html", context)


@require_http_methods(["GET"])
def questions(request):
    """Render the display-only member-question archive prototype.

    This page intentionally uses static preview data: it neither reads nor
    writes member questions, and it never invokes the AI Q&A service.
    """

    context = _base_context(active_page="questions")
    context["question_previews"] = QUESTION_ARCHIVE_PREVIEWS
    return render(request, "portal/questions.html", context)


@require_http_methods(["GET"])
def question_detail(request, question_id: int):
    """Show one static archive detail page without exposing a write path."""

    preview = next((item for item in QUESTION_ARCHIVE_PREVIEWS if item["id"] == question_id), None)
    if preview is None:
        raise Http404("질문을 찾을 수 없습니다.")
    context = _base_context(active_page="questions")
    context["question_post"] = preview
    return render(request, "portal/question_detail.html", context)


@require_http_methods(["GET", "POST"])
def lab(request):
    """Present the catalog-backed command lab; no submitted command is executed.

    Calls ``CommandLabService`` for every analyze, compose, and drawer action
    so request values cannot bypass the approved command catalog.
    """

    context = _base_context(active_page="lab")
    context["lab_mode"] = request.POST.get("mode") or request.GET.get("mode") or "examples"
    context["drawer_open"] = request.GET.get("drawer") == "1"
    context["analysis_form"] = CommandInputForm(request.POST or None)
    try:
        context.update(_lab_context())
    except Exception:
        context["lab_error"] = "명령어 실험실 데이터를 준비하지 못했습니다. 잠시 후 다시 시도해 주세요."
        return render(request, "portal/lab.html", context)

    service = get_command_lab_service()
    selected_result = None
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "analyze" and context["analysis_form"].is_valid():
                selected_result = _lab_payload(service.analyze(context["analysis_form"].cleaned_data["command"]))
            elif action == "compose":
                template_id = request.POST.get("template_id", "")
                item = service._item(template_id)
                values = {
                    field["part_id"]: request.POST.get(f"value_{field['part_id']}", "")
                    for field in item["editable_fields"]
                }
                product_id = request.POST.get("product_id") or None
                selected_result = _lab_payload(service.compose(template_id, values, product_id=product_id))
                context["analysis_form"] = CommandInputForm(initial={"command": selected_result["command"]})
            elif action == "save_drawer":
                template_id = request.POST.get("template_id", "")
                item = service._item(template_id)
                values = {
                    field["part_id"]: request.POST.get(f"value_{field['part_id']}", "")
                    for field in item["editable_fields"]
                }
                product_id = request.POST.get("product_id") or None
                selected_result = _lab_payload(service.compose(template_id, values, product_id=product_id))
                payload = service.drawer_payload(template_id, values, product_id=product_id)
                drawer = request.session.get(LAB_DRAWER_SESSION_KEY, [])
                if not any(saved.get("command_checksum") == payload["command_checksum"] for saved in drawer):
                    request.session[LAB_DRAWER_SESSION_KEY] = [*drawer, payload][-LAB_DRAWER_LIMIT:]
                context["drawer_saved"] = True
            elif action not in {"analyze", "compose", "save_drawer"}:
                context["lab_error"] = "요청을 확인하지 못했습니다."
        except ValueError as exc:
            context["lab_error"] = str(exc)
        except Exception:
            context["lab_error"] = "명령어 실험실을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요."
    elif context["lab_mode"] == "examples" and context["lab_templates"]:
        preferred = _selected_template(context["lab_templates"], "cmd-remote-access-004") or context["lab_templates"][0]
        selected_result = _lab_payload(service.compose(preferred["template_id"]))

    if selected_result:
        context["lab_result"] = selected_result
        context["selected_template"] = _selected_template(context["lab_templates"], selected_result["template_id"])
        context["lab_editable_fields"] = _editable_fields(context["selected_template"], selected_result["values"])
    context["drawer_items"] = _drawer_items(request, service)
    context["drawer_count"] = len(context["drawer_items"])
    return render(request, "portal/lab.html", context)


@require_http_methods(["GET", "POST"])
def challenge(request):
    """Run a three-question challenge with answer data kept on the server.

    ``ChallengeService`` selects and grades reviewed questions. Django stores
    only question IDs, shuffled choice order, and progress in the session.
    """

    context = _base_context(active_page="challenge")
    try:
        service = get_challenge_service()
        context["challenge_topics"] = service.topics()
        requested_topic = request.GET.get("topic", "")
        if requested_topic in {topic["id"] for topic in context["challenge_topics"]}:
            context["selected_challenge_topic"] = requested_topic
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


@require_http_methods(["POST"])
def inline_challenge_submit_api(request):
    """Grade the single Q&A follow-up with Django's normal CSRF protection."""

    try:
        state = request.session.get(INLINE_CHALLENGE_SESSION_KEY)
        if not state:
            raise ValueError("새 질문에 연결된 미니 챌린지를 다시 시작해 주세요.")
        outcome = get_challenge_service().submit_inline(
            state,
            question_id=request.POST.get("question_id", ""),
            choice_id=request.POST.get("choice_id", ""),
        )
        request.session.pop(INLINE_CHALLENGE_SESSION_KEY, None)
        return JsonResponse(_inline_challenge_payload(outcome))
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception:
        return JsonResponse({"error": "미니 챌린지를 채점하지 못했습니다. 잠시 후 다시 시도해 주세요."}, status=503)


def _json_body(request) -> dict:
    """Parse a JSON API body and reject non-object requests consistently."""
    try:
        value = json.loads(request.body)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("JSON 요청 본문을 확인해 주세요.") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON 객체를 보내 주세요.")
    return value


@require_http_methods(["GET"])
def lab_templates_api(request):
    """Expose browser-safe, approved command templates for future JS clients."""
    try:
        templates = [_lab_template_payload(item) for item in get_command_lab_service().list_templates()]
        return JsonResponse({"templates": templates})
    except Exception:
        return JsonResponse({"error": "명령어 실험실 데이터를 준비하지 못했습니다."}, status=503)


@require_http_methods(["POST"])
def lab_analyze_api(request):
    """Ask ``CommandLabService`` to analyze one non-executing command string."""
    try:
        body = _json_body(request)
        return JsonResponse(_lab_payload(get_command_lab_service().analyze(body.get("command"))))
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception:
        return JsonResponse({"error": "명령어 실험실을 처리하지 못했습니다."}, status=503)


@require_http_methods(["POST"])
def lab_compose_api(request):
    """Ask ``CommandLabService`` to compose validated editable command parts."""
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
    """Report whether external RAG prerequisites are available to this worker."""
    readiness = get_runtime_readiness()
    return JsonResponse(
        {
            "status": "ok" if readiness.ready else "not_ready",
            "ready": readiness.ready,
            "message": readiness.message,
        }
    )
