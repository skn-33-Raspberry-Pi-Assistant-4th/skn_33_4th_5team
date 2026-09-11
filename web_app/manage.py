#!/usr/bin/env python3
"""PiCare Django 실행 요약.

처음 한 번: ``python3 -m pip install -r requirements.txt``
로컬 실행: ``python3 web_app/manage.py runserver``
접속 주소: http://127.0.0.1:8000/
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


WEB_APP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_APP_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "picare_web.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
