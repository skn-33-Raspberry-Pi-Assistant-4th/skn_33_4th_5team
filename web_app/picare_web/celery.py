"""Celery application for cancellable Dynamic Mini Challenge generation."""

from __future__ import annotations

import os

from celery import Celery


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "picare_web.settings")

app = Celery("picare_web")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

