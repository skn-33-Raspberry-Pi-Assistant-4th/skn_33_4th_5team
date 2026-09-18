"""Small authenticated HTTP boundary; never import GPU libraries on AWS."""

from __future__ import annotations

from urllib.parse import urlsplit

import requests
from django.conf import settings


REMOTE_STATES = {"queued", "running", "cancelling", "succeeded", "failed", "cancelled", "expired"}


class RemoteAIError(Exception):
    """RunPod 원격 AI 호출 중 발생한 오류를 코드와 HTTP 상태값으로 전달한다."""

    def __init__(self, code: str, *, status: int = 503):
        """화면/서비스 계층에서 처리할 오류 코드와 상태값을 저장한다."""

        super().__init__(code)
        self.code = code
        self.status = status


class RunPodClient:
    def __init__(self):
        """Django 설정에서 RunPod API 주소와 인증 토큰을 읽고 유효성을 검사한다."""

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
        """RunPod Django API에 인증된 HTTP 요청을 보내고 JSON 객체를 반환한다."""

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
        """RunPod가 반환한 작업 응답이 요청한 작업과 일치하는지 검증한다."""

        if (
            data.get("job_id") != str(job_id)
            or data.get("kind") != kind
            or data.get("status") not in REMOTE_STATES
            or (data.get("status") == "succeeded" and not isinstance(data.get("result"), dict))
        ):
            raise RemoteAIError("invalid_response")
        return data

    def submit(self, job):
        """AWS에 저장된 AI 작업을 RunPod의 작업 큐에 등록한다."""

        data = self._request("POST", "/v1/jobs", body={
            "job_id": str(job.pk), "kind": job.kind, "payload": job.input_payload,
        })
        return self._job_response(data, job.pk, job.kind)

    def status(self, job):
        """RunPod에서 현재 작업 상태와 완료 결과를 조회한다."""

        return self._job_response(self._request("GET", f"/v1/jobs/{job.pk}"), job.pk, job.kind)

    def cancel(self, job):
        """RunPod에 대기 중이거나 실행 중인 작업의 취소를 요청한다."""

        return self._job_response(
            self._request("POST", f"/v1/jobs/{job.pk}/cancel", body={}), job.pk, job.kind,
        )

    def readiness(self):
        """RunPod AI 런타임이 요청을 처리할 준비가 되었는지 확인한다."""

        data = self._request("GET", "/health/ready", timeout=min(settings.AI_HTTP_TIMEOUT, 2))
        return data.get("ready") is True
