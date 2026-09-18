"""Small authenticated HTTP boundary; never import GPU libraries on AWS."""

from __future__ import annotations

from urllib.parse import urlsplit

import requests
from django.conf import settings


REMOTE_STATES = {"queued", "running", "cancelling", "succeeded", "failed", "cancelled", "expired"}


class RemoteAIError(Exception):
    def __init__(self, code: str, *, status: int = 503):
        super().__init__(code)
        self.code = code
        self.status = status


class RunPodClient:
    def __init__(self):
        self.base_url = settings.AI_API_URL.rstrip("/")
        self.token = settings.AI_API_TOKEN
        parsed = urlsplit(self.base_url)
        if not self.token or not parsed.hostname or parsed.username or parsed.password:
            raise RemoteAIError("configuration_error")
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        ):
            raise RemoteAIError("configuration_error")

    def _request(self, method, path, *, body=None, timeout=None):
        try:
            response = requests.request(
                method, self.base_url + path,
                json=body,
                headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
                timeout=timeout or settings.AI_HTTP_TIMEOUT,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise RemoteAIError("connection_unavailable") from None
        if response.status_code == 404:
            raise RemoteAIError("job_not_found", status=404)
        if response.status_code == 429:
            raise RemoteAIError("queue_full", status=429)
        if response.status_code in {401, 403}:
            raise RemoteAIError("authentication_failed")
        if not 200 <= response.status_code < 300:
            raise RemoteAIError("service_unavailable")
        try:
            payload = response.json()
        except ValueError:
            raise RemoteAIError("invalid_response") from None
        if not isinstance(payload, dict):
            raise RemoteAIError("invalid_response")
        return payload

    @staticmethod
    def _job_response(data, job_id, kind):
        if (
            data.get("job_id") != str(job_id)
            or data.get("kind") != kind
            or data.get("status") not in REMOTE_STATES
            or (data.get("status") == "succeeded" and not isinstance(data.get("result"), dict))
        ):
            raise RemoteAIError("invalid_response")
        return data

    def submit(self, job):
        data = self._request("POST", "/v1/jobs", body={
            "job_id": str(job.pk), "kind": job.kind, "payload": job.input_payload,
        })
        return self._job_response(data, job.pk, job.kind)

    def status(self, job):
        return self._job_response(self._request("GET", f"/v1/jobs/{job.pk}"), job.pk, job.kind)

    def cancel(self, job):
        return self._job_response(
            self._request("POST", f"/v1/jobs/{job.pk}/cancel", body={}), job.pk, job.kind,
        )

    def readiness(self):
        data = self._request("GET", "/health/ready", timeout=min(settings.AI_HTTP_TIMEOUT, 2))
        return data.get("ready") is True
