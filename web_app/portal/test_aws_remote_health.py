"""AWS 웹 컨테이너가 원격 RunPod 준비 상태를 사용하는지 검증한다."""

import json
import inspect
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase
from django.urls import resolve

class AwsRemoteHealthTests(TestCase):
    def test_health_uses_ready_remote_service(self):
        health_view = resolve("/health/").func
        health_globals = inspect.unwrap(health_view).__globals__
        client = SimpleNamespace(readiness=lambda: True)
        with patch.dict(
            health_globals,
            {"remote_enabled": lambda: True, "RunPodClient": lambda: client},
        ):
            response = health_view(RequestFactory().get("/health/"))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["ready"])

    def test_health_hides_remote_configuration_details(self):
        health_view = resolve("/health/").func
        health_globals = inspect.unwrap(health_view).__globals__

        def unavailable():
            raise health_globals["RemoteAIError"]("configuration_error")

        client = SimpleNamespace(readiness=unavailable)
        with patch.dict(
            health_globals,
            {"remote_enabled": lambda: True, "RunPodClient": lambda: client},
        ):
            response = health_view(RequestFactory().get("/health/"))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["status"], "not_ready")
        self.assertFalse(payload["ready"])
        self.assertNotIn("configuration_error", payload["message"])
