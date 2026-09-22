"""AWS 웹 컨테이너가 원격 RunPod 준비 상태를 사용하는지 검증한다."""

from unittest.mock import patch

from django.test import TestCase

from .remote_ai import RemoteAIError


class AwsRemoteHealthTests(TestCase):
    @patch("portal.views.remote_enabled", return_value=True)
    @patch("portal.views.RunPodClient.readiness", return_value=True)
    def test_health_uses_ready_remote_service(self, _readiness, _remote_enabled):
        response = self.client.get("/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertTrue(response.json()["ready"])

    @patch("portal.views.remote_enabled", return_value=True)
    @patch(
        "portal.views.RunPodClient.readiness",
        side_effect=RemoteAIError("configuration_error"),
    )
    def test_health_hides_remote_configuration_details(self, _readiness, _remote_enabled):
        response = self.client.get("/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "not_ready")
        self.assertFalse(response.json()["ready"])
        self.assertNotIn("configuration_error", response.json()["message"])
