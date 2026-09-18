#!/bin/sh
set -eu

python web_app/manage.py migrate --noinput
exec gunicorn picare_web.wsgi:application \
  --chdir web_app \
  --bind "${GUNICORN_BIND:-0.0.0.0:8000}" \
  --workers "${GUNICORN_WORKERS:-2}" \
  --timeout "${GUNICORN_TIMEOUT:-30}" \
  --access-logfile - \
  --error-logfile -
