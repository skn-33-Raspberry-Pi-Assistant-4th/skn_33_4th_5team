"""Settings for the standalone PiCare Django presentation layer."""

from __future__ import annotations

import os
import sys
import importlib.util
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(path: Path) -> bool:
        """Keep management commands usable before optional dependencies install."""

        if not path.is_file():
            return False
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", maxsplit=1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))
        return True

WEB_APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = WEB_APP_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-local-picare-only")
# 개발 환경에서만 DJANGO_DEBUG=true를 명시해 상세 오류 화면을 사용한다.
DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",") if host.strip()]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]


def _env_flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "portal",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
if importlib.util.find_spec("whitenoise") is not None:
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "picare_web.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [WEB_APP_ROOT / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

WSGI_APPLICATION = "picare_web.wsgi.application"
ASGI_APPLICATION = "picare_web.asgi.application"

# Docker Compose MySQL is the default Django database. ``DJANGO_DB_*`` values
# override the shared Compose ``MYSQL_*`` values for a separately hosted DB.
# SQLite remains available only when a test explicitly sets DJANGO_DB_ENGINE.
def _database_config() -> dict[str, str]:
    """Build one database configuration from the current environment."""

    engine = os.getenv("DJANGO_DB_ENGINE", "django.db.backends.mysql")
    is_mysql = engine == "django.db.backends.mysql"
    return {
        "ENGINE": engine,
        "NAME": os.getenv("DJANGO_DB_NAME") or (
            os.getenv("MYSQL_DATABASE", "picare")
            if is_mysql
            else os.getenv("DJANGO_SQLITE_PATH", str(WEB_APP_ROOT / "db.sqlite3"))
        ),
        "USER": os.getenv("DJANGO_DB_USER") or (os.getenv("MYSQL_USER", "") if is_mysql else ""),
        "PASSWORD": os.getenv("DJANGO_DB_PASSWORD") or (os.getenv("MYSQL_PASSWORD", "") if is_mysql else ""),
        "HOST": os.getenv("DJANGO_DB_HOST") or (os.getenv("MYSQL_HOST", "127.0.0.1") if is_mysql else ""),
        "PORT": os.getenv("DJANGO_DB_PORT") or (os.getenv("MYSQL_PORT", "3306") if is_mysql else ""),
    }


DATABASES = {"default": _database_config()}

SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = _env_flag("DJANGO_SESSION_COOKIE_SECURE")
CSRF_COOKIE_SECURE = _env_flag("DJANGO_CSRF_COOKIE_SECURE")
SECURE_SSL_REDIRECT = _env_flag("DJANGO_SECURE_SSL_REDIRECT")
if _env_flag("DJANGO_USE_PROXY_SSL", False):
    # AWS reverse proxies terminate TLS and pass this header to Django.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_flag("DJANGO_HSTS_INCLUDE_SUBDOMAINS")
SECURE_HSTS_PRELOAD = _env_flag("DJANGO_HSTS_PRELOAD")
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "about"
LOGOUT_REDIRECT_URL = "about"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [WEB_APP_ROOT / "static"]
STATIC_ROOT = WEB_APP_ROOT / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if importlib.util.find_spec("whitenoise") is not None
            else "django.contrib.staticfiles.storage.StaticFilesStorage"
        )
    },
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# AWS runs only the Django presentation layer.  RunPod owns every GPU model
# and is reached through the authenticated asynchronous job API.
PICARE_AI_BACKEND = os.getenv("PICARE_AI_BACKEND", "local").strip().lower()
AI_API_URL = os.getenv("AI_API_URL", "http://127.0.0.1:8000").strip()
AI_API_TOKEN = os.getenv("AI_API_TOKEN", "").strip()
AI_HTTP_TIMEOUT = max(1.0, float(os.getenv("AI_HTTP_TIMEOUT", "10")))
AI_JOB_TIMEOUT = max(30, int(os.getenv("AI_JOB_TIMEOUT", "300")))

# Dynamic Mini Challenge generation is isolated in a GPU Celery worker so an
# in-flight Qwen call can be terminated without stopping Django itself.
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_ACKS_LATE = False
CELERY_RESULT_EXPIRES = 60 * 30
