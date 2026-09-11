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

from django.test import SimpleTestCase


def response(*, status: str = "answered"):
    citation = SimpleNamespace(
        citation_id="C1", title="Raspberry Pi Documentation", section="Getting started > SSH", source_url="https://www.raspberrypi.com/documentation/", quote="SSH 설정 근거",
    )
    product = SimpleNamespace(
        product_model="Raspberry Pi 5", image_url=None, recommendation="홈 서버에 적합합니다.", limitations=["전원 요구 사항을 확인하세요."], product_url="https://www.raspberrypi.com/products/raspberry-pi-5/", citation_ids=["C1"],
    )
    return SimpleNamespace(
        status=status, answer="공식 문서 기준 안내입니다. [C1]", citations=[citation], products=[product], media=[], clarification_questions=[], warnings=[], conditions=None,
    )


class DjangoPortalTests(SimpleTestCase):
    @patch("portal.views.get_runtime_readiness", return_value=SimpleNamespace(ready=True, message="ready"))
    def test_public_pages_are_available(self, _readiness):
        for path in ("/", "/recommend/", "/qa/", "/health/"):
            result = self.client.get(path)
            self.assertEqual(result.status_code, 200)

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
        service.answer.assert_called_once()

    @patch("portal.views.get_runtime_readiness", return_value=SimpleNamespace(ready=True, message="ready"))
    @patch("portal.views.get_qa_service")
    def test_blank_question_does_not_call_service(self, service_factory, _readiness):
        result = self.client.post("/qa/", {"question": "   "})
        self.assertContains(result, "최소 1자")
        service_factory.assert_not_called()
