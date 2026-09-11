"""검수된 카탈로그 사실만으로 설명 가능한 제품 필터링·순위를 계산한다."""

from __future__ import annotations

from src.contracts import ConditionPayload

from .schema import (
    GpioHeader,
    PerformanceTier,
    ProductCatalog,
    ProductRecord,
    RecommendationCandidate,
    RecommendationDecision,
    RecommendationStatus,
)


USE_CASE_LABELS = {
    "education_coding": "코딩 교육",
    "desktop_computing": "데스크톱 컴퓨팅",
    "home_server": "홈 서버",
    "camera_monitoring": "카메라 모니터링",
    "smart_farm_monitoring": "스마트팜 모니터링",
    "headless_remote_management": "모니터 없는 원격 관리",
    "gpio_iot": "GPIO·IoT",
}
TASK_LABELS = {
    "desktop_programming": "데스크톱 프로그래밍",
    "os_installation": "운영체제 설치",
    "system_configuration": "시스템 설정",
    "remote_access": "원격 접속",
    "camera_setup": "카메라 설정",
    "gpio_setup": "GPIO 설정",
    "sensor_monitoring": "센서 모니터링",
    "server_operation": "서버 운영",
    "troubleshooting": "문제 해결",
    "support_recall": "지원·리콜 확인",
}


class ProductRecommender:
    """필수 조건으로 거른 뒤 가중치 점수로 최대 3개 제품을 추천한다."""

    def __init__(self, catalog: ProductCatalog, *, max_candidates: int = 3) -> None:
        """검증된 카탈로그와 반환할 최대 후보 수를 설정한다."""

        if not 1 <= max_candidates <= 3:
            raise ValueError("max_candidates는 1~3이어야 합니다.")
        self.catalog = catalog
        self.max_candidates = max_candidates

    def recommend(self, conditions: ConditionPayload) -> RecommendationDecision:
        """공통 조건을 받아 범위·명확성 확인 후 제품 후보를 계산한다."""

        if conditions.intent not in {"product_recommendation", "product_comparison"}:
            return self._decision(RecommendationStatus.OUT_OF_SCOPE, conditions)
        if conditions.needs_clarification:
            return self._decision(
                RecommendationStatus.NEEDS_CLARIFICATION,
                conditions,
                clarification_questions=conditions.clarification_questions,
            )
        if conditions.use_case is None and conditions.product_models is None:
            return self._decision(
                RecommendationStatus.NEEDS_CLARIFICATION,
                conditions,
                clarification_questions=["가장 중요한 사용 목적이 무엇인가요?"],
            )

        ranked = [
            self._score(product, conditions)
            for product in self.catalog.products
            if not self._hard_failures(product, conditions)
        ]
        ranked.sort(key=lambda item: (-item.score, item.product_id))
        candidates = ranked[: self.max_candidates]
        if not candidates:
            return self._decision(
                RecommendationStatus.NO_MATCH,
                conditions,
                clarification_questions=[
                    "필수 조건 중 완화할 수 있는 항목이 있나요?",
                    "사용하려는 주변기기와 연결 방식을 더 알려 주세요.",
                ],
            )
        return self._decision(
            RecommendationStatus.RECOMMENDED,
            conditions,
            candidates=candidates,
        )

    def _decision(
        self,
        status: RecommendationStatus,
        conditions: ConditionPayload,
        *,
        candidates: list[RecommendationCandidate] | None = None,
        clarification_questions: list[str] | None = None,
    ) -> RecommendationDecision:
        """모든 추천 분기에서 동일한 형식의 결정 객체를 생성한다."""

        return RecommendationDecision(
            status=status,
            conditions=conditions,
            candidates=candidates or [],
            clarification_questions=clarification_questions or [],
            catalog_version=self.catalog.catalog_version,
        )

    @staticmethod
    def _accepted_product_names(product: ProductRecord) -> set[str]:
        """제품 ID·공식명·별칭을 대소문자 무관 비교 집합으로 만든다."""

        return {
            product.product_id.casefold(),
            product.name.casefold(),
            *(alias.casefold() for alias in product.aliases),
        }

    @classmethod
    def _hard_failures(
        cls, product: ProductRecord, conditions: ConditionPayload
    ) -> list[str]:
        """필수 기능을 만족하지 않는 이유를 모아 제품 제외 여부를 정한다."""

        failures: list[str] = []
        caps = product.capabilities
        if not product.is_current:
            failures.append("current product only")
        if conditions.product_models:
            requested = {name.casefold() for name in conditions.product_models}
            if not requested.intersection(cls._accepted_product_names(product)):
                failures.append("explicit product mismatch")
        # 일반 추천에서는 카탈로그에서 사람이 승인한 용도 밖의 제품을 후보에
        # 섞지 않는다. 비교 요청은 사용자가 지정한 제품의 장단점을 그대로
        # 보여줘야 하므로 이 제한을 적용하지 않는다.
        if (
            conditions.intent == "product_recommendation"
            and conditions.use_case is not None
            and conditions.use_case not in product.recommendation_profile.recommended_use_cases
        ):
            failures.append("reviewed use case")
        if conditions.ethernet_required is True and not caps.ethernet:
            failures.append("ethernet")
        if conditions.min_camera_connectors is not None and caps.camera_connector_count < conditions.min_camera_connectors:
            failures.append("camera connector count")
        if conditions.min_display_outputs is not None and caps.display_output_count < conditions.min_display_outputs:
            failures.append("display output count")
        if conditions.wireless_required is True and not caps.wireless:
            failures.append("wireless")
        if conditions.camera_required is True and caps.camera_connector_count == 0:
            failures.append("camera connector")
        if conditions.gpio_required is True and caps.gpio_header is GpioHeader.NONE:
            failures.append("GPIO")
        if conditions.monitor_available is True and caps.display_output_count == 0:
            failures.append("display output")
        if conditions.remote_access_required is True and not (caps.wireless or caps.ethernet):
            failures.append("network for remote access")
        return failures

    @classmethod
    def _score(
        cls, product: ProductRecord, conditions: ConditionPayload
    ) -> RecommendationCandidate:
        """목적·작업·수준·성능·기능 일치도를 점수와 한국어 이유로 만든다."""

        profile = product.recommendation_profile
        matched: list[str] = []
        score = 0

        if conditions.product_models:
            requested = {name.casefold() for name in conditions.product_models}
            if requested.intersection(cls._accepted_product_names(product)):
                score += 50
                matched.append("사용자가 지정한 제품")

        if conditions.use_case in profile.recommended_use_cases:
            score += 35
            matched.append(
                f"사용 목적: {USE_CASE_LABELS.get(conditions.use_case, conditions.use_case)}"
            )
        if conditions.task in profile.recommended_tasks:
            score += 20
            matched.append(f"작업: {TASK_LABELS.get(conditions.task, conditions.task)}")
        if conditions.user_level == "beginner" and profile.beginner_friendly:
            score += 15
            matched.append("입문자 친화성")

        performance_points = {
            "high": {
                PerformanceTier.HIGH: 20,
                PerformanceTier.MEDIUM: 8,
                PerformanceTier.LOW: 0,
            },
            "medium": {
                PerformanceTier.HIGH: 10,
                PerformanceTier.MEDIUM: 16,
                PerformanceTier.LOW: 6,
            },
            "low": {
                PerformanceTier.HIGH: 4,
                PerformanceTier.MEDIUM: 8,
                PerformanceTier.LOW: 12,
            },
        }
        if conditions.performance_priority is not None:
            points = performance_points[conditions.performance_priority][
                profile.performance_tier
            ]
            score += points
            if points:
                matched.append("성능 우선순위")

        for required, available, label in (
            (conditions.wireless_required, product.capabilities.wireless, "Wi-Fi"),
            (
                conditions.camera_required,
                product.capabilities.camera_connector_count > 0,
                "카메라 연결",
            ),
            (
                conditions.gpio_required,
                product.capabilities.gpio_header is not GpioHeader.NONE,
                "GPIO",
            ),
            (
                conditions.monitor_available,
                product.capabilities.display_output_count > 0,
                "모니터 출력",
            ),
            (
                conditions.remote_access_required,
                product.capabilities.wireless or product.capabilities.ethernet,
                "원격 접속용 네트워크",
            ),
        ):
            if required is True and available:
                score += 8
                matched.append(label)

        if conditions.monitor_available is False:
            matched.append("모니터 없는 환경")

        for use_case in sorted(set(conditions.additional_use_cases) - {conditions.use_case}):
            label = USE_CASE_LABELS.get(use_case, use_case)
            if use_case in profile.recommended_use_cases:
                score += 10
                matched.append(f"추가 사용 목적: {label}")
        for task in sorted(set(conditions.additional_tasks) - {conditions.task}):
            if task in profile.recommended_tasks:
                score += 5
                matched.append(f"추가 작업: {TASK_LABELS.get(task, task)}")
        if conditions.ethernet_required is True:
            matched.append("유선 LAN")
        tradeoffs = list(product.caveats)
        tradeoffs.extend(f"충족 여부 확인 필요: {item}" for item in conditions.unverified_requirements)
        for use_case in sorted(set(conditions.additional_use_cases) - {conditions.use_case}):
            if use_case not in profile.recommended_use_cases:
                tradeoffs.append(f"추가 용도 검토 필요: {USE_CASE_LABELS.get(use_case, use_case)}")
        if (
            conditions.gpio_required is True
            and product.capabilities.gpio_header is GpioHeader.UNPOPULATED
        ):
            tradeoffs.append(
                "GPIO 핀 헤더가 장착되지 않은 변형은 납땜 또는 헤더가 필요합니다."
            )

        return RecommendationCandidate(
            product_id=product.product_id,
            name=product.name,
            score=score,
            matched_conditions=matched,
            tradeoffs=tradeoffs,
            required_accessories=product.required_accessories,
            conditional_accessories=product.conditional_accessories,
            evidence_by_field=product.evidence_by_field,
            evidence_document_ids=product.document_ids,
            product_url=product.product_url,
            image_url=product.image_url,
            display=product.display,
        )
