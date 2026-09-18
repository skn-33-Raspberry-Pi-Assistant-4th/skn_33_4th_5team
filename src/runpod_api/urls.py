"""URL routes for the standalone RunPod Django inference API."""

from django.urls import path

from . import app


urlpatterns = [
    path("health/live", app.live, name="runpod_health_live"),
    path("health/ready", app.ready, name="runpod_health_ready"),
    path("v1/jobs", app.submit, name="runpod_job_submit"),
    path("v1/jobs/<str:job_id>", app.get_job, name="runpod_job_status"),
    path("v1/jobs/<str:job_id>/cancel", app.cancel_job, name="runpod_job_cancel"),
]


__all__ = ["urlpatterns"]
