#!/usr/bin/env python3
"""Bootstrap PiCare's local Django, MySQL, and Python development setup.

Run once from any directory with ``python scripts/init.py``. The script is
idempotent: it never overwrites an existing ``.env`` or deletes Docker data.
For a fresh clone it generates local-only development secrets, creates the
project virtual environment, installs dependencies, starts MySQL through
Docker Compose, and applies Django migrations.

This script is for local development only. RunPod uses ``scripts/runpod``.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import secrets
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOTENV_PATH = PROJECT_ROOT / ".env"
DOTENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"
VENV_PATH = PROJECT_ROOT / ".venv"
REQUIRED_SECRET_KEYS = ("MYSQL_PASSWORD", "MYSQL_ROOT_PASSWORD", "DJANGO_SECRET_KEY")


def _run(command: list[str]) -> None:
    """Run one setup command from the repository root and stop on failure."""

    print("+", " ".join(command))
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def _set_env_value(content: str, key: str, value: str) -> str:
    """Replace a commented or active dotenv key, or append it when absent."""

    pattern = re.compile(rf"^\s*#?\s*{re.escape(key)}=.*$", flags=re.MULTILINE)
    line = f"{key}={value}"
    if pattern.search(content):
        return pattern.sub(line, content, count=1)
    return f"{content.rstrip()}\n{line}\n"


def _read_dotenv(path: Path) -> dict[str, str]:
    """Read simple dotenv assignments without importing the application runtime."""

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _is_placeholder(value: str | None) -> bool:
    """Reject blank and instructional values that cannot safely start MySQL."""

    if not value:
        return True
    lower = value.lower()
    markers = ("<", ">", "비밀번호", "랜덤", "your_", "change-me", "example")
    return any(marker in lower for marker in markers)


def _create_local_dotenv() -> None:
    """Create a non-production dotenv file with fresh local-only credentials."""

    if not DOTENV_EXAMPLE_PATH.is_file():
        raise RuntimeError(f"환경 변수 예시 파일이 없습니다: {DOTENV_EXAMPLE_PATH}")
    content = DOTENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    content = _set_env_value(content, "DJANGO_DEBUG", "true")
    content = _set_env_value(content, "MYSQL_PASSWORD", secrets.token_hex(24))
    content = _set_env_value(content, "MYSQL_ROOT_PASSWORD", secrets.token_hex(24))
    content = _set_env_value(content, "DJANGO_SECRET_KEY", secrets.token_urlsafe(48))
    DOTENV_PATH.write_text(content, encoding="utf-8")
    os.chmod(DOTENV_PATH, 0o600)
    print(f"로컬 개발용 .env를 생성했습니다: {DOTENV_PATH}")
    print("생성된 비밀번호는 .env에서 확인할 수 있으며, .env는 Git에 포함되지 않습니다.")


def _ensure_dotenv() -> None:
    """Keep existing local configuration intact and validate required secrets."""

    if not DOTENV_PATH.exists():
        _create_local_dotenv()
    values = _read_dotenv(DOTENV_PATH)
    invalid = [key for key in REQUIRED_SECRET_KEYS if _is_placeholder(values.get(key))]
    if invalid:
        names = ", ".join(invalid)
        raise RuntimeError(f".env에서 다음 값을 설정해 주세요: {names}")
    if values.get("DJANGO_DEBUG", "").lower() != "true":
        print("경고: 로컬 runserver에서 CSS를 보려면 .env의 DJANGO_DEBUG=true를 권장합니다.")


def _venv_python() -> Path:
    """Return the project virtual-environment interpreter for the host OS."""

    return VENV_PATH / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _ensure_virtualenv_and_dependencies() -> Path:
    """Create ``.venv`` when needed and install the pinned project requirements."""

    python = _venv_python()
    if not python.is_file():
        _run([sys.executable, "-m", "venv", str(VENV_PATH)])
    _run([str(python), "-m", "pip", "install", "--upgrade", "pip"])
    _run([str(python), "-m", "pip", "install", "-r", "requirements.txt"])
    return python


def _ensure_docker_mysql() -> None:
    """Verify Docker Desktop is available, then start and wait for PiCare MySQL."""

    try:
        _run(["docker", "info"])
        _run(["docker", "compose", "version"])
    except FileNotFoundError as exc:
        raise RuntimeError("Docker Desktop을 설치하고 실행한 뒤 다시 시도해 주세요.") from exc
    _run(["docker", "compose", "up", "-d", "--wait", "mysql"])


def _migrate(python: Path) -> None:
    """Create or update Django's User, permission, and session tables in MySQL."""

    _run([str(python), "web_app/manage.py", "migrate"])


def main() -> int:
    """Run the safe, repeatable local bootstrap sequence."""

    try:
        _ensure_dotenv()
        python = _ensure_virtualenv_and_dependencies()
        _ensure_docker_mysql()
        _migrate(python)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"\n초기 설정을 완료하지 못했습니다: {exc}", file=sys.stderr)
        return 1

    print("\nPiCare 로컬 초기 설정이 완료되었습니다.")
    print(f"다음 실행: {python} web_app/manage.py runserver 8001")
    print("접속 주소: http://127.0.0.1:8001/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
