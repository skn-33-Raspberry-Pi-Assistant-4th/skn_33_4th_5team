"""Database ownership and state transitions for RunPod inference jobs."""

from __future__ import annotations

import hashlib
from datetime import timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from .models import AiJob
from .remote_ai import RemoteAIError, RunPodClient


TERMINAL = {"succeeded", "failed", "cancelled", "expired"}


def remote_enabled():
    """현재 설정이 RunPod 원격 AI 백엔드를 사용하는지 반환한다."""

    return settings.PICARE_AI_BACKEND == "remote"


def session_hash(request):
    """브라우저 세션 키를 외부 노출 없는 해시값으로 변환한다."""

    if not request.session.session_key:
        request.session.create()
    return hashlib.sha256(request.session.session_key.encode()).hexdigest()


def owned_jobs(request):
    """현재 사용자와 브라우저 세션이 소유한 AI 작업만 조회한다."""

    return AiJob.objects.filter(
        session_hash=session_hash(request),
        owner_id=request.user.pk if request.user.is_authenticated else None,
    )


def owned_job(request, job_id, *, kind=None, lock=False):
    """현재 세션 소유 작업 하나를 조회하고 필요하면 행 잠금을 건다."""

    queryset = owned_jobs(request)
    if lock:
        queryset = queryset.select_for_update()
    if kind:
        queryset = queryset.filter(kind=kind)
    try:
        return queryset.get(pk=job_id)
    except (AiJob.DoesNotExist, ValueError):
        raise Http404 from None


def _apply_remote(job_id, data):
    """RunPod에서 받은 작업 상태를 잠금 상태의 DB 작업에 반영한다."""

    with transaction.atomic():
        job = AiJob.objects.select_for_update().get(pk=job_id)
        if job.status in TERMINAL:
            return job
        # A cancelled/superseded result must never become eligible for saving.
        if job.cancel_requested and data["status"] == "succeeded":
            job.status = "cancelled"
            job.result_payload = None
        else:
            job.status = data["status"]
            job.result_payload = data.get("result") if job.status == "succeeded" else None
        job.error_code = "generation_failed" if job.status == "failed" else ""
        if job.status in TERMINAL:
            job.expires_at = timezone.now() + timedelta(minutes=30)
        job.save()
        return job


def _terminal(job_id, status, code=""):
    """작업을 종료 상태로 전환하고 결과 보존 만료 시각을 기록한다."""

    with transaction.atomic():
        job = AiJob.objects.select_for_update().get(pk=job_id)
        if job.status not in TERMINAL:
            job.status = status
            job.error_code = code
            job.result_payload = None
            job.expires_at = timezone.now() + timedelta(minutes=30)
            job.save()
        return job


def cancel_job(job):
    """현재 작업의 취소 의도를 저장하고 RunPod에도 취소를 요청한다."""

    with transaction.atomic():
        job = AiJob.objects.select_for_update().get(pk=job.pk)
        if job.finalized_at or job.status in TERMINAL:
            return job
        job.cancel_requested = True
        job.status = "cancelling"
        job.save(update_fields=["cancel_requested", "status", "updated_at"])
    try:
        return _apply_remote(job.pk, RunPodClient().cancel(job))
    except RemoteAIError as exc:
        if exc.code == "job_not_found":
            return _terminal(job.pk, "cancelled")
        # Preserve cancellation intent and retry it when the browser polls.
        return job


def create_job(request, kind, payload):
    """세션별 기존 작업을 정리하고 새 RunPod 작업을 생성한다."""

    key_hash = session_hash(request)
    now = timezone.now()
    with transaction.atomic():
        # Serialize submissions for the same session across Gunicorn workers.
        Session.objects.select_for_update().get(session_key=request.session.session_key)
        old_jobs = list(owned_jobs(request).select_for_update().filter(kind=kind, is_current=True))
        AiJob.objects.filter(pk__in=[job.pk for job in old_jobs]).update(is_current=False)
        job = AiJob.objects.create(
            owner_id=request.user.pk if request.user.is_authenticated else None,
            session_hash=key_hash, kind=kind, input_payload=payload,
            deadline_at=now + timedelta(seconds=settings.AI_JOB_TIMEOUT),
            expires_at=now + timedelta(seconds=settings.AI_JOB_TIMEOUT, minutes=30),
        )
    for old in old_jobs:
        cancel_job(old)
    try:
        return _apply_remote(job.pk, RunPodClient().submit(job))
    except RemoteAIError as exc:
        if exc.code == "connection_unavailable":
            # The request may already have reached RunPod; retry only this ID.
            AiJob.objects.filter(pk=job.pk, status="queued").update(status="submission_unknown")
            job.refresh_from_db()
            return job
        return _terminal(job.pk, "failed", exc.code)


def refresh_job(job):
    """원격 작업 상태를 갱신하고 만료·취소·완료 상태를 반영한다."""

    if job.expires_at <= timezone.now():
        # Results have a fixed retention lifetime, including finalized results.
        AiJob.objects.filter(pk=job.pk).update(status="expired", result_payload=None)
        job.refresh_from_db()
        return job
    if job.status in TERMINAL:
        return job
    if job.deadline_at <= timezone.now():
        cancel_job(job)
        return _terminal(job.pk, "expired", "timed_out")
    if job.cancel_requested:
        return cancel_job(job)
    client = RunPodClient()
    try:
        data = client.submit(job) if job.status == "submission_unknown" else client.status(job)
    except RemoteAIError as exc:
        if exc.code == "job_not_found":
            return _terminal(job.pk, "expired")
        raise
    return _apply_remote(job.pk, data)
