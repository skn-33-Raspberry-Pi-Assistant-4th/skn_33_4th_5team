"""PiCare Django project configuration."""

# Import the configured app when Django starts so ``shared_task`` uses the
# Redis settings in ``picare_web.celery`` instead of Celery's default app.
from .celery import app as celery_app

__all__ = ("celery_app",)

# PyMySQL is a pure-Python MySQL driver and exposes Django's expected MySQLdb API.
try:
    import pymysql

    pymysql.install_as_MySQLdb()
except ImportError:
    # SQLite-only tests can run before optional MySQL dependencies are installed.
    pass
