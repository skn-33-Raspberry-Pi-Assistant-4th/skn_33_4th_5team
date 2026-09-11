"""ASGI config for PiCare."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "picare_web.settings")

from django.core.asgi import get_asgi_application

application = get_asgi_application()
