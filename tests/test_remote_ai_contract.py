"""Contract tests shared by the AWS client and the dependency-free fake API."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
WEB_APP = ROOT / "web_app"
for path in (ROOT, WEB_APP):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "picare_web.settings")

import django

django.setup()

from django.test import SimpleTestCase, override_settings

from portal.remote_ai import RemoteAIError, RunPodClient
from scripts.mock_ai_api import MockAIServer, MockJobStore
from src.contracts.models import ChatResponse, QuizResponse


TOKEN = "contract-test-token-at-least-32-bytes"


class RunningMock:
    def __init__(self, *, mode: str = "success", delay_seconds: float = 0.0):
        self.server = MockAIServer(
            ("127.0.0.1", 0),
            token=TOKEN,
            store=MockJobStore(mode=mode, delay_seconds=delay_seconds),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "RunningMock":
        self.thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"


def job(job_id: str, kind: str, payload: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(pk=job_id, kind=kind, input_payload=payload or {"value": "test"})


class RemoteAIContractTests(SimpleTestCase):
    def test_mock_rejects_unknown_kind_and_extra_wire_fields(self):
        store = MockJobStore()

        status, _ = store.submit({"job_id": "bad-kind", "kind": "other", "payload": {}})
        self.assertEqual(status, 422)
        status, _ = store.submit(
            {"job_id": "extra", "kind": "qa", "payload": {}, "token": "must-not-cross-wire"}
        )
        self.assertEqual(status, 422)

    def test_runpod_restart_forgets_volatile_jobs(self):
        before_restart = MockJobStore(delay_seconds=60)
        status, submitted = before_restart.submit(
            {"job_id": "lost-on-restart", "kind": "qa", "payload": {"question": "test"}}
        )
        self.assertEqual(status, 202)
        self.assertEqual(submitted["status"], "queued")

        after_restart = MockJobStore(delay_seconds=60)
        status, body = after_restart.get("lost-on-restart")

        self.assertEqual(status, 404)
        self.assertEqual(body, {"error": "job_not_found"})

    def test_client_uses_fixed_job_id_kind_payload_contract(self):
        with RunningMock() as mock, override_settings(
            AI_API_URL=mock.url, AI_API_TOKEN=TOKEN, AI_HTTP_TIMEOUT=2
        ):
            client = RunPodClient()
            work = job("job-qa-1", "qa", {"question": "SSH 설정 방법은?"})

            submitted = client.submit(work)
            completed = client.status(work)

        self.assertEqual(submitted, {"job_id": "job-qa-1", "kind": "qa", "status": "queued"})
        self.assertEqual(completed["status"], "succeeded")
        ChatResponse.model_validate(completed["result"])

    def test_quiz_result_reuses_quiz_response_contract(self):
        with RunningMock() as mock, override_settings(
            AI_API_URL=mock.url, AI_API_TOKEN=TOKEN, AI_HTTP_TIMEOUT=2
        ):
            work = job("job-quiz-1", "quiz")
            client = RunPodClient()
            client.submit(work)
            completed = client.status(work)

        QuizResponse.model_validate(completed["result"])

    def test_same_job_id_is_idempotent_but_different_payload_conflicts(self):
        with RunningMock(delay_seconds=60) as mock, override_settings(
            AI_API_URL=mock.url, AI_API_TOKEN=TOKEN, AI_HTTP_TIMEOUT=2
        ):
            client = RunPodClient()
            original = job("job-idempotent", "qa", {"question": "first"})
            self.assertEqual(client.submit(original)["status"], "queued")
            self.assertEqual(client.submit(original)["status"], "queued")
            changed = job("job-idempotent", "qa", {"question": "changed"})
            with self.assertRaisesRegex(RemoteAIError, "service_unavailable"):
                client.submit(changed)

    def test_cancel_reaches_terminal_state_and_drops_result(self):
        with RunningMock(delay_seconds=60) as mock, override_settings(
            AI_API_URL=mock.url, AI_API_TOKEN=TOKEN, AI_HTTP_TIMEOUT=2
        ):
            client = RunPodClient()
            work = job("job-cancel-1", "recommendation")
            client.submit(work)
            cancelled = client.cancel(work)
            after = client.status(work)

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(after["status"], "cancelled")
        self.assertNotIn("result", after)

    def test_failure_and_bad_token_are_explicit(self):
        with RunningMock(mode="failure") as mock, override_settings(
            AI_API_URL=mock.url, AI_API_TOKEN=TOKEN, AI_HTTP_TIMEOUT=2
        ):
            client = RunPodClient()
            work = job("job-failure-1", "qa")
            client.submit(work)
            self.assertEqual(client.status(work)["status"], "failed")

        with RunningMock() as mock, override_settings(
            AI_API_URL=mock.url, AI_API_TOKEN="wrong", AI_HTTP_TIMEOUT=2
        ):
            with self.assertRaisesRegex(RemoteAIError, "authentication_failed"):
                RunPodClient().submit(job("job-auth-1", "qa"))

    def test_readiness_is_independent_of_job_queue(self):
        with RunningMock(delay_seconds=60) as mock, override_settings(
            AI_API_URL=mock.url, AI_API_TOKEN=TOKEN, AI_HTTP_TIMEOUT=2
        ):
            self.assertTrue(RunPodClient().readiness())
