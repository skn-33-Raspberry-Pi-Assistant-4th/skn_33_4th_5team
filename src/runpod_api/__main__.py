"""Run the Django-based RunPod API with ``python -m src.runpod_api``."""

from __future__ import annotations

import os
import sys

import django
from django.conf import settings
from django.core.wsgi import get_wsgi_application


def _configure_django() -> None:
    """Configure only the Django pieces required by the GPU API server."""

    if settings.configured:
        return

    settings.configure(
        DEBUG=False,
        SECRET_KEY="picare-runpod-api",
        ALLOWED_HOSTS=["*"],
        ROOT_URLCONF="src.runpod_api.urls",
        MIDDLEWARE=[],
        INSTALLED_APPS=[],
    )
    django.setup()


_configure_django()
application = get_wsgi_application()


def main() -> None:
    """Serve the RunPod Django API with one Gunicorn worker."""

    from gunicorn.app.wsgiapp import run

    port = int(os.getenv("AI_API_PORT", "8000"))
    sys.argv = [
        "gunicorn",
        "src.runpod_api.__main__:application",
        "--bind",
        f"0.0.0.0:{port}",
        "--workers",
        "1",
        "--access-logfile",
        "-",
        "--error-logfile",
        "-",
    ]
    run()


if __name__ == "__main__":
    main()
