"""Django HTTP views exposed through the RunPod HTTPS proxy."""

from __future__ import annotations

import hmac
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from pydantic import ValidationError

from .contracts import JobCreate, JobResponse
from .jobs import JobConflictError, JobManager, JobNotFoundError, QueueFullError
from .runtime import PiCareRuntime


@dataclass(frozen=True)
class ApiSettings:
    """RunPod API 인증·큐·타임아웃 설정을 보관한다."""

    token: str
    max_queued: int = 8
    timeout_seconds: float = 300
    retention_seconds: float = 1_800
    project_root: Path = Path(__file__).resolve().parents[2]

    @classmethod
    def from_env(cls) -> "ApiSettings":
        """환경변수에서 RunPod API 설정을 읽고 검증한다."""

        token = os.getenv("AI_API_TOKEN", "").strip()
        if len(token) < 32:
            raise RuntimeError("AI_API_TOKEN must contain at least 32 characters")
        return cls(
            token=token,
            max_queued=int(os.getenv("AI_MAX_QUEUED", "8")),
            timeout_seconds=float(os.getenv("AI_JOB_TIMEOUT", "300")),
            retention_seconds=float(os.getenv("AI_RESULT_RETENTION", "1800")),
            project_root=Path(os.getenv("PICARE_PROJECT_ROOT", Path(__file__).resolve().parents[2])),
        )


class ServerState:
    """RunPod 런타임과 작업 큐의 생명주기를 관리한다."""

    def __init__(self, settings: ApiSettings, runtime: PiCareRuntime | None = None) -> None:
        """API 설정과 추론 런타임으로 서버 상태를 구성한다."""

        self.settings = settings
        self.runtime = runtime or PiCareRuntime(settings.project_root)
        self.manager = JobManager(
            self.runtime.execute,
            max_queued=settings.max_queued,
            timeout_seconds=settings.timeout_seconds,
            retention_seconds=settings.retention_seconds,
        )
        self.initializer: threading.Thread | None = None

    def start(self) -> None:
        """백그라운드에서 런타임을 준비하고 작업 큐를 시작한다."""

        if self.initializer is not None and self.initializer.is_alive():
            return

        def initialize() -> None:
            """런타임 초기화가 끝나면 GPU 작업 큐를 시작한다."""

            try:
                self.runtime.initialize()
            except Exception:
                return
            self.manager.start()

        self.initializer = threading.Thread(
            target=initialize,
            name="picare-runtime-loader",
            daemon=True,
        )
        self.initializer.start()

    def stop(self) -> None:
        """실행 중인 작업 큐를 안전하게 종료한다."""

        self.manager.stop()


_state_lock = threading.Lock()
_state_holder: ServerState | None = None


def get_server_state() -> ServerState:
    """Create the RunPod runtime once per Django worker and start it lazily."""

    global _state_holder
    if _state_holder is None:
        with _state_lock:
            if _state_holder is None:
                _state_holder = ServerState(ApiSettings.from_env())
                _state_holder.start()
    return _state_holder


def _json_response(response: JobResponse, *, status: int = 200) -> JsonResponse:
    """작업 응답 모델을 Django JSON 응답으로 변환한다."""

    return JsonResponse(response.model_dump(mode="json", exclude_none=True), status=status)


def _error(detail: str, status: int) -> JsonResponse:
    """오류 코드와 HTTP 상태값으로 JSON 응답을 만든다."""

    return JsonResponse({"detail": detail}, status=status)


def _is_authenticated(request: HttpRequest, state: ServerState) -> bool:
    """Bearer 토큰이 서버 설정의 인증 토큰과 일치하는지 확인한다."""

    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    return (
        bool(separator)
        and scheme.lower() == "bearer"
        and hmac.compare_digest(token.strip(), state.settings.token)
    )


def _manager_for(request: HttpRequest) -> tuple[JobManager | None, JsonResponse | None]:
    """인증과 준비 상태를 확인하고 사용할 작업 관리자를 반환한다."""

    state = get_server_state()
    if not _is_authenticated(request, state):
        return None, _error("unauthorized", 401)
    ready, _ = state.runtime.readiness
    if not ready or not state.manager.running:
        return None, _error("runtime_not_ready", 503)
    return state.manager, None


@require_GET
def live(_: HttpRequest) -> JsonResponse:
    """RunPod HTTP 프로세스의 생존 상태를 반환한다."""

    return JsonResponse({"live": True})


@require_GET
def ready(_: HttpRequest) -> JsonResponse:
    """추론 런타임과 작업 큐의 준비 상태를 반환한다."""

    state = get_server_state()
    is_ready, message = state.runtime.readiness
    return JsonResponse({"ready": is_ready and state.manager.running, "message": message})


@csrf_exempt
@require_POST
def submit(request: HttpRequest) -> JsonResponse:
    """검증된 AI 작업 요청을 RunPod 작업 큐에 등록한다."""

    manager, error = _manager_for(request)
    if error is not None:
        return error
    assert manager is not None

    try:
        raw_payload = json.loads(request.body or b"{}")
        job = JobCreate.model_validate(raw_payload)
    except (json.JSONDecodeError, ValidationError, TypeError):
        return _error("invalid_request", 422)

    try:
        return _json_response(manager.submit(job))
    except QueueFullError:
        return _error("queue_full", 429)
    except JobConflictError:
        return _error("job_conflict", 409)


@require_GET
def get_job(request: HttpRequest, job_id: str) -> JsonResponse:
    """지정한 RunPod 작업의 현재 상태와 결과를 조회한다."""

    manager, error = _manager_for(request)
    if error is not None:
        return error
    assert manager is not None

    try:
        return _json_response(manager.get(job_id))
    except JobNotFoundError:
        return _error("job_not_found", 404)


@csrf_exempt
@require_POST
def cancel_job(request: HttpRequest, job_id: str) -> JsonResponse:
    """지정한 RunPod 작업에 취소 요청을 전달한다."""

    manager, error = _manager_for(request)
    if error is not None:
        return error
    assert manager is not None

    try:
        return _json_response(manager.cancel(job_id))
    except JobNotFoundError:
        return _error("job_not_found", 404)


__all__ = [
    "ApiSettings",
    "ServerState",
    "cancel_job",
    "get_job",
    "get_server_state",
    "live",
    "ready",
    "submit",
]
