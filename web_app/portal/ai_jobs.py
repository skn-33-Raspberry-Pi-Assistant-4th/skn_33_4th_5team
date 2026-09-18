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
    return settings.PICARE_AI_BACKEND == "remote"


def session_hash(request):
    if not request.session.session_key:
        request.session.create()
    return hashlib.sha256(request.session.session_key.encode()).hexdigest()


def owned_jobs(request):
    return AiJob.objects.filter(
        session_hash=session_hash(request),
        owner_id=request.user.pk if request.user.is_authenticated else None,
    )


def owned_job(request, job_id, *, kind=None, lock=False):
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
