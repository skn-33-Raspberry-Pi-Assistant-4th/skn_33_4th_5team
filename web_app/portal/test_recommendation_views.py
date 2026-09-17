"""Recommendation history integration tests without inference or shared DB writes."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.test import Client, TestCase
from django.urls import reverse

from src.condition_extraction.ui_input import RecommendationFormInput
from src.contracts import ChatResponse

from .models import RecommendationRecord
from .views import ACTIVITY_PAGE_SIZE, MYPAGE_RECENT_LIMIT, RECOMMENDATION_SESSION_KEY


class RecommendationHistoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(username="recommend-owner")
        cls.other = get_user_model().objects.create_user(username="recommend-other")
        cls.admin = get_user_model().objects.create_superuser(
            username="recommend-admin", email="admin@example.com", password="TestOnly123!"
        )

    def setUp(self):
        for target, value in (
            ("portal.views.get_runtime_readiness", SimpleNamespace(ready=True, message="ready")),
            ("portal.views.get_citation_presenter", None),
        ):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def response(status="answered"):
        data = {
            "schema_version": "1.2.0", "request_id": "recommend-response-1",
            "status": status, "language": "ko", "answer": "추천 근거가 부족합니다.",
            "conditions": None, "citations": [], "products": [], "media": [],
            "clarification_questions": ["사용 목적은 무엇인가요?"] if status == "needs_clarification" else [],
            "warnings": ["INTERNAL_SNAPSHOT_ONLY"],
        }
        if status == "answered":
            data.update(
                answer="홈 서버에 Raspberry Pi 5를 추천합니다. [C1]",
                citations=[{
                    "citation_id": "C1", "document_id": "rpi-doc-pi5", "chunk_id": "rpi-doc-pi5-001",
                    "title": "Raspberry Pi 5", "publisher": "Raspberry Pi Ltd", "section": "Specifications",
                    "source_url": "https://www.raspberrypi.com/products/raspberry-pi-5/",
                    "source_anchor": None, "document_version": None, "published_at": None,
                    "updated_at": None, "collected_at": "2026-09-12", "license": "CC BY-SA 4.0",
                    "quote": "Raspberry Pi 5 specifications.",
                }],
                products=[{
                    "product_id": "rpi5", "product_model": "Raspberry Pi 5", "recommendation": "홈 서버용 후보",
                    "matched_conditions": ["홈 서버"], "limitations": ["별도 전원 필요"], "citation_ids": ["C1"],
                    "product_url": "https://www.raspberrypi.com/products/raspberry-pi-5/", "image_url": None,
                }],
                media=[{
                    "media_id": "rpi-product-0001", "media_type": "image", "title": "공식 제품 사진",
                    "url": "https://www.raspberrypi.com/test-image.png", "alt_text": "제품 사진",
                    "display_mode": "inline", "license": "test", "attribution": "Raspberry Pi",
                    "source_citation_id": "C1",
                }],
            )
        return ChatResponse.model_validate(data)

    def submit(self, response=None, **overrides):
        service = Mock()
        service.answer_form.return_value = response or self.response()
        data = {
            "purpose": "홈 서버를 추천해주세요. 두 번째 문장입니다.", "user_level": "입문자",
            "performance": "높음", "wifi": "false", "camera": "", "gpio": "true", "monitor_absent": "true",
        }
        data.update(overrides)
        with patch("portal.views.get_recommendation_service", return_value=service):
            page = self.client.post(reverse("recommend"), data)
        return page, service

    def record(self, owner=None, title="저장된 추천"):
        response = self.response()
        saved_input = RecommendationFormInput(
            request_id=response.request_id, free_text="홈 서버를 추천해주세요.",
            wireless_required=False, camera_required=None, gpio_required=True, monitor_absent=True,
        )
        return RecommendationRecord.objects.create(
            owner=owner or self.owner, request_id=response.request_id, title=title,
            question=saved_input.free_text, answer=response.answer, status=response.status,
            input_payload=saved_input.model_dump(mode="json"), response_payload=response.model_dump(mode="json"),
        )

    def save(self, page, **extra):
        return self.client.post(reverse("recommendation_save"), {
            "token": page.context["recommendation_save_token"], **extra,
        })

    def test_button_saves_all_valid_statuses_and_deduplicates_clicks(self):
        self.client.force_login(self.owner)
        for status in ("answered", "needs_clarification", "insufficient_evidence", "out_of_scope", "safety_blocked", "error"):
            with self.subTest(status=status):
                response = self.response(status)
                count_before = RecommendationRecord.objects.count()
                page, service = self.submit(response)
                self.assertEqual(RecommendationRecord.objects.count(), count_before)
                self.assertContains(page, "제품추천 기록 저장")
                with patch("portal.views.get_recommendation_service") as factory:
                    saved = self.save(page, answer="FORGED", owner_id=self.other.pk)
                    repeated = self.save(page)
                factory.assert_not_called()
                self.assertEqual(saved.status_code, 200)
                self.assertEqual(saved.json(), repeated.json())
                self.assertEqual(RecommendationRecord.objects.count(), count_before + 1)
                record = RecommendationRecord.objects.first()
                self.assertEqual(saved.json()["message"], "내 제품추천 기록에 저장했습니다.")
                self.assertEqual(record.owner, self.owner)
                self.assertEqual(record.request_id, response.request_id)
                self.assertEqual(record.title, "홈 서버를 추천해주세요.")
                self.assertEqual(record.question, service.answer_form.call_args.kwargs["form"].free_text)
                self.assertEqual(record.answer, response.answer)
                self.assertEqual(record.status, status)
                self.assertEqual(record.response_payload, response.model_dump(mode="json"))
                self.assertEqual(record.input_payload, service.answer_form.call_args.kwargs["form"].model_dump(mode="json"))
                self.assertIs(record.input_payload["wireless_required"], False)
                self.assertIsNone(record.input_payload["camera_required"])
        page, _ = self.submit()
        self.save(page)
        self.assertEqual(RecommendationRecord.objects.count(), 7)

    def test_guest_invalid_input_and_service_error_do_not_save(self):
        page, _ = self.submit()
        self.assertContains(page, "홈 서버용 후보")
        self.assertNotContains(page, "내 제품추천 기록에 저장했습니다")
        self.assertNotContains(page, 'id="recommendationSaveForm"')
        self.assertNotIn(RECOMMENDATION_SESSION_KEY, self.client.session)
        self.assertEqual(self.client.post(reverse("recommendation_save"), {"token": "fake"}).status_code, 401)
        self.client.force_login(self.owner)
        self.client.get(reverse("recommend"))
        self.assertEqual(RecommendationRecord.objects.count(), 0)
        for data in ({"purpose": " "}, {"wifi": "invalid"}):
            _, service = self.submit(**data)
            service.answer_form.assert_not_called()
        with patch("portal.views.get_recommendation_service", side_effect=RuntimeError("INTERNAL_SECRET")):
            page = self.client.post(reverse("recommend"), {"purpose": "추천해주세요"})
        self.assertContains(page, "제품 추천 서비스를 일시적으로 이용할 수 없습니다")
        self.assertNotContains(page, "INTERNAL_SECRET")
        self.assertEqual(RecommendationRecord.objects.count(), 0)

    def test_unvalidated_service_result_is_not_persisted(self):
        self.client.force_login(self.owner)
        invalid = self.response().model_copy(update={"citations": []})
        with self.assertLogs("portal.views", level="ERROR"):
            page, _ = self.submit(invalid)
        self.assertNotContains(page, 'id="recommendationSaveForm"')
        self.assertNotIn(RECOMMENDATION_SESSION_KEY, self.client.session)
        self.assertEqual(RecommendationRecord.objects.count(), 0)

    def test_save_failure_keeps_cards_and_hides_internal_error(self):
        self.client.force_login(self.owner)
        page, _ = self.submit()
        self.assertContains(page, "홈 서버용 후보")
        with (
            patch("portal.views.RecommendationRecord.objects.create", side_effect=DatabaseError("PRIVATE_DB_ERROR")),
            self.assertLogs("portal.views", level="ERROR"),
        ):
            failed = self.save(page)
        self.assertEqual(failed.status_code, 503)
        self.assertIn("제품추천 기록을 저장하지 못했습니다", failed.json()["error"])
        self.assertNotIn("PRIVATE_DB_ERROR", failed.content.decode())
        self.assertEqual(RecommendationRecord.objects.count(), 0)
        self.assertEqual(self.save(page).status_code, 200)
        self.assertEqual(RecommendationRecord.objects.count(), 1)

    def test_title_is_limited_to_200_characters(self):
        self.client.force_login(self.owner)
        page, _ = self.submit(purpose="가" * 250)
        self.save(page)
        self.assertEqual(RecommendationRecord.objects.get().title, "가" * 200)

    def test_save_rejects_missing_stale_tampered_and_wrong_owner_snapshots(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse("recommendation_save"), {"token": "fake"}).status_code, 409)
        old_page, _ = self.submit()
        page, _ = self.submit()
        self.assertEqual(self.save(old_page).status_code, 409)
        self.assertEqual(self.save(page, token="fake").status_code, 409)
        snapshot = self.client.session[RECOMMENDATION_SESSION_KEY]
        for field, value in (("owner_id", self.other.pk), ("response", {"broken": True}), ("input", {})):
            with self.subTest(field=field):
                session = self.client.session
                session[RECOMMENDATION_SESSION_KEY] = {**snapshot, field: value}
                session.save()
                self.assertEqual(self.save(page).status_code, 409)
        self.assertEqual(RecommendationRecord.objects.count(), 0)

    def test_new_invalid_request_and_logout_invalidate_pending_save(self):
        self.client.force_login(self.owner)
        page, _ = self.submit()
        self.submit(purpose=" ")
        self.assertEqual(self.save(page).status_code, 409)
        page, _ = self.submit()
        self.client.logout()
        self.client.force_login(self.other)
        self.assertEqual(self.save(page).status_code, 409)
        self.assertEqual(RecommendationRecord.objects.count(), 0)

    def test_save_requires_post_and_csrf(self):
        self.client.force_login(self.owner)
        page, _ = self.submit()
        client = Client(enforce_csrf_checks=True)
        client.cookies = self.client.cookies
        url = reverse("recommendation_save")
        self.assertEqual(client.get(url).status_code, 405)
        data = {"token": page.context["recommendation_save_token"]}
        self.assertEqual(client.post(url, data).status_code, 403)
        self.assertEqual(RecommendationRecord.objects.count(), 0)
        data["csrfmiddlewaretoken"] = client.cookies["csrftoken"].value
        self.assertEqual(client.post(url, data).status_code, 200)
        self.assertEqual(RecommendationRecord.objects.count(), 1)

    def test_history_pagination_and_mypage_only_show_owner_records(self):
        self.record(owner=self.other, title="타인의 비밀 추천")
        records = [self.record(title=f"내 추천 {index}") for index in range(ACTIVITY_PAGE_SIZE + 1)]
        self.client.force_login(self.owner)
        page = self.client.get(reverse("mypage_recommendations"))
        self.assertEqual(list(page.context["page_obj"]), list(reversed(records))[:ACTIVITY_PAGE_SIZE])
        self.assertNotContains(page, "타인의 비밀 추천")
        page2 = self.client.get(reverse("mypage_recommendations"), {"page": 2})
        self.assertEqual(list(page2.context["page_obj"]), records[:1])
        summary = self.client.get(reverse("mypage"))
        self.assertEqual(summary.context["activity_counts"]["recommendation_records"], len(records))
        self.assertEqual(list(summary.context["recent_recommendation_records"]), list(reversed(records))[:MYPAGE_RECENT_LIMIT])
        self.assertNotContains(summary, "타인의 비밀 추천")

    def test_detail_restores_snapshot_without_calling_recommendation_service(self):
        record = self.record()
        self.client.force_login(self.owner)
        with patch("portal.views.get_recommendation_service", side_effect=AssertionError("must not infer")) as service:
            page = self.client.get(reverse("mypage_recommendation_detail", args=[record.pk]))
        service.assert_not_called()
        for text in (record.question, "홈 서버용 후보", "Raspberry Pi 5 specifications.", "공식 제품 사진"):
            self.assertContains(page, text)
        self.assertEqual(dict(page.context["input_conditions"])["Wi-Fi 필요"], "아니오")
        self.assertEqual(dict(page.context["input_conditions"])["카메라 사용"], "선택 안 함")
        self.assertEqual(dict(page.context["input_conditions"])["모니터 없음"], "예")
        self.assertNotContains(page, "INTERNAL_SNAPSHOT_ONLY")
        self.assertNotContains(page, "질문 아카이브에 공개")
        archive = self.client.get(reverse("questions"))
        self.assertNotContains(archive, record.title)

    def test_invalid_saved_payloads_show_base_record(self):
        self.client.force_login(self.owner)
        for field in ("input_payload", "response_payload"):
            with self.subTest(field=field):
                record = self.record()
                setattr(record, field, {"broken": True})
                record.save(update_fields=[field])
                with self.assertLogs("portal.views", level="WARNING"):
                    page = self.client.get(reverse("mypage_recommendation_detail", args=[record.pk]))
                self.assertContains(page, "저장된 상세 결과 일부를 복원하지 못했습니다")
                self.assertContains(page, record.question)
                self.assertContains(page, record.answer)

    def test_owner_only_access_including_admin(self):
        record = self.record()
        detail = reverse("mypage_recommendation_detail", args=[record.pk])
        delete = reverse("mypage_recommendation_delete", args=[record.pk])
        for url, method in ((reverse("mypage_recommendations"), "get"), (detail, "get"), (delete, "post")):
            self.assertEqual(getattr(self.client, method)(url).status_code, 302)
        for user in (self.other, self.admin):
            self.client.force_login(user)
            self.assertEqual(self.client.get(detail).status_code, 404)
            self.assertEqual(self.client.post(delete).status_code, 404)
        self.assertTrue(RecommendationRecord.objects.filter(pk=record.pk).exists())

    def test_delete_requires_post_and_csrf_and_updates_history(self):
        record = self.record()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        delete = reverse("mypage_recommendation_delete", args=[record.pk])
        detail = reverse("mypage_recommendation_detail", args=[record.pk])
        self.assertEqual(client.get(delete).status_code, 405)
        self.assertEqual(client.post(delete).status_code, 403)
        client.get(detail)
        result = client.post(delete, {"csrfmiddlewaretoken": client.cookies["csrftoken"].value})
        self.assertRedirects(result, reverse("mypage_recommendations"))
        self.assertFalse(RecommendationRecord.objects.filter(pk=record.pk).exists())
        self.assertEqual(client.get(detail).status_code, 404)
        self.assertContains(client.get(reverse("mypage_recommendations")), "저장된 제품추천 기록이 없습니다")
        summary = client.get(reverse("mypage"))
        self.assertEqual(summary.context["activity_counts"]["recommendation_records"], 0)
        self.assertEqual(list(summary.context["recent_recommendation_records"]), [])
