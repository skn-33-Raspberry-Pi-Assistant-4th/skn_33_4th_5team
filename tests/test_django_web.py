"""Django presentation tests with the existing services mocked at the boundary."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
WEB_APP = ROOT / "web_app"
if str(WEB_APP) not in sys.path:
    sys.path.insert(0, str(WEB_APP))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "picare_web.settings")

import django

django.setup()

from django.test import Client, TestCase
from src.services.command_lab_service import CommandLabService


def response(*, status: str = "answered", document_id: str = "rpi-doc-remote-access-ssh"):
    citation = SimpleNamespace(
        citation_id="C1", document_id=document_id, title="Raspberry Pi Documentation", section="Getting started > SSH", source_url="https://www.raspberrypi.com/documentation/", quote="SSH 설정 근거",
    )
    product = SimpleNamespace(
        product_model="Raspberry Pi 5", image_url=None, recommendation="홈 서버에 적합합니다.", limitations=["전원 요구 사항을 확인하세요."], product_url="https://www.raspberrypi.com/products/raspberry-pi-5/", citation_ids=["C1"],
    )
    return SimpleNamespace(
        status=status, answer="공식 문서 기준 안내입니다. [C1]", citations=[citation], products=[product], media=[], clarification_questions=[], warnings=[], conditions=None,
    )


class DjangoPortalTests(TestCase):
    @patch("portal.views.get_runtime_readiness", return_value=SimpleNamespace(ready=True, message="ready"))
    def test_public_pages_are_available(self, _readiness):
        for path in ("/", "/recommend/", "/qa/", "/questions/", "/lab/", "/challenge/", "/health/"):
            result = self.client.get(path)
            self.assertEqual(result.status_code, 200)

    @patch("portal.views.get_runtime_readiness", return_value=SimpleNamespace(ready=True, message="ready"))
    def test_question_archive_shows_only_the_public_empty_state_before_records_exist(self, _readiness):
        page = self.client.get("/questions/")
        self.assertContains(page, "질문 아카이브")
        self.assertContains(page, "아직 공개된 질문이 없습니다")
        self.assertNotContains(page, "저장 및 AI 생성은 아직 연결하지 않았습니다")
        self.assertEqual(self.client.get("/questions/1/").status_code, 404)
        self.assertEqual(self.client.get("/questions/999/").status_code, 404)

    @patch("portal.views.get_runtime_readiness", return_value=SimpleNamespace(ready=True, message="ready"))
    def test_command_lab_api_exposes_only_approved_browser_payload(self, _readiness):
        templates = self.client.get("/api/lab/templates").json()["templates"]
        self.assertEqual(len(templates), 100)
        self.assertEqual(CommandLabService().audit()["approved"], 100)
        self.assertNotIn("review_status", templates[0])
        self.assertNotIn("evidence_checksums", templates[0])

        result = self.client.post(
            "/api/lab/analyze",
            data='{"command": "ssh pi@192.168.0.12"}',
            content_type="application/json",
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["command"], "ssh pi@192.168.0.12")
        self.assertNotIn("chunk_checksum", result.content.decode())

    @patch("portal.views.get_runtime_readiness", return_value=SimpleNamespace(ready=True, message="ready"))
    def test_command_lab_reference_layout_and_drawer_keep_server_generated_payload(self, _readiness):
        page = self.client.get("/lab/")
        self.assertContains(page, "안전 모드 · 명령은 실행되지 않음")
        self.assertContains(page, "PiCare Command Lab")
        self.assertContains(page, "명령어 라이브러리")
        self.assertContains(page, "100개")
        self.assertContains(page, "명령어나 설명 검색")
        self.assertContains(page, "ssh learner@raspberrypi.local")

        saved = self.client.post(
            "/lab/",
            {"action": "save_drawer", "mode": "examples", "template_id": "cmd-remote-access-004", "value_part-02": "pi@192.168.0.12"},
        )
        self.assertContains(saved, "현재 명령을 실험 서랍에 담았습니다.")
        drawer = self.client.session["picare_command_lab_drawer"]
        self.assertEqual(len(drawer), 1)
        self.assertEqual(drawer[0]["command_snapshot"], "ssh pi@192.168.0.12")
        self.assertNotIn("rationale_ko", drawer[0])

    @patch("portal.views.get_runtime_readiness", return_value=SimpleNamespace(ready=True, message="ready"))
    def test_lab_qa_link_prefills_question_without_submitting_it(self, _readiness):
        result = self.client.get("/qa/?question=ssh%20pi%40192.168.0.12")
        self.assertContains(result, "ssh pi@192.168.0.12")

    @patch("portal.views.get_runtime_readiness", return_value=SimpleNamespace(ready=True, message="ready"))
    def test_challenge_keeps_answers_out_of_the_session_until_submission(self, _readiness):
        started = self.client.post("/challenge/", {"action": "start", "topic": "remote_access"})
        self.assertEqual(started.status_code, 200)
        self.assertNotIn("correct_choice_id", started.content.decode())
        state = self.client.session["picare_challenge"]
        self.assertNotIn("correct_choice_id", state)
        self.assertNotIn("rationale_ko", state)

        question = self.client.get("/challenge/")
        self.assertEqual(question.status_code, 200)
        question_id = state["question_ids"][state["current_index"]]
        choice_id = state["choice_orders"][question_id][0]
        submitted = self.client.post(
            "/challenge/", {"action": "submit", "question_id": question_id, "choice_id": choice_id}
        )
        self.assertEqual(submitted.status_code, 200)
        self.assertIn("공식 문서 해설", submitted.content.decode())

    @patch("portal.views.get_runtime_readiness", return_value=SimpleNamespace(ready=True, message="ready"))
    @patch("portal.views.get_citation_presenter", return_value=None)
    @patch("portal.views.get_recommendation_service")
    def test_recommendation_submits_existing_form_contract(self, service_factory, _presenter, _readiness):
        service = Mock()
        service.answer_form.return_value = response()
        service_factory.return_value = service
        result = self.client.post("/recommend/", {"purpose": "홈 서버를 만들고 싶어요", "user_level": "입문자", "performance": "보통", "wifi": "true", "camera": "", "gpio": "", "monitor_absent": "true"})
        self.assertContains(result, "Raspberry Pi 5")
        service.answer_form.assert_called_once()
        request_form = service.answer_form.call_args.kwargs["form"]
        self.assertEqual(request_form.free_text, "홈 서버를 만들고 싶어요")
        self.assertTrue(request_form.wireless_required)
        self.assertTrue(request_form.monitor_absent)

    @patch("portal.views.get_runtime_readiness", return_value=SimpleNamespace(ready=True, message="ready"))
    @patch("portal.views.get_citation_presenter", return_value=None)
    @patch("portal.views.get_qa_service")
    def test_qa_renders_answer_and_source(self, service_factory, _presenter, _readiness):
        service = Mock()
        service.answer.return_value = response()
        service_factory.return_value = service
        result = self.client.post("/qa/", {"question": "SSH를 어떻게 활성화하나요?"})
        self.assertContains(result, "공식 문서 기준 안내입니다.")
        self.assertContains(result, "Raspberry Pi Documentation")
        self.assertContains(result, "Mini Challenge")
        inline_state = self.client.session["picare_inline_challenge"]
        self.assertNotIn("correct_choice_id", str(inline_state))
        self.assertNotIn("rationale_ko", str(inline_state))
        service.answer.assert_called_once()

    @patch("portal.views.get_runtime_readiness", return_value=SimpleNamespace(ready=True, message="ready"))
    @patch("portal.views.get_citation_presenter", return_value=None)
    @patch("portal.views.get_qa_service")
    def test_qa_only_shows_inline_challenge_for_supported_document_ids(self, service_factory, _presenter, _readiness):
        service = Mock()
        service.answer.return_value = response(document_id="rpi-doc-hardware-introduction")
        service_factory.return_value = service

        result = self.client.post("/qa/", {"question": "제품의 사양이 궁금해요"})

        self.assertNotContains(result, "Mini Challenge")
        self.assertNotIn("picare_inline_challenge", self.client.session)

    @patch("portal.views.get_runtime_readiness", return_value=SimpleNamespace(ready=True, message="ready"))
    @patch("portal.views.get_citation_presenter", return_value=None)
    @patch("portal.views.get_qa_service")
    def test_inline_challenge_submission_reveals_explanation_only_after_answer(self, service_factory, _presenter, _readiness):
        service = Mock()
        service.answer.return_value = response(document_id="rpi-doc-getting-started-install")
        service_factory.return_value = service
        initial = self.client.post("/qa/", {"question": "OS는 어떻게 설치하나요?"})
        self.assertContains(initial, "Mini Challenge")
        state = self.client.session["picare_inline_challenge"]
        question_id = state["question_ids"][0]
        choice_id = state["choice_orders"][question_id][0]

        submitted = self.client.post(
            "/api/qa/mini-challenge/submit", {"question_id": question_id, "choice_id": choice_id}
        )

        self.assertEqual(submitted.status_code, 200)
        payload = submitted.json()
        self.assertIn("rationale_ko", payload)
        self.assertIn("evidence", payload)
        self.assertNotIn("state", payload)
        self.assertNotIn("chunk_checksum", submitted.content.decode())
        self.assertNotIn("picare_inline_challenge", self.client.session)

    def test_inline_challenge_submission_requires_csrf(self):
        csrf_client = Client(enforce_csrf_checks=True)

        result = csrf_client.post("/api/qa/mini-challenge/submit", {"question_id": "ssh-01", "choice_id": "A"})

        self.assertEqual(result.status_code, 403)

    @patch("portal.views.get_runtime_readiness", return_value=SimpleNamespace(ready=True, message="ready"))
    @patch("portal.views.get_qa_service")
    def test_blank_question_does_not_call_service(self, service_factory, _readiness):
        result = self.client.post("/qa/", {"question": "   "})
        self.assertContains(result, "최소 1자")
        service_factory.assert_not_called()
