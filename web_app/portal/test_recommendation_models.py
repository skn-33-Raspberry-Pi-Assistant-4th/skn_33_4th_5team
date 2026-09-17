"""Persistence checks for recommendation snapshots; no model inference needed."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from src.condition_extraction.ui_input import RecommendationFormInput
from src.contracts import ChatResponse

from .models import RecommendationRecord


class RecommendationRecordTests(TestCase):
    def test_snapshot_round_trip_ordering_and_owner_deletion(self):
        owner = get_user_model().objects.create_user(username="recommendation_owner")
        other = get_user_model().objects.create_user(username="recommendation_other")
        form = RecommendationFormInput(
            request_id="r" * 120,
            free_text="모니터 없이 홈 서버로 사용하고 싶어요.",
            wireless_required=False,
            camera_required=None,
            monitor_absent=True,
        )
        response = ChatResponse(
            schema_version="1.2.0", request_id=form.request_id,
            status="insufficient_evidence", language="ko",
            answer="추천할 공식 문서 근거가 부족합니다.", conditions=None,
            citations=[], products=[], media=[], clarification_questions=[], warnings=[],
        )
        values = {
            "request_id": form.request_id, "title": "홈 서버 추천",
            "question": form.free_text, "answer": response.answer, "status": response.status,
            "input_payload": form.model_dump(mode="json"),
            "response_payload": response.model_dump(mode="json"),
        }
        first = RecommendationRecord.objects.create(owner=owner, **values)
        second = RecommendationRecord.objects.create(owner=owner, **values)
        retained = RecommendationRecord.objects.create(owner=other, **values)
        first.refresh_from_db()
        self.assertEqual(RecommendationFormInput.model_validate(first.input_payload), form)
        self.assertEqual(ChatResponse.model_validate(first.response_payload), response)
        self.assertIs(first.input_payload["wireless_required"], False)
        self.assertIsNone(first.input_payload["camera_required"])
        self.assertEqual(list(owner.recommendation_records.all()), [second, first])
        self.assertIsNotNone(first.created_at)
        self.assertIsNotNone(first.updated_at)
        owner.delete()
        self.assertFalse(RecommendationRecord.objects.filter(pk__in=[first.pk, second.pk]).exists())
        self.assertTrue(RecommendationRecord.objects.filter(pk=retained.pk).exists())
