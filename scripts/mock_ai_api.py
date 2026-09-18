#!/usr/bin/env python3
"""Small dependency-free fake of the private RunPod job API.

This server is for AWS/Django integration checks.  It deliberately implements
the same authenticated, asynchronous boundary as production without importing
model or GPU libraries.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit


KINDS = {"qa", "recommendation", "quiz"}


def _chat_result(job_id: str) -> dict[str, Any]:
    return {
        "schema_version": "1.2.0",
        "request_id": job_id,
        "status": "insufficient_evidence",
        "language": "ko",
        "answer": "통합 테스트용 모의 응답입니다.",
        "conditions": None,
        "citations": [],
        "products": [],
        "media": [],
        "clarification_questions": [],
        "warnings": ["mock_ai_api"],
    }


def result_for(kind: str, job_id: str) -> dict[str, Any]:
    if kind == "quiz":
        return {"status": "insufficient_content", "questions": []}
    return _chat_result(job_id)


@dataclass
class MockJobStore:
    """Thread-safe in-memory jobs with deterministic success/failure modes."""

    mode: str = "success"
    delay_seconds: float = 0.0
    jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def submit(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if set(body) != {"job_id", "kind", "payload"}:
            return HTTPStatus.UNPROCESSABLE_ENTITY, {"error": "invalid_request"}
        job_id, kind, payload = body["job_id"], body["kind"], body["payload"]
        if not isinstance(job_id, str) or not job_id or kind not in KINDS or not isinstance(payload, dict):
            return HTTPStatus.UNPROCESSABLE_ENTITY, {"error": "invalid_request"}
        with self.lock:
            existing = self.jobs.get(job_id)
            if existing:
                if existing["kind"] != kind or existing["payload"] != payload:
                    return HTTPStatus.CONFLICT, {"error": "job_id_conflict"}
                return HTTPStatus.OK, self.public(existing)
            job = {
                "job_id": job_id,
                "kind": kind,
                "payload": payload,
                "status": "queued",
                "submitted_at": time.monotonic(),
            }
            self.jobs[job_id] = job
            return HTTPStatus.ACCEPTED, self.public(job)

    def get(self, job_id: str) -> tuple[int, dict[str, Any]]:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return HTTPStatus.NOT_FOUND, {"error": "job_not_found"}
            self._advance(job)
            return HTTPStatus.OK, self.public(job)

    def cancel(self, job_id: str) -> tuple[int, dict[str, Any]]:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return HTTPStatus.NOT_FOUND, {"error": "job_not_found"}
            if job["status"] not in {"succeeded", "failed", "cancelled"}:
                job["status"] = "cancelled"
            return HTTPStatus.OK, self.public(job)

    def _advance(self, job: dict[str, Any]) -> None:
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            return
        elapsed = time.monotonic() - job["submitted_at"]
        if elapsed < self.delay_seconds:
            job["status"] = "running"
            return
        job["status"] = "failed" if self.mode == "failure" else "succeeded"

    @staticmethod
    def public(job: dict[str, Any]) -> dict[str, Any]:
        data: dict[str, Any] = {
            "job_id": job["job_id"],
            "kind": job["kind"],
            "status": job["status"],
        }
        if job["status"] == "succeeded":
            data["result"] = result_for(job["kind"], job["job_id"])
        elif job["status"] == "failed":
            data["error"] = {"code": "mock_generation_failed"}
        return data


class MockAIRequestHandler(BaseHTTPRequestHandler):
    server: "MockAIServer"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        if path == "/health/live":
            self._send(HTTPStatus.OK, {"live": True})
            return
        if path == "/health/ready":
            self._send(HTTPStatus.OK, {"ready": True})
            return
        if not self._authorized():
            return
        job_id = self._job_id(path)
        if job_id is None:
            self._send(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        self._send(*self.server.store.get(job_id))

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if not self._authorized():
            return
        path = urlsplit(self.path).path
        if path == "/v1/jobs":
            body = self._read_json()
            if body is None:
                return
            self._send(*self.server.store.submit(body))
            return
        if path.endswith("/cancel"):
            job_id = self._job_id(path.removesuffix("/cancel"))
            if job_id is not None:
                self._send(*self.server.store.cancel(job_id))
                return
        self._send(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def _authorized(self) -> bool:
        if self.headers.get("Authorization") == f"Bearer {self.server.token}":
            return True
        self._send(HTTPStatus.UNAUTHORIZED, {"error": "authentication_failed"})
        return False

    @staticmethod
    def _job_id(path: str) -> str | None:
        prefix = "/v1/jobs/"
        value = path[len(prefix):] if path.startswith(prefix) else ""
        return value if value and "/" not in value else None

    def _read_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
            return None
        if not isinstance(data, dict):
            self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
            return None
        return data

    def _send(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return


class MockAIServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], *, token: str, store: MockJobStore):
        super().__init__(address, MockAIRequestHandler)
        self.token = token
        self.store = store


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PiCare fake private AI API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--mode", choices=("success", "failure"), default="success")
    parser.add_argument("--delay-seconds", type=float, default=0.0)
    args = parser.parse_args()
    token = os.environ.get("AI_API_TOKEN", "")
    if len(token) < 32:
        parser.error("AI_API_TOKEN must contain at least 32 characters")
    server = MockAIServer(
        (args.host, args.port),
        token=token,
        store=MockJobStore(mode=args.mode, delay_seconds=max(0.0, args.delay_seconds)),
    )
    print(f"mock AI API listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
