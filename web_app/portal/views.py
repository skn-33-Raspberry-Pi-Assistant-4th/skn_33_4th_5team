"""Django views that present existing PiCare service responses."""

from __future__ import annotations

import json
import logging
import uuid

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from src.condition_extraction.ui_input import RecommendationFormInput
from src.contracts import ChatResponse, QuizResponse

from .forms import (
    CommandAnalyzeForm,
    CommandInputForm,
    CommentForm,
    PostForm,
    ProfileUpdateForm,
    QuestionForm,
    RecommendationForm,
    SignUpForm,
)
from .models import Comment, DrawerItem, Post, PostLike, WrongNote
from .services import (
    get_challenge_service,
    get_citation_presenter,
    get_command_lab_service,
    get_qa_service,
    get_recommendation_service,
    get_runtime_readiness,
)
from src.services.command_lab_service import CommandLabError, CommandLabService
from src.services.quiz_generator import QuizGenerator


STATUS_LABELS = {
    "answered": "근거 확인 완료",
    "needs_clarification": "추가 정보 필요",
    "insufficient_evidence": "근거 부족",
    "out_of_scope": "답변 범위 외",
    "safety_blocked": "안전 정책으로 보류",
    "error": "실행 오류",
}
BLOCKED_STATUSES = {"needs_clarification", "insufficient_evidence", "out_of_scope", "safety_blocked", "error"}
COMMUNITY_PAGE_SIZE = 10
ACTIVITY_PAGE_SIZE = 10
MYPAGE_RECENT_LIMIT = 5
QA_SESSION_KEY = "latest_qa_response"
QUIZ_SESSION_KEY = "mini_challenge"
CHALLENGE_SESSION_KEY = "picare_challenge"
INLINE_CHALLENGE_SESSION_KEY = "picare_inline_challenge"
LAB_DRAWER_SESSION_KEY = "picare_command_lab_drawer"
LAB_DRAWER_LIMIT = 10

LAB_TOPIC_LABELS = {
    "remote_access": "원격 접속",
    "os_installation": "OS 설치",
}
REMOTE_ACCESS_DOCUMENT_IDS = frozenset({"rpi-doc-remote-access-ssh"})
OS_INSTALLATION_DOCUMENT_IDS = frozenset(
    {"rpi-doc-getting-started-install", "rpi-doc-getting-started-setting-up"}
)

# This is a display-only archive supplied by the existing frontend.  It does
# not persist or expose a member's private data.
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

logger = logging.getLogger(__name__)


def _command_lab_error_response(error: CommandLabError) -> JsonResponse:
    return JsonResponse({"error": str(error)}, status=400)


def _command_lab_unavailable_response() -> JsonResponse:
    return JsonResponse({"error": "명령어 실험실을 일시적으로 이용할 수 없습니다."}, status=503)


def _json_request_data(request) -> tuple[dict | None, JsonResponse | None]:
    if request.content_type != "application/json":
        return None, JsonResponse({"error": "application/json 요청만 지원합니다."}, status=400)
    try:
        data = json.loads(request.body)
    except (TypeError, json.JSONDecodeError):
        return None, JsonResponse({"error": "JSON 본문을 확인해 주세요."}, status=400)
    if not isinstance(data, dict):
        return None, JsonResponse({"error": "JSON 객체가 필요합니다."}, status=400)
    return data, None


def _form_compose_arguments(service: CommandLabService, data) -> tuple[str, dict[str, str], str | None]:
    """Collect only catalog-declared editable values before calling the service."""

    template_id = data.get("template_id")
    preview = service.compose(template_id)
    values = {
        part["part_id"]: data.get(f"value_{part['part_id']}", part["value"])
        for part in preview["parts"]
        if part["editable"]
    }
    product_id = data.get("product_id") or None
    return template_id, values, product_id


def get_quiz_generator(qa_service) -> QuizGenerator:
    """Wrap the already assembled QA answer generator; never create another model."""

    answer_generator = getattr(qa_service, "answer_generator", None)
    if answer_generator is None or not hasattr(answer_generator, "generate_structured"):
        raise RuntimeError("현재 Q&A 생성기는 퀴즈 structured generation을 지원하지 않습니다.")

    from src.rag_to_llm.quiz_text_generator import HuggingFaceQuizTextGenerator

    return QuizGenerator(HuggingFaceQuizTextGenerator(answer_generator))


def _store_qa_response(request, response, question: str) -> bool:
    """Keep only the latest server-built Q&A result for a transient challenge."""

    if not isinstance(response, ChatResponse):
        return False
    request.session[QA_SESSION_KEY] = {
        "response": response.model_dump(mode="json"),
        "question": question,
    }
    request.session.pop(QUIZ_SESSION_KEY, None)
    return True


def _load_qa_response(request) -> tuple[ChatResponse, str] | None:
    saved = request.session.get(QA_SESSION_KEY)
    if not isinstance(saved, dict) or not isinstance(saved.get("response"), dict):
        return None
    try:
        return ChatResponse.model_validate(saved["response"]), str(saved.get("question", ""))
    except (TypeError, ValueError):
        request.session.pop(QA_SESSION_KEY, None)
        return None


def _qa_result_context(response: ChatResponse, question: str) -> dict:
    context = _response_context(response)
    context.update({"form": QuestionForm(initial={"question": question}), "question": question})
    return context


def _store_quiz_response(request, quiz_response: QuizResponse) -> str:
    quiz_id = str(uuid.uuid4())
    request.session[QUIZ_SESSION_KEY] = {
        "quiz_id": quiz_id,
        "response": quiz_response.model_dump(mode="json"),
        "submissions": {},
    }
    return quiz_id


def _load_quiz_response(request, quiz_id: str) -> tuple[QuizResponse, dict] | None:
    saved = request.session.get(QUIZ_SESSION_KEY)
    if not isinstance(saved, dict) or saved.get("quiz_id") != str(quiz_id) or not isinstance(saved.get("response"), dict):
        return None
    try:
        return QuizResponse.model_validate(saved["response"]), saved
    except (TypeError, ValueError):
        request.session.pop(QUIZ_SESSION_KEY, None)
        return None


def _quiz_context(quiz_id: str, quiz_response: QuizResponse, *, submission: dict | None = None) -> dict:
    return {
        "quiz_id": quiz_id,
        "quiz_response": quiz_response,
        "quiz_status": quiz_response.status,
        "quiz_submission": submission,
    }


def _question_or_none(quiz_response: QuizResponse, question_id: str | None):
    return next((question for question in quiz_response.questions if question.question_id == question_id), None)


def _activity_page(request, queryset):
    """Paginate a user-owned activity queryset without accepting a user identifier."""

    return Paginator(queryset, ACTIVITY_PAGE_SIZE).get_page(request.GET.get("page"))


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


def _inline_challenge_topic(response: ChatResponse) -> str | None:
    """Select an inline challenge only from cited, approved document IDs."""

    if response.status != "answered":
        return None
    document_ids = {getattr(citation, "document_id", "") for citation in response.citations}
    if document_ids & REMOTE_ACCESS_DOCUMENT_IDS:
        return "remote_access"
    if document_ids & OS_INSTALLATION_DOCUMENT_IDS:
        return "os_installation"
    return None


def _inline_challenge_payload(result: dict) -> dict:
    """Return the reviewed grading result without exposing server session state."""

    return {
        "correct": result["correct"],
        "selected_choice_id": result["selected_choice_id"],
        "correct_choice_id": result["correct_choice_id"],
        "rationale_ko": result["rationale_ko"],
        "choice_feedback": result["choice_feedback"],
        "evidence": result["evidence"],
    }


def _lab_evidence_cards(evidence: list[dict]) -> list[dict[str, str]]:
    """Expose only browser-safe source labels for the existing lab UI."""

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
    """Create the payload expected by the pre-existing command-lab template."""

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
    return next((item for item in templates if item["template_id"] == template_id), None)


def _editable_fields(template: dict | None, values: dict | None) -> list[dict]:
    if not template:
        return []
    current_values = values or {}
    return [
        {**field, "current_value": current_values.get(field["part_id"], field["example"])}
        for field in template["editable_fields"]
    ]


def _drawer_items(request, service) -> list[dict]:
    """Restore legacy session drawer entries without touching member drawers."""

    saved_items = request.session.get(LAB_DRAWER_SESSION_KEY, [])
    restored, valid_saved = [], []
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


def _base_context(*, active_page: str) -> dict:
    readiness = get_runtime_readiness()
    runtime_message = readiness.message if readiness.ready else "RAG 실행 환경을 준비하지 못했습니다. 설정을 확인해 주세요."
    return {"active_page": active_page, "runtime_ready": readiness.ready, "runtime_message": runtime_message}


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
        except Exception:
            logger.error("Recommendation service failed while processing a form request")
            context["service_error"] = "제품 추천 서비스를 일시적으로 이용할 수 없습니다. 잠시 후 다시 시도해 주세요."
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
            qa_service = get_qa_service()
            response = qa_service.answer(
                request_id=str(uuid.uuid4()), question=question, retrieval_mode="hybrid", trace=True
            )
            context.update(_response_context(response))
            context["quiz_can_generate"] = _store_qa_response(request, response, question) and response.status == "answered" and bool(response.citations)
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
        except Exception:
            logger.error("Q&A service failed while processing a question")
            context["service_error"] = "Q&A 서비스를 일시적으로 이용할 수 없습니다. 잠시 후 다시 시도해 주세요."
    return render(request, "portal/qa.html", context)


@require_http_methods(["GET"])
def questions(request):
    """Render the existing display-only question archive."""

    context = _base_context(active_page="questions")
    context["question_previews"] = QUESTION_ARCHIVE_PREVIEWS
    return render(request, "portal/questions.html", context)


@require_http_methods(["GET"])
def question_detail(request, question_id: int):
    preview = next((item for item in QUESTION_ARCHIVE_PREVIEWS if item["id"] == question_id), None)
    if preview is None:
        raise Http404("질문을 찾을 수 없습니다.")
    context = _base_context(active_page="questions")
    context["question_post"] = preview
    return render(request, "portal/question_detail.html", context)


@require_http_methods(["GET", "POST"])
def lab(request):
    """Keep the existing lab UI while adding authenticated DB drawer saves."""

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
            elif action in {"compose", "save_drawer"}:
                template_id = request.POST.get("template_id", "")
                item = service._item(template_id)
                values = {
                    field["part_id"]: request.POST.get(f"value_{field['part_id']}", "")
                    for field in item["editable_fields"]
                }
                product_id = request.POST.get("product_id") or None
                selected_result = _lab_payload(service.compose(template_id, values, product_id=product_id))
                context["analysis_form"] = CommandInputForm(initial={"command": selected_result["command"]})
                if action == "save_drawer":
                    payload = service.drawer_payload(template_id, values, product_id=product_id)
                    if request.user.is_authenticated:
                        saved_item = DrawerItem.objects.create(
                            owner=request.user,
                            title=payload["command_snapshot"][:200],
                            kind=payload["kind"],
                            payload=payload,
                        )
                        context["drawer_detail_url"] = reverse("drawer_detail", kwargs={"pk": saved_item.pk})
                    else:
                        drawer = request.session.get(LAB_DRAWER_SESSION_KEY, [])
                        if not any(saved.get("command_checksum") == payload["command_checksum"] for saved in drawer):
                            request.session[LAB_DRAWER_SESSION_KEY] = [*drawer, payload][-LAB_DRAWER_LIMIT:]
                    context["drawer_saved"] = True
            elif action not in {"analyze", "compose", "save_drawer"}:
                context["lab_error"] = "요청을 확인하지 못했습니다."
        except CommandLabError as exc:
            context["lab_error"] = str(exc)
        except Exception:
            logger.error("Command lab page request failed")
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
    """Run the existing reviewed three-question challenge in the session."""

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


@require_POST
def inline_challenge_submit_api(request):
    """Grade the existing Q&A follow-up with normal Django CSRF protection."""

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
    try:
        value = json.loads(request.body)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("JSON 요청 본문을 확인해 주세요.") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON 객체를 보내 주세요.")
    return value


@require_GET
def lab_templates_api(request):
    try:
        templates = [_lab_template_payload(item) for item in get_command_lab_service().list_templates()]
        return JsonResponse({"templates": templates})
    except Exception:
        return JsonResponse({"error": "명령어 실험실 데이터를 준비하지 못했습니다."}, status=503)


@require_POST
def lab_analyze_api(request):
    try:
        return JsonResponse(_lab_payload(get_command_lab_service().analyze(_json_body(request).get("command"))))
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception:
        return JsonResponse({"error": "명령어 실험실을 처리하지 못했습니다."}, status=503)


@require_POST
def lab_compose_api(request):
    try:
        body = _json_body(request)
        result = get_command_lab_service().compose(
            body.get("template_id"), body.get("values"), product_id=body.get("product_id")
        )
        return JsonResponse(_lab_payload(result))
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
            "message": readiness.message if readiness.ready else "RAG 실행 환경을 준비하지 못했습니다. 설정을 확인해 주세요.",
        }
    )


@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated:
        return redirect("profile_edit")

    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "회원가입이 완료되었습니다.")
        return redirect("profile_edit")
    return render(request, "portal/signup.html", {"form": form})


@login_required
@require_http_methods(["GET", "POST"])
def profile_edit(request):
    form = ProfileUpdateForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "회원정보를 수정했습니다.")
        return redirect("profile_edit")
    return render(request, "portal/profile_edit.html", {"form": form, "active_page": "profile"})


@login_required
@require_GET
def mypage(request):
    """Show only the authenticated member's account summary and recent activity."""

    user = request.user
    context = {
        "member": user,
        "activity_counts": {
            "posts": Post.objects.filter(author=user).count(),
            "comments": Comment.objects.filter(author=user).count(),
            "likes": PostLike.objects.filter(user=user).count(),
            "drawer_items": DrawerItem.objects.filter(owner=user).count(),
            "wrong_notes": WrongNote.objects.filter(owner=user).count(),
        },
        "recent_posts": Post.objects.filter(author=user).select_related("author")[:MYPAGE_RECENT_LIMIT],
        "recent_comments": Comment.objects.filter(author=user).select_related("post")[:MYPAGE_RECENT_LIMIT],
        "recent_likes": PostLike.objects.filter(user=user).select_related("post", "post__author")[:MYPAGE_RECENT_LIMIT],
        "recent_drawer_items": DrawerItem.objects.filter(owner=user)[:MYPAGE_RECENT_LIMIT],
        "recent_wrong_notes": WrongNote.objects.filter(owner=user)[:MYPAGE_RECENT_LIMIT],
        "active_page": "mypage",
    }
    return render(request, "portal/mypage.html", context)


@login_required
@require_GET
def mypage_posts(request):
    posts = (
        Post.objects.filter(author=request.user)
        .select_related("author")
        .annotate(like_count=Count("likes", distinct=True), comment_count=Count("comments", distinct=True))
        .order_by("-created_at", "-id")
    )
    return render(
        request,
        "portal/mypage_posts.html",
        {"page_obj": _activity_page(request, posts), "active_page": "mypage"},
    )


@login_required
@require_GET
def mypage_comments(request):
    comments = Comment.objects.filter(author=request.user).select_related("post", "post__author")
    return render(
        request,
        "portal/mypage_comments.html",
        {"page_obj": _activity_page(request, comments), "active_page": "mypage"},
    )


@login_required
@require_GET
def mypage_likes(request):
    likes = PostLike.objects.filter(user=request.user).select_related("post", "post__author")
    return render(
        request,
        "portal/mypage_likes.html",
        {"page_obj": _activity_page(request, likes), "active_page": "mypage"},
    )


@require_GET
def community_list(request):
    posts = Post.objects.select_related("author").annotate(like_count=Count("likes")).order_by("-created_at", "-id")
    page_obj = Paginator(posts, COMMUNITY_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "portal/community_list.html", {"page_obj": page_obj, "active_page": "community"})


@require_GET
def community_post_detail(request, pk: int):
    comment_queryset = Comment.objects.select_related("author")
    post_queryset = (
        Post.objects.select_related("author")
        .annotate(like_count=Count("likes"))
        .prefetch_related(Prefetch("comments", queryset=comment_queryset, to_attr="prefetched_comments"))
    )
    if request.user.is_authenticated:
        post_queryset = post_queryset.prefetch_related(
            Prefetch("likes", queryset=PostLike.objects.filter(user=request.user), to_attr="current_user_likes")
        )

    post = get_object_or_404(post_queryset, pk=pk)
    return render(
        request,
        "portal/community_detail.html",
        {
            "post": post,
            "comments": post.prefetched_comments,
            "comment_form": CommentForm(),
            "is_liked": bool(getattr(post, "current_user_likes", [])),
            "active_page": "community",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def community_post_create(request):
    form = PostForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        post = form.save(commit=False)
        post.author = request.user
        post.save()
        messages.success(request, "게시글을 작성했습니다.")
        return redirect("community_post_detail", pk=post.pk)
    return render(request, "portal/community_form.html", {"form": form, "active_page": "community"})


@login_required
@require_http_methods(["GET", "POST"])
def community_post_edit(request, pk: int):
    post = get_object_or_404(Post, pk=pk, author=request.user)
    form = PostForm(request.POST or None, instance=post)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "게시글을 수정했습니다.")
        return redirect("community_post_detail", pk=post.pk)
    return render(
        request,
        "portal/community_form.html",
        {"form": form, "post": post, "is_edit": True, "active_page": "community"},
    )


@login_required
@require_POST
def community_post_delete(request, pk: int):
    post = get_object_or_404(Post, pk=pk, author=request.user)
    post.delete()
    messages.success(request, "게시글을 삭제했습니다.")
    return redirect("community_list")


@login_required
@require_POST
def community_comment_create(request, pk: int):
    post = get_object_or_404(Post, pk=pk)
    form = CommentForm(request.POST)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.post = post
        comment.author = request.user
        comment.save()
        messages.success(request, "댓글을 작성했습니다.")
    else:
        messages.warning(request, "댓글 내용을 확인해 주세요.")
    return redirect("community_post_detail", pk=post.pk)


@login_required
@require_http_methods(["GET", "POST"])
def community_comment_edit(request, pk: int, comment_pk: int):
    comment = get_object_or_404(Comment.objects.select_related("post"), pk=comment_pk, post_id=pk, author=request.user)
    form = CommentForm(request.POST or None, instance=comment)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "댓글을 수정했습니다.")
        return redirect("community_post_detail", pk=comment.post_id)
    return render(
        request,
        "portal/community_comment_form.html",
        {"form": form, "post": comment.post, "comment": comment, "active_page": "community"},
    )


@login_required
@require_POST
def community_comment_delete(request, pk: int, comment_pk: int):
    comment = get_object_or_404(Comment, pk=comment_pk, post_id=pk, author=request.user)
    comment.delete()
    messages.success(request, "댓글을 삭제했습니다.")
    return redirect("community_post_detail", pk=pk)


@login_required
@require_POST
def community_post_like(request, pk: int):
    post = get_object_or_404(Post, pk=pk)
    like, created = PostLike.objects.get_or_create(post=post, user=request.user)
    if created:
        messages.success(request, "게시글을 추천했습니다.")
    else:
        like.delete()
        messages.success(request, "게시글 추천을 취소했습니다.")
    return redirect("community_post_detail", pk=post.pk)


@require_GET
def api_lab_templates(request):
    try:
        return JsonResponse({"templates": get_command_lab_service().list_templates()})
    except CommandLabError as error:
        return _command_lab_error_response(error)
    except Exception:
        logger.error("Command lab template listing failed")
        return _command_lab_unavailable_response()


@require_POST
def api_lab_analyze(request):
    data, error_response = _json_request_data(request)
    if error_response is not None:
        return error_response
    try:
        return JsonResponse(get_command_lab_service().analyze(data.get("command")))
    except CommandLabError as error:
        return _command_lab_error_response(error)
    except Exception:
        logger.error("Command lab analysis failed")
        return _command_lab_unavailable_response()


@require_POST
def api_lab_compose(request):
    data, error_response = _json_request_data(request)
    if error_response is not None:
        return error_response
    try:
        return JsonResponse(
            get_command_lab_service().compose(
                data.get("template_id"), data.get("values"), product_id=data.get("product_id")
            )
        )
    except CommandLabError as error:
        return _command_lab_error_response(error)
    except Exception:
        logger.error("Command lab composition failed")
        return _command_lab_unavailable_response()


@require_http_methods(["GET", "POST"])
def command_lab(request):
    form = CommandAnalyzeForm(request.POST or None)
    context = {"form": form, "active_page": "lab"}
    try:
        service = get_command_lab_service()
        context["templates"] = service.list_templates()
        if request.method == "POST":
            action = request.POST.get("action")
            if action == "analyze" and form.is_valid():
                context["result"] = service.analyze(form.cleaned_data["command"])
            elif action == "compose":
                template_id, values, product_id = _form_compose_arguments(service, request.POST)
                context["result"] = service.compose(template_id, values, product_id=product_id)
            elif action not in {"analyze", "compose"}:
                context["lab_error"] = "지원하지 않는 요청입니다."
    except CommandLabError as error:
        context["lab_error"] = str(error)
    except Exception:
        logger.error("Command lab page request failed")
        context["lab_error"] = "명령어 실험실을 일시적으로 이용할 수 없습니다. 잠시 후 다시 시도해 주세요."
    return render(request, "portal/command_lab.html", context)


@login_required
@require_GET
def drawer_list(request):
    items = DrawerItem.objects.filter(owner=request.user)
    page_obj = _activity_page(request, items)
    return render(
        request,
        "portal/drawer_list.html",
        {"items": page_obj, "page_obj": page_obj, "active_page": "drawer"},
    )


@login_required
@require_POST
def drawer_save(request):
    try:
        service = get_command_lab_service()
        template_id, values, product_id = _form_compose_arguments(service, request.POST)
        # Never accept a client command snapshot or checksum: recreate the full payload server-side.
        payload = service.drawer_payload(template_id, values, product_id=product_id)
    except CommandLabError as error:
        messages.warning(request, str(error))
        return redirect("command_lab")
    except Exception:
        logger.error("Command lab drawer save failed")
        messages.error(request, "서랍장에 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.")
        return redirect("command_lab")

    item = DrawerItem.objects.create(
        owner=request.user,
        title=payload["command_snapshot"][:200],
        kind=payload["kind"],
        payload=payload,
    )
    messages.success(request, "명령어 결과를 서랍장에 저장했습니다.")
    return redirect("drawer_detail", pk=item.pk)


@login_required
@require_GET
def drawer_detail(request, pk: int):
    item = get_object_or_404(DrawerItem, pk=pk, owner=request.user)
    context = {"item": item, "active_page": "drawer"}
    try:
        context["result"] = get_command_lab_service().restore_drawer(item.payload)
    except CommandLabError as error:
        context["needs_reconfirmation"] = True
        context["reconfirmation_message"] = str(error)
    except Exception:
        logger.error("Command lab drawer restore failed")
        context["needs_reconfirmation"] = True
        context["reconfirmation_message"] = "서랍장 항목을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요."
    return render(request, "portal/drawer_detail.html", context)


@login_required
@require_POST
def drawer_delete(request, pk: int):
    item = get_object_or_404(DrawerItem, pk=pk, owner=request.user)
    item.delete()
    messages.success(request, "서랍장 항목을 삭제했습니다.")
    return redirect("drawer_list")


@require_POST
def quiz_generate(request):
    loaded_qa = _load_qa_response(request)
    if loaded_qa is None:
        messages.warning(request, "퀴즈를 만들 Q&A 결과가 없습니다. 먼저 질문을 제출해 주세요.")
        return redirect("qa")

    response, question = loaded_qa
    context = _qa_result_context(response, question)
    if response.status != "answered" or not response.citations:
        quiz_response = QuizResponse(status="insufficient_content", questions=[])
    else:
        try:
            # This reuses the cached Q&A service's answer generator and never calls qa_service.answer().
            quiz_response = get_quiz_generator(get_qa_service()).generate_from_chat_response(response, max_questions=3)
        except Exception:
            quiz_response = QuizResponse(status="generation_failed", questions=[])

    quiz_id = _store_quiz_response(request, quiz_response)
    context.update(_quiz_context(quiz_id, quiz_response))
    return render(request, "portal/qa.html", context)


@require_POST
def quiz_submit(request, quiz_id):
    loaded_qa = _load_qa_response(request)
    loaded_quiz = _load_quiz_response(request, str(quiz_id))
    if loaded_qa is None or loaded_quiz is None:
        messages.warning(request, "퀴즈가 만료되었습니다. Q&A 결과에서 다시 시작해 주세요.")
        return redirect("qa")

    response, question_text = loaded_qa
    quiz_response, saved_quiz = loaded_quiz
    question = _question_or_none(quiz_response, request.POST.get("question_id"))
    selected_choice_id = request.POST.get("selected_choice_id")
    if question is None or selected_choice_id not in {choice.id for choice in question.choices}:
        messages.warning(request, "유효한 선택지를 골라 주세요.")
        context = _qa_result_context(response, question_text)
        context.update(_quiz_context(str(quiz_id), quiz_response))
        return render(request, "portal/qa.html", context)

    submissions = saved_quiz.setdefault("submissions", {})
    submissions[question.question_id] = selected_choice_id
    request.session[QUIZ_SESSION_KEY] = saved_quiz
    submission = {
        "question_id": question.question_id,
        "selected_choice_id": selected_choice_id,
        "correct_choice_id": question.correct_choice_id,
        "is_correct": selected_choice_id == question.correct_choice_id,
    }
    context = _qa_result_context(response, question_text)
    context.update(_quiz_context(str(quiz_id), quiz_response, submission=submission))
    return render(request, "portal/qa.html", context)


@login_required
@require_POST
def wrong_note_save(request, quiz_id):
    loaded_quiz = _load_quiz_response(request, str(quiz_id))
    if loaded_quiz is None:
        messages.warning(request, "퀴즈가 만료되었습니다. Q&A 결과에서 다시 시작해 주세요.")
        return redirect("qa")

    quiz_response, saved_quiz = loaded_quiz
    question = _question_or_none(quiz_response, request.POST.get("question_id"))
    selected_choice_id = saved_quiz.get("submissions", {}).get(question.question_id) if question is not None else None
    if question is None or selected_choice_id is None:
        messages.warning(request, "저장할 오답 풀이 결과가 없습니다.")
        return redirect("qa")
    if selected_choice_id == question.correct_choice_id:
        messages.warning(request, "정답은 오답노트에 저장하지 않습니다.")
        return redirect("qa")

    wrong_note = WrongNote.objects.create(
        owner=request.user,
        question_id=question.question_id,
        question=question.question,
        choices=[choice.model_dump(mode="json") for choice in question.choices],
        selected_choice_id=selected_choice_id,
        correct_choice_id=question.correct_choice_id,
        explanation=question.explanation,
        evidence_ids=question.evidence_ids,
        supporting_quotes=question.supporting_quotes,
    )
    messages.success(request, "오답노트에 저장했습니다.")
    return redirect("wrong_note_detail", pk=wrong_note.pk)


@login_required
@require_GET
def wrong_note_list(request):
    notes = WrongNote.objects.filter(owner=request.user)
    page_obj = _activity_page(request, notes)
    return render(
        request,
        "portal/wrong_note_list.html",
        {"notes": page_obj, "page_obj": page_obj, "active_page": "wrong_notes"},
    )


@login_required
@require_GET
def wrong_note_detail(request, pk: int):
    note = get_object_or_404(WrongNote, pk=pk, owner=request.user)
    return render(request, "portal/wrong_note_detail.html", {"note": note, "active_page": "wrong_notes"})


@login_required
@require_POST
def wrong_note_delete(request, pk: int):
    note = get_object_or_404(WrongNote, pk=pk, owner=request.user)
    note.delete()
    messages.success(request, "오답노트를 삭제했습니다.")
    return redirect("wrong_note_list")
