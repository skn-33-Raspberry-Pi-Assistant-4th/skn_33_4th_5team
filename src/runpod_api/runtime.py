"""Shared PiCare model graph used by the serial RunPod worker."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Mapping
from pathlib import Path

from src.condition_extraction.schema import SurveyAnswer, SurveyResponse
from src.condition_extraction.ui_input import RecommendationFormInput
from src.contracts import ChatResponse, QaSummaryResult
from src.media import MediaResolver
from src.rag import HybridRetriever, RagSettings, load_indexed_at
from src.rag_to_llm import AnswerGeneratorSettings, build_answer_generator
from src.recommendation import (
    ProductRecommender,
    RecommendationSettings,
    build_condition_extractor,
    load_and_validate_catalog,
)
from src.services.integration_adapters import manifest_to_rag_result_metadata
from src.services.quiz_generator import QuizGenerator
from src.services.rag_qa_service import RagQaService
from src.services.recommendation_agent import RecommendationAgent
from src.services.recommendation_rag_service import RecommendationRagService
from src.rag_to_llm.quiz_text_generator import HuggingFaceQuizTextGenerator
from src.rag_to_llm.qa_summary_text_generator import build_qa_summary_text_generator
from src.rag_to_llm.cancellation import GenerationCancelled
from src.services.qa_summary import QaSummaryService

from .contracts import JobKind, QaPayload, QuizPayload


logger = logging.getLogger(__name__)


class RuntimeNotReadyError(RuntimeError):
    """Inference was requested before all persistent assets became usable."""


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name, "true" if default else "false").strip().lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return value == "true"


class PiCareRuntime:
    """Load one retriever and answer model shared by every AI feature."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.qa_service: RagQaService | None = None
        self.qa_summary_service: QaSummaryService | None = None
        self._qa_summary_text_generator = None
        self.recommendation_service: RecommendationRagService | None = None
        self.quiz_generator: QuizGenerator | None = None
        self._condition_extractor = None
        self._lock = threading.Lock()
        self._state = "initializing"
        self._message = "모델과 검색 색인을 준비하고 있습니다."

    @property
    def readiness(self) -> tuple[bool, str]:
        with self._lock:
            return self._state == "ready", self._message

    def initialize(self) -> None:
        """Build and warm all dependencies before accepting inference jobs."""

        try:
            rag_settings = RagSettings.from_env(self.project_root)
            answer_settings = AnswerGeneratorSettings.from_env(self.project_root)
            recommendation_settings = RecommendationSettings.from_env(self.project_root)
            if answer_settings.provider != "huggingface":
                raise RuntimeError("RunPod requires ANSWER_GENERATOR=huggingface")
            if recommendation_settings.condition_extractor != "lora":
                raise RuntimeError("RunPod requires CONDITION_EXTRACTOR=lora")

            retriever = HybridRetriever.from_manifest(
                rag_settings.manifest_path,
                chroma_path=rag_settings.chroma_path,
                collection_name=rag_settings.chroma_collection_name,
                embedding_model_name=rag_settings.e5_model_name,
                dense_max_distance=rag_settings.dense_max_distance,
            )
            # Opening the indexed collection metadata catches an absent or stale
            # persistent index before readiness becomes true.
            indexed_at = load_indexed_at(
                chroma_path=rag_settings.chroma_path,
                collection_name=rag_settings.chroma_collection_name,
                manifest_path=rag_settings.manifest_path,
            )
            answer_generator = build_answer_generator(answer_settings)
            media_resolver = MediaResolver.from_paths(
                media_manifest_path=rag_settings.media_manifest_path,
                document_manifest_path=rag_settings.manifest_path,
                media_chunk_map_path=rag_settings.media_chunk_map_path,
                image_manifest_path=self.project_root / "assets/media/manifest.json",
                video_manifest_path=self.project_root / "assets/media/video_manifest.json",
            )
            catalog, manifest = load_and_validate_catalog(
                catalog_path=recommendation_settings.catalog_path,
                manifest_path=rag_settings.manifest_path,
            )
            condition_extractor = build_condition_extractor(recommendation_settings)
            qa_service = RagQaService(
                retriever=retriever,
                answer_generator=answer_generator,
                media_resolver=media_resolver,
                top_k=rag_settings.top_k,
            )
            qa_summary_text_generator = build_qa_summary_text_generator(answer_generator)
            qa_summary_service = QaSummaryService(qa_summary_text_generator)
            recommendation_service = RecommendationRagService(
                recommendation_agent=RecommendationAgent(
                    extractor=condition_extractor,
                    recommender=ProductRecommender(catalog),
                ),
                retriever=retriever,
                metadata_by_chunk_id=manifest_to_rag_result_metadata(
                    manifest,
                    indexed_at=indexed_at,
                ),
                answer_generator=answer_generator,
                media_resolver=media_resolver,
                top_k=rag_settings.top_k,
            )
            quiz_generator = QuizGenerator(HuggingFaceQuizTextGenerator(answer_generator))

            if _bool_env("AI_STARTUP_SMOKE", True):
                self._smoke_inference(answer_generator, condition_extractor)

            self.qa_service = qa_service
            self.qa_summary_service = qa_summary_service
            self._qa_summary_text_generator = qa_summary_text_generator
            self.recommendation_service = recommendation_service
            self.quiz_generator = quiz_generator
            self._condition_extractor = condition_extractor
        except Exception as exc:
            with self._lock:
                self._state = "failed"
                self._message = f"런타임 준비 실패: {type(exc).__name__}"
            raise
        with self._lock:
            self._state = "ready"
            self._message = "Qwen·LoRA·Hybrid RAG 런타임 준비 완료"

    @staticmethod
    def _smoke_inference(answer_generator, condition_extractor) -> None:
        """Exercise both generation models once; no generated text is persisted."""

        answer_generator.generate_structured(
            [{"role": "user", "content": "한 글자로 예라고 답하세요."}],
            max_new_tokens=4,
        )
        condition_extractor.extract(
            SurveyResponse(
                session_id="runpod-readiness",
                answers=[
                    SurveyAnswer(
                        question_id="purpose_environment",
                        question="사용 목적은 무엇인가요?",
                        answer="Raspberry Pi로 홈 서버를 만들고 싶습니다.",
                    )
                ],
            )
        )

    def execute(
        self,
        kind: JobKind,
        payload: Mapping[str, object],
        *,
        job_id: str,
        cancel_requested: Callable[[], bool],
    ) -> dict[str, object]:
        ready, _ = self.readiness
        if (
            not ready
            or self.qa_service is None
            or self.qa_summary_service is None
            or self.recommendation_service is None
            or self.quiz_generator is None
        ):
            raise RuntimeNotReadyError("RunPod runtime is not ready")

        if kind == "qa":
            request = QaPayload.model_validate(payload)
            response = self.qa_service.answer(
                request_id=job_id,
                question=request.question,
                retrieval_mode=request.retrieval_mode,
                trace=request.trace,
                cancel_requested=cancel_requested,
            )
            try:
                summary = QaSummaryService(
                    self._qa_summary_text_generator,
                    cancel_requested=cancel_requested,
                ).generate(request.question, response)
            except GenerationCancelled:
                raise
            except Exception:
                logger.exception("Q&A summary generation failed; preserving the original response")
                summary = QaSummaryResult(
                    question_title=None,
                    question_title_status="generation_failed",
                    answer_summary=None,
                    answer_summary_status=(
                        "generation_failed" if response.status == "answered" else "not_applicable"
                    ),
                )
            return {
                "response": response.model_dump(mode="json"),
                "summary": summary.model_dump(mode="json"),
            }
        elif kind == "recommendation":
            form_payload = dict(payload)
            form_payload.setdefault("request_id", job_id)
            form = RecommendationFormInput.model_validate(form_payload)
            result = self.recommendation_service.answer_form(
                form=form,
                trace=True,
                cancel_requested=cancel_requested,
            )
        else:
            request = QuizPayload.model_validate(payload)
            response = ChatResponse.model_validate(request.response)
            result = self.quiz_generator.generate_from_chat_response(
                response,
                max_questions=request.max_questions,
                cancel_requested=cancel_requested,
            )
        return result.model_dump(mode="json")


__all__ = ["PiCareRuntime", "RuntimeNotReadyError"]
