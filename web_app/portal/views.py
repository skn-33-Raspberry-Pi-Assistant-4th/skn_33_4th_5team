"""Django views that present existing PiCare service responses."""

from __future__ import annotations

import json
import logging
import re
import uuid

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Prefetch
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from src.condition_extraction.ui_input import (
    PERFORMANCE_PRIORITY_LABELS,
    USER_LEVEL_LABELS,
    RecommendationFormInput,
)
from src.contracts import ChatResponse, QaSummaryResult, QuizResponse
from src.rag_to_llm.qa_summary_text_generator import build_qa_summary_text_generator
from src.services.qa_summary import QaSummaryService

from .forms import (
    CommandAnalyzeForm,
    CommandInputForm,
    CommentForm,
    PostForm,
    ProfileUpdateForm,
    QuestionForm,
    RecommendationForm,
)
from .ai_jobs import cancel_job, create_job, owned_job, refresh_job, remote_enabled
from .models import AiJob, Comment, DrawerItem, Post, PostLike, QuestionRecord, RecommendationRecord, WrongNote
from .remote_ai import RemoteAIError, RunPodClient
from .result_service import (
    get_challenge_result,
    get_command_lab_result,
    get_qa_result,
    get_recommendation_result,
)
from .services import (
    get_citation_presenter,
    get_command_lab_service,
    get_qa_service,
    get_recommendation_service,
    get_runtime_readiness,
)
from src.services.command_lab_service import CommandLabError, CommandLabFieldError, CommandLabService

from pathlib import Path

from django.http import Http404, HttpResponse, JsonResponse


STATUS_LABELS = {
    "answered": "근거 확인 완료",
    "needs_clarification": "추가 정보 필요",
    "insufficient_evidence": "근거 부족",
    "out_of_scope": "답변 범위 외",
    "safety_blocked": "안전 정책으로 보류",
    "error": "실행 오류",
}
BLOCKED_STATUSES = {"needs_clarification", "insufficient_evidence", "out_of_scope", "safety_blocked", "error"}
LAB_TOPIC_LABELS = {
    "remote_access": "원격 접속",
    "networking": "네트워크",
    "os_installation": "운영체제 설치",
    "storage": "저장장치",
    "camera": "카메라",
    "interfaces": "인터페이스",
    "system_status": "시스템 상태",
}
COMMUNITY_PAGE_SIZE = 10
ACTIVITY_PAGE_SIZE = 10
MYPAGE_RECENT_LIMIT = 5
QA_SESSION_KEY = "latest_qa_response"
RECOMMENDATION_SESSION_KEY = "pending_recommendation"
QUIZ_SESSION_KEY = "mini_challenge"
QUIZ_JOB_SESSION_KEY = "mini_challenge_job"
LAB_DRAWER_SESSION_KEY = "picare_command_lab_drawer"
LAB_DRAWER_LIMIT = 10

logger = logging.getLogger(__name__)


def _command_lab_error_response(error: CommandLabError) -> JsonResponse:
    payload = {"error": str(error)}
    if isinstance(error, CommandLabFieldError):
        payload["field"] = error.part_id
    return JsonResponse(payload, status=400)


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


def _wants_json_response(request) -> bool:
    """Return whether the caller explicitly requested a JSON response."""

    return "application/json" in request.headers.get("Accept", "")


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


def get_quiz_generation_task():
    """Load Celery only when the asynchronous Quiz API is used."""

    from .tasks import generate_dynamic_quiz

    return generate_dynamic_quiz


def get_quiz_async_result(task_id: str):
    """Look up an asynchronous task without loading Celery during normal Q&A."""

    from celery.result import AsyncResult

    return AsyncResult(task_id)


def _cancel_active_quiz_job(request) -> None:
    """Stop an older Quiz task before replacing the session's Q&A result."""

    job = request.session.get(QUIZ_JOB_SESSION_KEY)
    if not isinstance(job, dict) or not job.get("task_id") or job.get("status") == "cancelled":
        request.session.pop(QUIZ_JOB_SESSION_KEY, None)
        return
    job["status"] = "cancelled"
    request.session[QUIZ_JOB_SESSION_KEY] = job
    try:
        get_quiz_async_result(str(job["task_id"])).revoke(terminate=True, signal="SIGTERM")
    except Exception:
        logger.warning("Unable to revoke stale Quiz task %s", job["task_id"], exc_info=True)


def _store_qa_response(request, response, question: str) -> bool:
    """Keep only the latest server-built Q&A result for a transient challenge."""

    if not isinstance(response, ChatResponse):
        return False
    _cancel_active_quiz_job(request)
    request.session[QA_SESSION_KEY] = {
        "response": response.model_dump(mode="json"),
        "question": question,
    }
    request.session.pop(QUIZ_SESSION_KEY, None)
    return True


def _qa_record_title(question: str) -> str:
    """Build a stable archive title without asking a model to generate one."""

    normalized = " ".join(question.split())
    first_sentence = re.split(r"(?<=[.!?])\s+", normalized, maxsplit=1)[0]
    return first_sentence[:200]


def _generate_qa_summary(service, question: str, response: ChatResponse) -> QaSummaryResult:
    """Generate archive metadata from the Q&A service's already-loaded answer model."""

    try:
        text_generator = build_qa_summary_text_generator(getattr(service, "answer_generator", None))
        return QaSummaryService(text_generator).generate(question, response)
    except Exception:
        logger.exception("Q&A summary generation failed; preserving the original response")
        return QaSummaryResult(
            question_title=None,
            question_title_status="generation_failed",
            answer_summary=None,
            answer_summary_status="generation_failed" if response.status == "answered" else "not_applicable",
        )


def _save_question_record(
    request,
    response: ChatResponse,
    question: str,
    summary: QaSummaryResult | None = None,
) -> QuestionRecord | None:
    """Persist only a server-built response for an authenticated member."""

    if not request.user.is_authenticated:
        return None
    try:
        generated_title = (
            summary.question_title
            if summary is not None and summary.question_title_status == "available"
            else None
        )
        return QuestionRecord.objects.create(
            owner=request.user,
            request_id=response.request_id,
            title=generated_title or _qa_record_title(question),
            question=question,
            answer=response.answer,
            status=response.status,
            response_payload=response.model_dump(mode="json"),
            question_title=summary.question_title if summary is not None else None,
            question_title_status=summary.question_title_status if summary is not None else None,
            answer_summary=summary.answer_summary if summary is not None else None,
            answer_summary_status=summary.answer_summary_status if summary is not None else None,
        )
    except Exception:
        logger.exception("Failed to save Q&A record")
        return None


def _question_record_response(record: QuestionRecord) -> ChatResponse | None:
    """Restore a saved response only when its immutable payload is still valid."""

    try:
        return ChatResponse.model_validate(record.response_payload)
    except (TypeError, ValueError):
        logger.warning("Question record %s has an invalid response payload", record.pk)
        return None


def _save_recommendation_record(
    request, request_form: RecommendationFormInput, response: ChatResponse
) -> RecommendationRecord | None:
    """Persist a validated server snapshot without hiding results on DB failure."""

    if not request.user.is_authenticated:
        return None
    try:
        validated_input = RecommendationFormInput.model_validate(request_form.model_dump(mode="json"))
        validated_response = ChatResponse.model_validate(response.model_dump(mode="json"))
        with transaction.atomic():
            # Serialize saves per member so double clicks cannot create duplicates.
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            existing = RecommendationRecord.objects.filter(
                owner=request.user,
                request_id=validated_response.request_id,
                input_payload__request_id=validated_input.request_id,
            ).first()
            if existing is not None:
                return existing
            return RecommendationRecord.objects.create(
                owner=request.user,
                request_id=validated_response.request_id,
                title=_qa_record_title(validated_input.free_text),
                question=validated_input.free_text,
                answer=validated_response.answer,
                status=validated_response.status,
                input_payload=validated_input.model_dump(mode="json"),
                response_payload=validated_response.model_dump(mode="json"),
            )
    except Exception:
        logger.exception("Failed to save recommendation record")
        return None


def _recommendation_record_context(record: RecommendationRecord) -> dict:
    """저장된 제품 추천 기록을 화면 표시용 컨텍스트로 변환한다."""

    context = {
        "record": record,
        "active_page": "mypage",
        "status_label": STATUS_LABELS.get(record.status, "저장된 답변"),
        "is_blocked": record.status in BLOCKED_STATUSES,
        "input_conditions": [],
        "snapshot_error": False,
    }
    try:
        saved_input = RecommendationFormInput.model_validate(record.input_payload)
        level_labels = {value: label for label, value in USER_LEVEL_LABELS.items()}
        performance_labels = {value: label for label, value in PERFORMANCE_PRIORITY_LABELS.items()}
        context["input_conditions"] = [
            ("사용자 수준", level_labels[saved_input.user_level]),
            ("성능 우선순위", performance_labels[saved_input.performance_priority]),
        ]
        for label, value in (
            ("Wi-Fi 필요", saved_input.wireless_required),
            ("카메라 사용", saved_input.camera_required),
            ("GPIO 사용", saved_input.gpio_required),
            ("모니터 없음", saved_input.monitor_absent),
        ):
            context["input_conditions"].append((label, "선택 안 함" if value is None else "예" if value else "아니오"))
    except (TypeError, ValueError):
        context["snapshot_error"] = True
        logger.warning("Recommendation record %s has an invalid input payload", record.pk)
    try:
        response = ChatResponse.model_validate(record.response_payload)
        context.update(_response_context(response))
    except (TypeError, ValueError):
        context["snapshot_error"] = True
        logger.warning("Recommendation record %s has an invalid response payload", record.pk)
    return context


def _question_record_context(record: QuestionRecord) -> dict:
    """Expose only user-facing response fields from a persisted snapshot."""

    response = _question_record_response(record)
    context = {
        "question_record": record,
        "saved_response": response,
        "status_label": STATUS_LABELS.get(record.status, "저장된 답변"),
        "is_blocked": record.status in BLOCKED_STATUSES,
        "source_cards": [],
        "images": [],
        "videos": [],
    }
    if response is not None:
        context.update(_response_context(response))
    return context


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


def _remote_qa_result(payload: object) -> tuple[ChatResponse, QaSummaryResult | None]:
    """Validate the QA-only RunPod envelope while accepting pre-deploy jobs."""

    if isinstance(payload, dict) and "response" in payload:
        response = ChatResponse.model_validate(payload["response"])
        summary_payload = payload.get("summary")
        summary = QaSummaryResult.model_validate(summary_payload) if summary_payload is not None else None
        return response, summary
    return ChatResponse.model_validate(payload), None


def _finalize_remote_job(request, job: AiJob) -> AiJob:
    """Validate one RunPod result and apply its Django-side effect once."""

    with transaction.atomic():
        job = owned_job(request, job.pk, lock=True)
        if job.status != "succeeded" or job.finalized_at is not None:
            return job
        try:
            if job.kind == "qa":
                response, summary = _remote_qa_result(job.result_payload)
                question = str(job.input_payload["question"])
                _store_qa_response(request, response, question)
                job.question_record = _save_question_record(request, response, question, summary)
            elif job.kind == "recommendation":
                request_form = RecommendationFormInput.model_validate(job.input_payload)
                response = ChatResponse.model_validate(job.result_payload)
                if request.user.is_authenticated:
                    request.session[RECOMMENDATION_SESSION_KEY] = {
                        "token": str(job.save_token),
                        "owner_id": request.user.pk,
                        "input": request_form.model_dump(mode="json"),
                        "response": response.model_dump(mode="json"),
                    }
            elif job.kind == "quiz":
                quiz_response = QuizResponse.model_validate(job.result_payload)
                job.quiz_id = uuid.uuid4()
                request.session[QUIZ_SESSION_KEY] = {
                    "quiz_id": str(job.quiz_id),
                    "response": quiz_response.model_dump(mode="json"),
                    "submissions": {},
                }
            else:
                raise ValueError("unsupported feature")
        except (KeyError, TypeError, ValueError):
            logger.exception("Remote AI job %s returned an invalid result", job.pk)
            job.status = "failed"
            job.error_code = "invalid_response"
            job.result_payload = None
            job.save(update_fields=["status", "error_code", "result_payload", "updated_at"])
            return job
        job.finalized_at = timezone.now()
        job.save(update_fields=["question_record", "quiz_id", "finalized_at", "updated_at"])
        return job


def _remote_job_json(request, job: AiJob) -> dict:
    """Build a browser-safe status response; Quiz answer keys stay in session."""

    payload = {"job_id": str(job.pk), "kind": job.kind, "status": job.status}
    if job.error_code:
        payload["error"] = {"code": job.error_code, "message": "AI 작업을 완료하지 못했습니다. 다시 시도해 주세요."}
    if job.status != "succeeded":
        return payload
    if job.kind == "qa":
        payload["redirect_url"] = f"{reverse('qa')}?job={job.pk}"
    elif job.kind == "recommendation":
        payload["redirect_url"] = f"{reverse('recommend')}?job={job.pk}"
    elif job.kind == "quiz":
        quiz_response = QuizResponse.model_validate(job.result_payload)
        payload["status"] = quiz_response.status
        payload["quiz"] = _public_quiz_payload(quiz_response)
        if job.quiz_id:
            payload["quiz_id"] = str(job.quiz_id)
    return payload


def _store_quiz_response(request, quiz_response: QuizResponse) -> str:
    quiz_id = str(uuid.uuid4())
    request.session[QUIZ_SESSION_KEY] = {
        "quiz_id": quiz_id,
        "response": quiz_response.model_dump(mode="json"),
        "submissions": {},
    }
    return quiz_id


def _public_quiz_payload(quiz_response: QuizResponse) -> dict:
    """Expose only questions and choices until a user submits an answer."""

    return {
        "status": quiz_response.status,
        "questions": [
            {
                "question_id": question.question_id,
                "question": question.question,
                "choices": [{"id": choice.id, "text": choice.text} for choice in question.choices],
            }
            for question in quiz_response.questions
        ],
    }


def _quiz_evidence_cards(response: ChatResponse, question) -> list[dict[str, str]]:
    """퀴즈 문항의 근거 인용을 화면 표시용 카드 목록으로 변환한다."""

    citations = {citation.citation_id: citation for citation in response.citations}
    cards = []
    for citation_id in question.evidence_ids:
        citation = citations.get(citation_id)
        if citation is None:
            continue
        cards.append(
            {
                "title": citation.title,
                "section": citation.section,
                "url": str(citation.source_url),
                "quote": citation.quote,
            }
        )
    return cards


def _load_quiz_response(request, quiz_id: str) -> tuple[QuizResponse, dict] | None:
    saved = request.session.get(QUIZ_SESSION_KEY)
    if not isinstance(saved, dict) or saved.get("quiz_id") != str(quiz_id) or not isinstance(saved.get("response"), dict):
        return None
    try:
        return QuizResponse.model_validate(saved["response"]), saved
    except (TypeError, ValueError):
        request.session.pop(QUIZ_SESSION_KEY, None)
        return None


def _question_or_none(quiz_response: QuizResponse, question_id: str | None):
    return next((question for question in quiz_response.questions if question.question_id == question_id), None)


def _activity_page(request, queryset):
    """Paginate a user-owned activity queryset without accepting a user identifier."""

    return Paginator(queryset, ACTIVITY_PAGE_SIZE).get_page(request.GET.get("page"))


def _source_cards(response: ChatResponse, *, preferred_use_case: str | None = None) -> list[dict[str, str]]:
    """답변 인용 정보를 화면에 표시할 출처 카드 목록으로 변환한다."""

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
    """AI 응답을 상태·출처·미디어가 포함된 화면 컨텍스트로 변환한다."""

    preferred_use_case = response.conditions.use_case if response.conditions else None
    return {
        "response": response,
        "status_label": STATUS_LABELS[response.status],
        "is_blocked": response.status in BLOCKED_STATUSES,
        "source_cards": _source_cards(response, preferred_use_case=preferred_use_case),
        "images": [item for item in response.media if item.media_type == "image"],
        "videos": [item for item in response.media if item.media_type != "image"],
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
        "field_validation": result.get("field_validation", []),
        "validation_summary": result.get("validation_summary"),
    }


def _lab_template_payload(template: dict) -> dict:
    """명령어 템플릿에서 브라우저에 필요한 필드만 추려 반환한다."""

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
    """명령어 실험실의 템플릿·주제·제품 목록 컨텍스트를 구성한다."""

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
    """템플릿 ID와 일치하는 항목 하나를 찾아 반환한다."""

    return next((item for item in templates if item["template_id"] == template_id), None)


def _editable_fields(
    template: dict | None,
    values: dict | None,
    validations: list[dict] | None = None,
    errors: dict[str, str] | None = None,
) -> list[dict]:
    """템플릿 편집 필드에 현재 입력값을 합쳐 화면용 목록을 만든다."""

    if not template:
        return []
    current_values = values or {}
    validation_by_part = {item["part_id"]: item for item in validations or []}
    errors = errors or {}
    result = []
    for field in template["editable_fields"]:
        part_id = field["part_id"]
        validation = dict(validation_by_part.get(part_id, {}))
        if part_id in errors:
            validation.update({"status": "error", "message": errors[part_id]})
        result.append({
            **field,
            "current_value": current_values.get(part_id, field["example"]),
            "validation": validation,
        })
    return result


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
    if remote_enabled():
        return {
            "active_page": active_page,
            "runtime_ready": True,
            "runtime_message": "RunPod AI 서비스에 작업을 요청합니다.",
        }
    readiness = get_runtime_readiness()
    runtime_message = readiness.message if readiness.ready else "RAG 실행 환경을 준비하지 못했습니다. 설정을 확인해 주세요."
    return {"active_page": active_page, "runtime_ready": readiness.ready, "runtime_message": runtime_message}


@require_http_methods(["GET"])
def about(request):
    """서비스 소개 화면을 렌더링한다."""

    return render(request, "portal/about.html", _base_context(active_page="about"))


@require_http_methods(["GET", "POST"])
def recommend(request):
    """제품 추천 입력을 처리하고 로컬 또는 RunPod 결과를 표시한다."""

    context = _base_context(active_page="recommend")
    form = RecommendationForm(request.POST or None, initial={"purpose": "모니터 없이 홈 서버로 사용하고 싶어요."})
    context["form"] = form
    requested_job = request.GET.get("job")
    if request.method == "GET" and requested_job and remote_enabled():
        job = owned_job(request, requested_job, kind="recommendation")
        if job.status == "succeeded":
            job = _finalize_remote_job(request, job)
            try:
                request_form = RecommendationFormInput.model_validate(job.input_payload)
                response = ChatResponse.model_validate(job.result_payload)
                context["form"] = RecommendationForm(initial={
                    "purpose": request_form.free_text,
                })
                context.update(_response_context(response))
                if request.user.is_authenticated:
                    context["recommendation_save_token"] = str(job.save_token)
            except (TypeError, ValueError):
                context["service_error"] = "제품 추천 결과를 확인하지 못했습니다. 다시 요청해 주세요."
        else:
            context["service_error"] = "제품 추천 작업이 완료되지 않았습니다. 다시 요청해 주세요."
        return render(request, "portal/recommend.html", context)
    if request.method == "POST":
        request.session.pop(RECOMMENDATION_SESSION_KEY, None)
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
            if remote_enabled():
                context["ai_job"] = create_job(
                    request, "recommendation", request_form.model_dump(mode="json")
                )
                return render(request, "portal/recommend.html", context)
            feature_result = get_recommendation_result(get_recommendation_service(), form=request_form, trace=True)
            response = feature_result.result
            context["feature_result"] = feature_result
            context.update(_response_context(response))
            if request.user.is_authenticated:
                snapshot = {
                    "token": str(uuid.uuid4()),
                    "owner_id": request.user.pk,
                    "input": request_form.model_dump(mode="json"),
                    "response": ChatResponse.model_validate(response.model_dump(mode="json")).model_dump(mode="json"),
                }
                request.session[RECOMMENDATION_SESSION_KEY] = snapshot
                context["recommendation_save_token"] = snapshot["token"]
        except Exception:
            logger.error("Recommendation service failed while processing a form request")
            context["service_error"] = "제품 추천 서비스를 일시적으로 이용할 수 없습니다. 잠시 후 다시 시도해 주세요."
    return render(request, "portal/recommend.html", context)


@require_POST
def recommendation_save(request):
    """Save only the current member's latest server-built recommendation."""

    if not request.user.is_authenticated:
        return JsonResponse({"error": "로그인 후 제품추천을 다시 받아 주세요."}, status=401)
    snapshot = request.session.get(RECOMMENDATION_SESSION_KEY)
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("owner_id") != request.user.pk
        or not snapshot.get("token")
        or snapshot.get("token") != request.POST.get("token")
    ):
        return JsonResponse({"error": "저장할 추천 결과가 만료되었거나 변경되었습니다. 제품추천을 다시 받아 주세요."}, status=409)
    try:
        request_form = RecommendationFormInput.model_validate(snapshot["input"])
        response = ChatResponse.model_validate(snapshot["response"])
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"error": "저장할 추천 결과를 확인할 수 없습니다. 제품추천을 다시 받아 주세요."}, status=409)
    record = _save_recommendation_record(request, request_form, response)
    if record is None:
        return JsonResponse({"error": "제품추천 기록을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요."}, status=503)
    return JsonResponse({
        "message": "내 제품추천 기록에 저장했습니다.",
        "record_url": reverse("mypage_recommendation_detail", args=[record.pk]),
    })


@require_http_methods(["GET", "POST"])
def qa(request):
    """사용자 질문을 처리하고 RAG Q&A 결과와 퀴즈 연결 상태를 표시한다."""

    context = _base_context(active_page="qa")
    form = QuestionForm(request.POST or None, initial={"question": request.GET.get("question", "")})
    context["form"] = form
    requested_job = request.GET.get("job")
    if request.method == "GET" and requested_job and remote_enabled():
        job = owned_job(request, requested_job, kind="qa")
        if job.status == "succeeded":
            job = _finalize_remote_job(request, job)
            try:
                response, summary = _remote_qa_result(job.result_payload)
                question = str(job.input_payload["question"])
                context.update(_qa_result_context(response, question))
                context["qa_summary"] = summary
                context["qa_record"] = job.question_record
                context["qa_record_save_error"] = request.user.is_authenticated and job.question_record is None
                context["quiz_auto_start"] = response.status == "answered" and bool(response.citations)
            except (KeyError, TypeError, ValueError):
                context["service_error"] = "Q&A 결과를 확인하지 못했습니다. 다시 요청해 주세요."
        else:
            context["service_error"] = "Q&A 작업이 완료되지 않았습니다. 다시 요청해 주세요."
        return render(request, "portal/qa.html", context)
    if request.method == "POST" and form.is_valid():
        question = form.cleaned_data["question"]
        context["question"] = question
        try:
            if remote_enabled():
                context["ai_job"] = create_job(request, "qa", {
                    "question": question,
                    "retrieval_mode": "hybrid",
                    "trace": True,
                })
                return render(request, "portal/qa.html", context)
            service = get_qa_service()
            feature_result = get_qa_result(
                service,
                request_id=str(uuid.uuid4()),
                question=question,
                retrieval_mode="hybrid",
                trace=True,
            )
            response = feature_result.result
            summary = _generate_qa_summary(service, question, response)
            context["feature_result"] = feature_result
            context.update(_response_context(response))
            context["qa_summary"] = summary
            saved_record = _save_question_record(request, response, question, summary)
            if saved_record is not None:
                context["qa_record"] = saved_record
            elif request.user.is_authenticated:
                context["qa_record_save_error"] = True
            context["quiz_auto_start"] = (
                _store_qa_response(request, response, question)
                and response.status == "answered"
                and bool(response.citations)
            )
        except Exception:
            logger.error("Q&A service failed while processing a question")
            context["service_error"] = "Q&A 서비스를 일시적으로 이용할 수 없습니다. 잠시 후 다시 시도해 주세요."
    return render(request, "portal/qa.html", context)


def _quiz_api_error(code: str, message: str, status: int) -> JsonResponse:
    """미니 챌린지 API 오류를 일관된 JSON 형식으로 반환한다."""

    return JsonResponse({"error": {"code": code, "message": message}}, status=status)


@require_GET
def ai_job_status_api(request, job_id):
    """Poll a caller-owned RunPod job and finalize terminal output once."""

    job = owned_job(request, job_id)
    try:
        job = refresh_job(job)
    except RemoteAIError as exc:
        return _quiz_api_error(exc.code, "AI 서버 상태를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.", exc.status)
    if job.status == "succeeded":
        job = _finalize_remote_job(request, job)
    try:
        payload = _remote_job_json(request, job)
    except (TypeError, ValueError):
        return _quiz_api_error("invalid_response", "AI 서버 응답 형식을 확인하지 못했습니다.", 502)
    return JsonResponse(payload, status=202 if job.status not in {"succeeded", "failed", "cancelled", "expired"} else 200)


@require_POST
def ai_job_cancel_api(request, job_id):
    """Cancel only a job owned by the current user and browser session."""

    job = owned_job(request, job_id)
    job = cancel_job(job)
    return JsonResponse(_remote_job_json(request, job), status=202 if job.status == "cancelling" else 200)


@require_POST
def mini_challenge_start_api(request):
    """Queue C's Quiz generation from the latest server-created Q&A response."""

    data, error = _json_request_data(request)
    if error is not None:
        return error
    max_questions = data.get("max_questions", 3)
    if max_questions != 3:
        return _quiz_api_error("invalid_request", "현재 미니 챌린지는 최대 3문항으로 생성합니다.", 400)

    loaded_qa = _load_qa_response(request)
    if loaded_qa is None:
        return _quiz_api_error("qa_response_not_found", "먼저 질문을 제출해 주세요.", 404)
    response, _ = loaded_qa
    if response.status != "answered" or not response.citations:
        return JsonResponse({"status": "insufficient_content", "quiz": {"status": "insufficient_content", "questions": []}})

    if remote_enabled():
        try:
            job = create_job(request, "quiz", {
                "response": response.model_dump(mode="json"),
                "max_questions": 3,
            })
        except Exception:
            logger.exception("Unable to submit remote Quiz generation")
            return _quiz_api_error("queue_unavailable", "미니 챌린지를 준비하지 못했습니다. 잠시 후 다시 시도해 주세요.", 503)
        request.session[QUIZ_JOB_SESSION_KEY] = {
            "task_id": str(job.pk),
            "qa_request_id": response.request_id,
            "status": "pending",
        }
        return JsonResponse({"task_id": str(job.pk), "status": "pending"}, status=202)

    existing = request.session.get(QUIZ_JOB_SESSION_KEY)
    if isinstance(existing, dict) and existing.get("status") in {"pending", "running"}:
        return _quiz_api_error("generation_in_progress", "이미 미니 챌린지를 생성하고 있습니다.", 409)

    try:
        task = get_quiz_generation_task().delay(response.model_dump(mode="json"), max_questions=3)
    except Exception:
        logger.exception("Unable to queue dynamic Quiz generation")
        return _quiz_api_error("queue_unavailable", "미니 챌린지를 준비하지 못했습니다. 잠시 후 다시 시도해 주세요.", 503)

    request.session[QUIZ_JOB_SESSION_KEY] = {
        "task_id": str(task.id),
        "qa_request_id": response.request_id,
        "status": "pending",
    }
    return JsonResponse({"task_id": str(task.id), "status": "pending"}, status=202)


@require_GET
def mini_challenge_job_api(request, task_id):
    """Return only the session owner's current Quiz generation status."""

    job = request.session.get(QUIZ_JOB_SESSION_KEY)
    loaded_qa = _load_qa_response(request)
    if not isinstance(job, dict) or str(job.get("task_id")) != str(task_id) or loaded_qa is None:
        return _quiz_api_error("job_not_found", "미니 챌린지 생성 정보를 찾을 수 없습니다.", 404)
    response, _ = loaded_qa
    if job.get("qa_request_id") != response.request_id:
        return _quiz_api_error("job_not_found", "이전 질문의 미니 챌린지입니다.", 404)
    if job.get("status") == "cancelled":
        return JsonResponse({"task_id": str(task_id), "status": "cancelled"})

    if remote_enabled():
        ai_job = owned_job(request, task_id, kind="quiz")
        try:
            ai_job = refresh_job(ai_job)
        except RemoteAIError as exc:
            return _quiz_api_error(exc.code, "미니 챌린지 상태를 확인하지 못했습니다.", exc.status)
        if ai_job.status == "succeeded":
            ai_job = _finalize_remote_job(request, ai_job)
        payload = _remote_job_json(request, ai_job)
        payload["task_id"] = payload.pop("job_id")
        if payload["status"] in {"queued", "submission_unknown"}:
            payload["status"] = "pending"
        job["status"] = payload["status"]
        if payload.get("quiz_id"):
            job["quiz_id"] = payload["quiz_id"]
        request.session[QUIZ_JOB_SESSION_KEY] = job
        return JsonResponse(payload, status=202 if payload["status"] in {"pending", "running", "cancelling"} else 200)

    try:
        task = get_quiz_async_result(str(task_id))
        task_state = task.state
    except Exception:
        logger.exception("Unable to inspect dynamic Quiz task %s", task_id)
        return _quiz_api_error("queue_unavailable", "미니 챌린지 상태를 확인하지 못했습니다.", 503)

    if task_state in {"PENDING", "RECEIVED", "STARTED", "RETRY"}:
        job["status"] = "running" if task_state == "STARTED" else "pending"
        request.session[QUIZ_JOB_SESSION_KEY] = job
        return JsonResponse({"task_id": str(task_id), "status": job["status"]}, status=202)
    if task_state == "REVOKED":
        job["status"] = "cancelled"
        request.session[QUIZ_JOB_SESSION_KEY] = job
        return JsonResponse({"task_id": str(task_id), "status": "cancelled"})
    if task_state != "SUCCESS":
        job["status"] = "generation_failed"
        request.session[QUIZ_JOB_SESSION_KEY] = job
        return JsonResponse({"task_id": str(task_id), "status": "generation_failed"})

    try:
        quiz_response = QuizResponse.model_validate(task.result)
    except (TypeError, ValueError):
        logger.error("Dynamic Quiz task %s returned an invalid result", task_id)
        job["status"] = "generation_failed"
        request.session[QUIZ_JOB_SESSION_KEY] = job
        return JsonResponse({"task_id": str(task_id), "status": "generation_failed"})

    job["status"] = quiz_response.status
    if quiz_response.status == "available":
        quiz_id = _store_quiz_response(request, quiz_response)
        job["quiz_id"] = quiz_id
    request.session[QUIZ_JOB_SESSION_KEY] = job
    payload = {"task_id": str(task_id), "status": quiz_response.status, "quiz": _public_quiz_payload(quiz_response)}
    if job.get("quiz_id"):
        payload["quiz_id"] = job["quiz_id"]
    return JsonResponse(payload)


@require_POST
def cancelAPI(request, task_id):
    """Terminate the caller's active Celery Quiz worker task."""

    job = request.session.get(QUIZ_JOB_SESSION_KEY)
    if not isinstance(job, dict) or str(job.get("task_id")) != str(task_id):
        return _quiz_api_error("job_not_found", "미니 챌린지 생성 정보를 찾을 수 없습니다.", 404)
    if job.get("status") == "cancelled":
        return JsonResponse({"task_id": str(task_id), "status": "cancelled"})

    if remote_enabled():
        ai_job = cancel_job(owned_job(request, task_id, kind="quiz"))
        job["status"] = "cancelled" if ai_job.status == "cancelled" else "cancelling"
        request.session[QUIZ_JOB_SESSION_KEY] = job
        return JsonResponse({"task_id": str(task_id), "status": job["status"]}, status=202)

    # Persist cancellation first: a result that wins the race must never be exposed.
    job["status"] = "cancelled"
    request.session[QUIZ_JOB_SESSION_KEY] = job
    try:
        get_quiz_async_result(str(task_id)).revoke(terminate=True, signal="SIGTERM")
    except Exception:
        logger.exception("Unable to terminate dynamic Quiz task %s", task_id)
        return _quiz_api_error("cancel_unavailable", "생성 작업을 취소하지 못했습니다.", 503)
    return JsonResponse({"task_id": str(task_id), "status": "cancelled"}, status=202)


@require_POST
def mini_challenge_submit_api(request, quiz_id):
    """Grade one dynamic Quiz answer without trusting client-provided answer keys."""

    data, error = _json_request_data(request)
    if error is not None:
        return error
    loaded_qa = _load_qa_response(request)
    loaded_quiz = _load_quiz_response(request, str(quiz_id))
    if loaded_qa is None or loaded_quiz is None:
        return _quiz_api_error("quiz_not_found", "퀴즈가 만료되었습니다. Q&A에서 다시 시작해 주세요.", 404)

    response, _ = loaded_qa
    quiz_response, saved_quiz = loaded_quiz
    question = _question_or_none(quiz_response, data.get("question_id"))
    selected_choice_id = data.get("selected_choice_id")
    if question is None or selected_choice_id not in {choice.id for choice in question.choices}:
        return _quiz_api_error("invalid_answer", "유효한 선택지를 골라 주세요.", 400)

    submissions = saved_quiz.setdefault("submissions", {})
    if question.question_id in submissions:
        return _quiz_api_error("already_submitted", "이미 제출한 문제입니다.", 409)
    submissions[question.question_id] = selected_choice_id
    request.session[QUIZ_SESSION_KEY] = saved_quiz

    is_correct = selected_choice_id == question.correct_choice_id
    payload = {
        "question_id": question.question_id,
        "selected_choice_id": selected_choice_id,
        "correct_choice_id": question.correct_choice_id,
        "is_correct": is_correct,
        "explanation": question.explanation,
        "supporting_quotes": question.supporting_quotes,
        "evidence": _quiz_evidence_cards(response, question),
        "authenticated": request.user.is_authenticated,
    }
    feature_result = get_challenge_result(
        question=question,
        selected_choice_id=selected_choice_id,
        submission=payload,
    )
    payload.update(feature_result.to_dict())
    if not is_correct and request.user.is_authenticated:
        payload["wrong_note_url"] = reverse("wrong_note_save", args=[quiz_id])
    return JsonResponse(payload)


@require_http_methods(["GET"])
def questions(request):
    """List only records their authors have explicitly made public."""

    context = _base_context(active_page="questions")
    records = QuestionRecord.objects.filter(is_public=True).select_related("owner").order_by("-published_at", "-id")
    context["page_obj"] = Paginator(records, COMMUNITY_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "portal/questions.html", context)


@require_http_methods(["GET"])
def question_detail(request, question_id: int):
    """공개된 질문 기록 하나의 상세 화면을 렌더링한다."""

    record = get_object_or_404(QuestionRecord.objects.select_related("owner"), pk=question_id, is_public=True)
    context = _base_context(active_page="questions")
    context.update(_question_record_context(record))
    context["is_private_view"] = False
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
    feature_result = None
    submitted_template_id = None
    submitted_values = None
    submitted_product_id = None
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "analyze" and context["analysis_form"].is_valid():
                feature_result = get_command_lab_result(
                    service, command=context["analysis_form"].cleaned_data["command"]
                )
                selected_result = _lab_payload(feature_result.result)
            elif action in {"compose", "save_drawer"}:
                template_id = request.POST.get("template_id", "")
                submitted_template_id = template_id
                item = service._item(template_id)
                values = {
                    field["part_id"]: request.POST.get(f"value_{field['part_id']}", "")
                    for field in item["editable_fields"]
                }
                submitted_values = values
                product_id = request.POST.get("product_id") or None
                submitted_product_id = product_id
                feature_result = get_command_lab_result(
                    service, template_id=template_id, values=values, product_id=product_id
                )
                selected_result = _lab_payload(feature_result.result)
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
        except CommandLabFieldError as exc:
            context["lab_error"] = str(exc)
            context["lab_field_errors"] = {exc.part_id: str(exc)}
            if submitted_template_id:
                feature_result = get_command_lab_result(
                    service,
                    template_id=submitted_template_id,
                    product_id=submitted_product_id,
                )
                selected_result = _lab_payload(feature_result.result)
                context["lab_submitted_values"] = submitted_values
        except CommandLabError as exc:
            context["lab_error"] = str(exc)
        except Exception:
            logger.error("Command lab page request failed")
            context["lab_error"] = "명령어 실험실을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요."
    elif context["lab_mode"] == "examples" and context["lab_templates"]:
        preferred = _selected_template(context["lab_templates"], "cmd-remote-access-004") or context["lab_templates"][0]
        feature_result = get_command_lab_result(service, template_id=preferred["template_id"])
        selected_result = _lab_payload(feature_result.result)

    if selected_result:
        context["feature_result"] = feature_result
        context["lab_result"] = selected_result
        context["selected_template"] = _selected_template(context["lab_templates"], selected_result["template_id"])
        context["lab_editable_fields"] = _editable_fields(
            context["selected_template"],
            context.get("lab_submitted_values", selected_result["values"]),
            selected_result.get("field_validation"),
            context.get("lab_field_errors"),
        )
    context["drawer_items"] = _drawer_items(request, service)
    context["drawer_count"] = len(context["drawer_items"])
    return render(request, "portal/lab.html", context)


def _json_body(request) -> dict:
    """요청 본문을 JSON 객체로 읽고 형식 오류를 검증한다."""

    try:
        value = json.loads(request.body)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("JSON 요청 본문을 확인해 주세요.") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON 객체를 보내 주세요.")
    return value


@require_GET
def lab_templates_api(request):
    """명령어 실험실에서 사용할 템플릿 목록을 JSON으로 반환한다."""

    try:
        templates = [_lab_template_payload(item) for item in get_command_lab_service().list_templates()]
        return JsonResponse({"templates": templates})
    except Exception:
        return JsonResponse({"error": "명령어 실험실 데이터를 준비하지 못했습니다."}, status=503)


@require_POST
def lab_analyze_api(request):
    """입력 명령어를 분석하고 검증된 실험실 결과를 JSON으로 반환한다."""

    try:
        feature_result = get_command_lab_result(get_command_lab_service(), command=_json_body(request).get("command"))
        return JsonResponse(_lab_payload(feature_result.result))
    except CommandLabError as exc:
        return _command_lab_error_response(exc)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception:
        return JsonResponse({"error": "명령어 실험실을 처리하지 못했습니다."}, status=503)


@require_POST
def lab_compose_api(request):
    """템플릿 입력값으로 명령어를 조합해 JSON 결과를 반환한다."""

    try:
        body = _json_body(request)
        feature_result = get_command_lab_result(
            get_command_lab_service(),
            template_id=body.get("template_id"),
            values=body.get("values"),
            product_id=body.get("product_id"),
        )
        return JsonResponse(_lab_payload(feature_result.result))
    except CommandLabError as exc:
        return _command_lab_error_response(exc)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except Exception:
        return JsonResponse({"error": "명령어 실험실을 처리하지 못했습니다."}, status=503)


@require_http_methods(["GET"])
def health(request):
    """웹 애플리케이션과 RAG 런타임의 준비 상태를 반환한다."""

    if remote_enabled():
        try:
            ready = RunPodClient().readiness()
        except RemoteAIError:
            ready = False
        return JsonResponse(
            {
                "status": "ok" if ready else "not_ready",
                "ready": ready,
                "message": (
                    "RunPod AI 서비스가 준비되었습니다."
                    if ready
                    else "RunPod AI 서비스를 준비하지 못했습니다. 설정을 확인해 주세요."
                ),
            }
        )

    readiness = get_runtime_readiness()
    return JsonResponse(
        {
            "status": "ok" if readiness.ready else "not_ready",
            "ready": readiness.ready,
            "message": readiness.message if readiness.ready else "RAG 실행 환경을 준비하지 못했습니다. 설정을 확인해 주세요.",
        }
    )

@require_GET
def openapi_schema(request):
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "openapi"
        / "web-api.yaml"
    )

    try:
        schema_text = schema_path.read_text(encoding="utf-8")
    except OSError:
        return JsonResponse(
            {"error": "OpenAPI 명세 파일을 읽을 수 없습니다."},
            status=500,
        )

    return HttpResponse(
        schema_text,
        content_type="application/yaml; charset=utf-8",
    )
@require_GET
def swagger_docs(request):
    """OpenAPI 명세를 Swagger UI로 표시합니다."""

    return render(
        request,
        "portal/swagger_ui.html",
        {"schema_url": reverse("openapi_schema")},
    )


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
            "qa_records": QuestionRecord.objects.filter(owner=user).count(),
            "recommendation_records": RecommendationRecord.objects.filter(owner=user).count(),
        },
        "recent_posts": Post.objects.filter(author=user).select_related("author")[:MYPAGE_RECENT_LIMIT],
        "recent_comments": Comment.objects.filter(author=user).select_related("post")[:MYPAGE_RECENT_LIMIT],
        "recent_likes": PostLike.objects.filter(user=user).select_related("post", "post__author")[:MYPAGE_RECENT_LIMIT],
        "recent_drawer_items": DrawerItem.objects.filter(owner=user)[:MYPAGE_RECENT_LIMIT],
        "recent_wrong_notes": WrongNote.objects.filter(owner=user)[:MYPAGE_RECENT_LIMIT],
        "recent_qa_records": QuestionRecord.objects.filter(owner=user)[:MYPAGE_RECENT_LIMIT],
        "recent_recommendation_records": RecommendationRecord.objects.filter(owner=user)[:MYPAGE_RECENT_LIMIT],
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


@login_required
@require_GET
def mypage_recommendations(request):
    """현재 사용자가 저장한 제품 추천 기록 목록을 표시한다."""

    records = RecommendationRecord.objects.filter(owner=request.user)
    page_obj = _activity_page(request, records)
    for record in page_obj:
        record.status_label = STATUS_LABELS.get(record.status, "저장된 답변")
    return render(request, "portal/mypage_recommendations.html", {"page_obj": page_obj, "active_page": "mypage"})


@login_required
@require_GET
def mypage_recommendation_detail(request, pk: int):
    """현재 사용자가 소유한 제품 추천 기록 상세를 표시한다."""

    record = get_object_or_404(RecommendationRecord, pk=pk, owner=request.user)
    return render(request, "portal/recommendation_detail.html", _recommendation_record_context(record))


@login_required
@require_POST
def mypage_recommendation_delete(request, pk: int):
    """현재 사용자가 소유한 제품 추천 기록을 삭제한다."""

    record = get_object_or_404(RecommendationRecord, pk=pk, owner=request.user)
    record.delete()
    messages.success(request, "제품추천 기록을 삭제했습니다.")
    return redirect("mypage_recommendations")


@login_required
@require_GET
def mypage_questions(request):
    """현재 사용자가 저장한 Q&A 기록 목록을 표시한다."""

    records = QuestionRecord.objects.filter(owner=request.user)
    return render(
        request,
        "portal/mypage_questions.html",
        {"page_obj": _activity_page(request, records), "active_page": "mypage"},
    )


@login_required
@require_GET
def mypage_question_detail(request, pk: int):
    """현재 사용자가 소유한 Q&A 기록 상세를 표시한다."""

    record = get_object_or_404(QuestionRecord.objects.select_related("owner"), pk=pk, owner=request.user)
    context = _question_record_context(record)
    context.update({"active_page": "mypage", "is_private_view": True})
    return render(request, "portal/question_detail.html", context)


@login_required
@require_POST
def mypage_question_visibility(request, pk: int):
    """현재 사용자의 Q&A 기록 공개 여부를 전환한다."""

    record = get_object_or_404(QuestionRecord, pk=pk, owner=request.user)
    if record.is_public:
        record.is_public = False
        record.published_at = None
        messages.success(request, "질문 기록을 비공개로 전환했습니다.")
    else:
        record.is_public = True
        record.published_at = timezone.now()
        messages.success(request, "질문 기록을 공개 아카이브에 게시했습니다.")
    record.save(update_fields=["is_public", "published_at", "updated_at"])
    return redirect("mypage_question_detail", pk=record.pk)


@login_required
@require_POST
def mypage_question_delete(request, pk: int):
    """현재 사용자가 소유한 Q&A 기록을 삭제한다."""

    record = get_object_or_404(QuestionRecord, pk=pk, owner=request.user)
    record.delete()
    messages.success(request, "질문 기록을 삭제했습니다.")
    return redirect("mypage_questions")


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
        feature_result = get_command_lab_result(get_command_lab_service(), command=data.get("command"))
        return JsonResponse(feature_result.result)
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
        feature_result = get_command_lab_result(
            get_command_lab_service(),
            template_id=data.get("template_id"),
            values=data.get("values"),
            product_id=data.get("product_id"),
        )
        return JsonResponse(feature_result.result)
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
                feature_result = get_command_lab_result(service, command=form.cleaned_data["command"])
                context["feature_result"] = feature_result
                context["result"] = feature_result.result
            elif action == "compose":
                template_id, values, product_id = _form_compose_arguments(service, request.POST)
                feature_result = get_command_lab_result(
                    service, template_id=template_id, values=values, product_id=product_id
                )
                context["feature_result"] = feature_result
                context["result"] = feature_result.result
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


@login_required
@require_POST
def wrong_note_save(request, quiz_id):
    """Save one submitted incorrect answer, responding as HTML or JSON by request type."""

    wants_json = _wants_json_response(request)
    loaded_quiz = _load_quiz_response(request, str(quiz_id))
    if loaded_quiz is None:
        message = "퀴즈가 만료되었습니다. Q&A 결과에서 다시 시작해 주세요."
        if wants_json:
            return _quiz_api_error("quiz_not_found", message, 409)
        messages.warning(request, message)
        return redirect("qa")

    quiz_response, saved_quiz = loaded_quiz
    question = _question_or_none(quiz_response, request.POST.get("question_id"))
    selected_choice_id = saved_quiz.get("submissions", {}).get(question.question_id) if question is not None else None
    if question is None or selected_choice_id is None:
        message = "저장할 오답 풀이 결과가 없습니다."
        if wants_json:
            return _quiz_api_error("submission_not_found", message, 409)
        messages.warning(request, message)
        return redirect("qa")
    if selected_choice_id == question.correct_choice_id:
        message = "정답은 오답노트에 저장하지 않습니다."
        if wants_json:
            return _quiz_api_error("correct_answer", message, 409)
        messages.warning(request, message)
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
    message = "오답노트에 저장했습니다."
    wrong_note_url = reverse("wrong_note_detail", args=[wrong_note.pk])
    if wants_json:
        return JsonResponse(
            {"message": message, "wrong_note_id": wrong_note.pk, "wrong_note_url": wrong_note_url},
            status=201,
        )
    messages.success(request, message)
    return redirect(wrong_note_url)


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
