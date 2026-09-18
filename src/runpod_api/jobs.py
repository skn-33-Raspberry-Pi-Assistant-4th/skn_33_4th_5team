"""Single-GPU in-memory job queue with idempotency and cooperative cancellation."""

from __future__ import annotations

import hashlib
import json
import queue
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from src.rag_to_llm.cancellation import GenerationCancelled

from .contracts import JobCreate, JobKind, JobResponse, JobStatus


class JobRunner(Protocol):
    """AI 작업 실행기가 따라야 할 호출 규약을 정의한다."""

    def __call__(
        self,
        kind: JobKind,
        payload: Mapping[str, object],
        *,
        job_id: str,
        cancel_requested: Callable[[], bool],
    ) -> dict[str, object]:
        """하나의 AI 작업을 실행하고 JSON 객체 형태의 결과를 반환한다."""

        ...


class QueueFullError(RuntimeError):
    """The bounded waiting queue cannot accept another job."""


class JobConflictError(RuntimeError):
    """A job ID was reused with a different kind or payload."""


class JobNotFoundError(LookupError):
    """No job or retained tombstone exists for the requested ID."""


@dataclass
class _Job:
    """메모리 큐에 보관하는 단일 작업의 상태를 나타낸다."""

    request: JobCreate
    fingerprint: str
    created_at: float
    deadline_at: float
    status: JobStatus = "queued"
    result: dict[str, object] | None = None
    error: str | None = None
    finished_at: float | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def response(self) -> JobResponse:
        """내부 작업 상태를 외부 API용 ``JobResponse``로 변환한다."""

        return JobResponse(
            job_id=self.request.job_id,
            kind=self.request.kind,
            status=self.status,
            result=self.result if self.status == "succeeded" else None,
            error=self.error if self.status == "failed" else None,
        )


class JobManager:
    """Own one serial worker so model instances are never used concurrently."""

    def __init__(
        self,
        runner: JobRunner,
        *,
        max_queued: int = 8,
        timeout_seconds: float = 300,
        retention_seconds: float = 1_800,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """GPU 작업을 순차 실행하는 메모리 큐를 생성한다."""

        if max_queued < 1 or timeout_seconds <= 0 or retention_seconds <= 0:
            raise ValueError("job limits must be positive")
        self._runner = runner
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=max_queued)
        self._timeout_seconds = timeout_seconds
        self._retention_seconds = retention_seconds
        self._clock = clock
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()

    @staticmethod
    def _fingerprint(request: JobCreate) -> str:
        """동일한 ``job_id`` 재사용 여부를 판별할 요청 해시를 생성한다."""

        wire = request.model_dump(mode="json")
        encoded = json.dumps(wire, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @property
    def running(self) -> bool:
        """GPU worker 스레드가 현재 실행 중인지 반환한다."""

        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """GPU 작업을 하나씩 처리하는 worker 스레드를 시작한다."""

        with self._lock:
            if self.running:
                return
            self._stopping.clear()
            self._thread = threading.Thread(
                target=self._worker_loop,
                name="picare-gpu-worker",
                daemon=True,
            )
            self._thread.start()

    def stop(self, *, timeout: float = 10) -> None:
        """진행 중인 작업에 취소를 요청하고 worker 스레드를 종료한다."""

        with self._lock:
            if not self.running:
                return
            self._stopping.set()
            for job in self._jobs.values():
                if job.status in {"queued", "running", "cancelling"}:
                    job.cancel_event.set()
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass
            thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)

    def submit(self, request: JobCreate) -> JobResponse:
        """새 작업을 큐에 등록하고 현재 상태를 반환한다."""

        fingerprint = self._fingerprint(request)
        now = self._clock()
        with self._lock:
            self._expire_locked(now)
            existing = self._jobs.get(request.job_id)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise JobConflictError("job_id already belongs to a different request")
                return existing.response()
            job = _Job(
                request=request,
                fingerprint=fingerprint,
                created_at=now,
                deadline_at=now + self._timeout_seconds,
            )
            # Publish the job before making its ID visible to the worker.
            # Otherwise a fast worker can consume and drop an unknown ID.
            self._jobs[request.job_id] = job
            try:
                self._queue.put_nowait(request.job_id)
            except queue.Full as exc:
                del self._jobs[request.job_id]
                raise QueueFullError("GPU queue is full") from exc
            return job.response()

    def get(self, job_id: str) -> JobResponse:
        """``job_id``에 해당하는 최신 작업 상태를 조회한다."""

        with self._lock:
            self._expire_locked(self._clock())
            try:
                return self._jobs[job_id].response()
            except KeyError as exc:
                raise JobNotFoundError(job_id) from exc

    def cancel(self, job_id: str) -> JobResponse:
        """대기 중이거나 실행 중인 작업에 취소를 요청한다."""

        with self._lock:
            self._expire_locked(self._clock())
            try:
                job = self._jobs[job_id]
            except KeyError as exc:
                raise JobNotFoundError(job_id) from exc
            if job.status == "queued":
                job.cancel_event.set()
                self._finish_locked(job, "cancelled")
            elif job.status in {"running", "cancelling"}:
                job.cancel_event.set()
                job.status = "cancelling"
            return job.response()

    def _expire_locked(self, now: float) -> None:
        """시간 제한 또는 보관 기간이 지난 작업을 만료 상태로 변경한다."""

        for job in self._jobs.values():
            if job.status == "queued" and now >= job.deadline_at:
                job.cancel_event.set()
                self._finish_locked(job, "expired")
            elif (
                job.status in {"succeeded", "failed", "cancelled"}
                and job.finished_at is not None
                and now - job.finished_at >= self._retention_seconds
            ):
                job.status = "expired"
                job.result = None
                job.error = None

    def _finish_locked(
        self,
        job: _Job,
        status: JobStatus,
        *,
        result: dict[str, object] | None = None,
        error: str | None = None,
    ) -> None:
        """작업의 최종 상태와 결과 또는 오류 정보를 기록한다."""

        job.status = status
        job.result = result if status == "succeeded" else None
        job.error = error if status == "failed" else None
        job.finished_at = self._clock()

    def _worker_loop(self) -> None:
        """큐에서 작업 ID를 꺼내 단일 GPU worker에서 순차 처리한다."""

        while not self._stopping.is_set():
            try:
                job_id = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if job_id is None:
                self._queue.task_done()
                return
            try:
                self._run_one(job_id)
            finally:
                self._queue.task_done()

    def _run_one(self, job_id: str) -> None:
        """하나의 작업을 실행하고 성공·실패·취소·만료 상태를 확정한다."""

        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != "queued":
                return
            if self._clock() >= job.deadline_at:
                self._finish_locked(job, "expired")
                return
            job.status = "running"

        timed_out = False

        def cancel_requested() -> bool:
            """사용자 취소, 시간 초과, 서버 종료 요청 여부를 확인한다."""

            nonlocal timed_out
            timed_out = self._clock() >= job.deadline_at
            return job.cancel_event.is_set() or timed_out or self._stopping.is_set()

        try:
            result = self._runner(
                job.request.kind,
                job.request.payload,
                job_id=job.request.job_id,
                cancel_requested=cancel_requested,
            )
            if not isinstance(result, dict):
                raise TypeError("job runner must return a JSON object")
        except GenerationCancelled:
            with self._lock:
                self._finish_locked(job, "expired" if timed_out else "cancelled")
        except Exception as exc:
            with self._lock:
                if cancel_requested():
                    self._finish_locked(job, "expired" if timed_out else "cancelled")
                else:
                    self._finish_locked(job, "failed", error="generation_failed")
        else:
            with self._lock:
                if cancel_requested():
                    self._finish_locked(job, "expired" if timed_out else "cancelled")
                else:
                    self._finish_locked(job, "succeeded", result=result)


__all__ = [
    "JobConflictError",
    "JobManager",
    "JobNotFoundError",
    "JobRunner",
    "QueueFullError",
]
