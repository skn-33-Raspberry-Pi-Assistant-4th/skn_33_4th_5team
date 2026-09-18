"""FastAPI application exposed through the RunPod HTTPS proxy."""

from __future__ import annotations

import hmac
import os
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .contracts import JobCreate, JobResponse
from .jobs import JobConflictError, JobManager, JobNotFoundError, QueueFullError
from .runtime import PiCareRuntime


@dataclass(frozen=True)
class ApiSettings:
    token: str
    max_queued: int = 8
    timeout_seconds: float = 300
    retention_seconds: float = 1_800
    project_root: Path = Path(__file__).resolve().parents[2]

    @classmethod
    def from_env(cls) -> "ApiSettings":
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
    def __init__(self, settings: ApiSettings, runtime: PiCareRuntime | None = None) -> None:
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
        def initialize() -> None:
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
        self.manager.stop()


def create_app(*, settings: ApiSettings | None = None, runtime: PiCareRuntime | None = None) -> FastAPI:
    configured = settings or ApiSettings.from_env()
    state_holder = ServerState(configured, runtime)
    bearer = HTTPBearer(auto_error=False)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        state_holder.start()
        try:
            yield
        finally:
            state_holder.stop()

    api = FastAPI(title="PiCare RunPod AI API", version="1.0.0", lifespan=lifespan)
    api.state.server = state_holder

    def authenticate(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> None:
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or not hmac.compare_digest(credentials.credentials, configured.token)
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")

    def require_manager(_: None = Depends(authenticate)) -> JobManager:
        ready, _ = state_holder.runtime.readiness
        if not ready or not state_holder.manager.running:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="runtime_not_ready")
        return state_holder.manager

    @api.get("/health/live")
    def live() -> dict[str, bool]:
        return {"live": True}

    @api.get("/health/ready")
    def ready() -> dict[str, object]:
        is_ready, message = state_holder.runtime.readiness
        return {"ready": is_ready and state_holder.manager.running, "message": message}

    @api.post(
        "/v1/jobs",
        response_model=JobResponse,
        response_model_exclude_none=True,
        dependencies=[Depends(authenticate)],
    )
    def submit(request: JobCreate, manager: JobManager = Depends(require_manager)) -> JobResponse:
        try:
            return manager.submit(request)
        except QueueFullError as exc:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="queue_full") from exc
        except JobConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="job_conflict") from exc

    @api.get(
        "/v1/jobs/{job_id}",
        response_model=JobResponse,
        response_model_exclude_none=True,
        dependencies=[Depends(authenticate)],
    )
    def get_job(job_id: str, manager: JobManager = Depends(require_manager)) -> JobResponse:
        try:
            return manager.get(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found") from exc

    @api.post(
        "/v1/jobs/{job_id}/cancel",
        response_model=JobResponse,
        response_model_exclude_none=True,
        dependencies=[Depends(authenticate)],
    )
    def cancel_job(job_id: str, manager: JobManager = Depends(require_manager)) -> JobResponse:
        try:
            return manager.cancel(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found") from exc

    return api


__all__ = ["ApiSettings", "ServerState", "create_app"]
