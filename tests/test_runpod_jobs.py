from __future__ import annotations

import threading
import time

import pytest

from src.rag_to_llm.cancellation import GenerationCancelled
from src.runpod_api.contracts import JobCreate
from src.runpod_api.jobs import JobConflictError, JobManager, QueueFullError


def request(job_id: str, *, question: str | None = None) -> JobCreate:
    return JobCreate(
        job_id=job_id,
        kind="qa",
        payload={"question": question or job_id},
    )


def wait_for(manager: JobManager, job_id: str, *states: str):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        response = manager.get(job_id)
        if response.status in states:
            return response
        time.sleep(0.005)
    raise AssertionError(f"{job_id} did not reach {states}")


def test_submit_is_idempotent_and_rejects_conflicting_payload() -> None:
    manager = JobManager(lambda *args, **kwargs: {})

    first = manager.submit(request("same-id"))
    duplicate = manager.submit(request("same-id"))

    assert first == duplicate
    with pytest.raises(JobConflictError):
        manager.submit(request("same-id", question="different"))


def test_queue_is_bounded_before_worker_starts() -> None:
    manager = JobManager(lambda *args, **kwargs: {}, max_queued=2)
    manager.submit(request("one"))
    manager.submit(request("two"))

    with pytest.raises(QueueFullError):
        manager.submit(request("three"))


def test_worker_runs_one_gpu_job_at_a_time() -> None:
    lock = threading.Lock()
    active = 0
    maximum = 0

    def runner(kind, payload, *, job_id, cancel_requested):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return {"job": job_id}

    manager = JobManager(runner)
    manager.start()
    try:
        manager.submit(request("first"))
        manager.submit(request("second"))
        assert wait_for(manager, "first", "succeeded").result == {"job": "first"}
        assert wait_for(manager, "second", "succeeded").result == {"job": "second"}
        assert maximum == 1
    finally:
        manager.stop()


def test_running_cancel_reaches_generation_and_next_job_recovers() -> None:
    entered = threading.Event()

    def runner(kind, payload, *, job_id, cancel_requested):
        if job_id == "cancel-me":
            entered.set()
            while not cancel_requested():
                time.sleep(0.002)
            raise GenerationCancelled()
        return {"job": job_id}

    manager = JobManager(runner)
    manager.start()
    try:
        manager.submit(request("cancel-me"))
        assert entered.wait(1)
        assert manager.cancel("cancel-me").status == "cancelling"
        assert wait_for(manager, "cancel-me", "cancelled").result is None

        manager.submit(request("after-cancel"))
        assert wait_for(manager, "after-cancel", "succeeded").result == {"job": "after-cancel"}
    finally:
        manager.stop()


def test_queued_cancel_never_calls_runner() -> None:
    calls: list[str] = []

    def runner(kind, payload, *, job_id, cancel_requested):
        calls.append(job_id)
        return {}

    manager = JobManager(runner)
    manager.submit(request("queued"))

    assert manager.cancel("queued").status == "cancelled"
    manager.start()
    try:
        time.sleep(0.02)
        assert calls == []
    finally:
        manager.stop()


def test_terminal_result_expires_and_is_cleared() -> None:
    now = [0.0]
    manager = JobManager(
        lambda kind, payload, *, job_id, cancel_requested: {"answer": "ok"},
        retention_seconds=10,
        clock=lambda: now[0],
    )
    manager.start()
    try:
        manager.submit(request("retained"))
        assert wait_for(manager, "retained", "succeeded").result == {"answer": "ok"}
        now[0] = 11
        expired = manager.get("retained")
        assert expired.status == "expired"
        assert expired.result is None
    finally:
        manager.stop()
