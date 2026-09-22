"""PiCare Streamlit UI connected to the shared recommendation and RAG services."""

from __future__ import annotations

import html
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from src.condition_extraction.ui_input import RecommendationFormInput
from src.contracts import ChatResponse, MediaItem
from src.contracts.input_limits import MAX_INPUT_CHARS, INPUT_LENGTH_HINT
from src.presentation import CitationPresenter, load_citation_presenter
from src.rag import RagSettings
from streamlit_app.runtime import (
    build_qa_service,
    build_recommendation_service,
    check_runtime_readiness,
)
from streamlit_app.streaming import iter_text_chunks
from streamlit_app.styles import APP_CSS


st.set_page_config(
    page_title="PiCare | Raspberry Pi 공식 문서 기반 도우미",
    page_icon="🍓",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(APP_CSS, unsafe_allow_html=True)


RUNTIME_READINESS = check_runtime_readiness(ROOT)


@st.cache_resource(show_spinner=False)
def citation_presenter() -> CitationPresenter | None:
    """출처 표시 사전이 없어도 QA 자체는 계속 동작하게 한다."""

    try:
        return load_citation_presenter(RagSettings.from_env(ROOT).manifest_path)
    except Exception:
        return None


@st.cache_resource(show_spinner=False)
def qa_chat_service():
    """Keep one real QA service for the Streamlit process."""

    return build_qa_service(ROOT)


@st.cache_resource(show_spinner=False)
def recommendation_service():
    """Keep the model, catalog, and retriever assembly across Streamlit reruns."""

    return build_recommendation_service(ROOT)


def current_page() -> str:
    """Return a supported top-level page from the URL query string."""

    page = st.query_params.get("page", "about")
    page = page if page in {"about", "recommend", "qa", "lab"} else "about"
    previous_page = st.session_state.get("active_page")
    if previous_page is not None and previous_page != page:
        for key in (
            "recommendation_response",
            "qa_response",
            "qa_question",
            "qa_history",
        ):
            st.session_state.pop(key, None)
    st.session_state.active_page = page
    return page


def render_header(page: str) -> str:
    """Render functional Streamlit navigation for the live service."""

    page_labels = {
        "about": "서비스 소개",
        "recommend": "제품 추천",
        "qa": "질의응답",
        "lab": "명령어 실험실",
    }
    with st.container(key="topbar"):
        brand, navigation_area, _ = st.columns([1, 1.5, 1], vertical_alignment="center")
        with brand:
            st.markdown('<div class="picare-brand">🍓PiCare</div>', unsafe_allow_html=True)
        with navigation_area:
            with st.container(key="top_navigation"):
                navigation = st.columns(len(page_labels), gap="small", vertical_alignment="center")
                for column, (target, label) in zip(navigation, page_labels.items(), strict=True):
                    with column:
                        if st.button(
                            label,
                            key=f"top_navigation_{target}",
                            type="primary" if target == page else "secondary",
                            use_container_width=False,
                        ):
                            st.query_params["page"] = target
                            st.rerun()
    st.markdown('<div class="picare-header-line"></div>', unsafe_allow_html=True)
    return page


def render_hero(title: str, highlighted: str | None, subtitle: str) -> None:
    """Render a consistent page heading."""

    safe_title = html.escape(title)
    if highlighted:
        safe_title = safe_title.replace(
            html.escape(highlighted), f"<em>{html.escape(highlighted)}</em>"
        )
    st.markdown(
        f"""
        <div class="hero">
          <h1>{safe_title}</h1>
          <p>{html.escape(subtitle)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_title(title: str, pill: str | None = None) -> None:
    """Render a section heading and optional status pill."""

    badge = f'<span class="status-pill">{html.escape(pill)}</span>' if pill else ""
    st.markdown(
        f'<div class="section-title"><h2>{html.escape(title)}</h2>{badge}</div>',
        unsafe_allow_html=True,
    )


def _value(item, name: str, default=""):
    """Read a field from a Pydantic contract or a legacy mapping."""

    return getattr(item, name, item.get(name, default) if isinstance(item, dict) else default)


def render_sources(sources, *, preferred_use_case: str | None = None) -> None:
    """Render citation metadata without asking an LLM to generate it."""

    if not sources:
        st.info("표시할 공식 검색 근거가 없습니다. 출처를 추측하지 않습니다.")
        return
    presenter = citation_presenter()
    for source in sources:
        citation = _value(source, "citation_id")
        if presenter is not None:
            display = presenter.present(source, preferred_use_case=preferred_use_case)
            citation_text = f"{html.escape(display.citation_id)} · "
            title = display.document_label
            section = display.section_label
            tags = " · ".join(display.tags) if display.tags else "없음"
        else:
            citation_text = f"{html.escape(citation)} · " if citation else ""
            title = str(_value(source, "title"))
            section = str(_value(source, "section")).rsplit(" > ", maxsplit=1)[-1]
            tags = "없음"
        url = str(_value(source, "source_url", _value(source, "url")))
        st.markdown(
            f"""
            <div class="source-card">
              <div class="source-icon">📄</div>
              <div>
                <div class="source-title">{citation_text}{html.escape(title)}</div>
                <div class="source-meta">섹션: {html.escape(section)}</div>
                <div class="source-meta">태그: {html.escape(tags)}</div>
              </div>
              <a class="source-link" href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer" aria-label="공식 문서 열기">↗</a>
            </div>
            """,
            unsafe_allow_html=True,
        )


def product_card(product) -> str:
    """Render one server-validated ProductRecommendation contract."""

    name = str(product.product_model)
    image = str(product.image_url) if product.image_url else ""
    limitations = " ".join(product.limitations) or "추가 유의사항 없음"
    citation_ids = ", ".join(product.citation_ids)
    return f"""
        <div class="product-card">
          <div class="product-card-header"><div class="product-name">{html.escape(name)}</div></div>
          <div class="product-card-body">
            {f'<img src="{html.escape(image, quote=True)}" alt="{html.escape(name)}" class="product-image" />' if image else ''}
            <div class="product-reason">{html.escape(product.recommendation)}</div>
            <div class="product-limitations">{html.escape(limitations)}</div>
            <div class="product-card-footer">
              <a class="product-link" href="{html.escape(str(product.product_url), quote=True)}" target="_blank" rel="noopener noreferrer">자세히 보기 <span>→</span></a>
              <span class="product-badge tone-red">공식 근거 {html.escape(citation_ids)}</span>
            </div>
          </div>
        </div>
        """


def optional_boolean_label(value: bool | None) -> str:
    return "선택 안 함" if value is None else "예" if value else "아니요"


def render_recommendation_page() -> None:
    """Render the product form and the real recommendation service response."""

    render_hero(
        "나에게 맞는 Raspberry Pi 찾기",
        "Raspberry Pi",
        "사용 목적과 필요한 기능을 선택하면 공식 사양을 바탕으로 후보를 비교해 드려요.",
    )

    with st.form("recommendation_form"):
        purpose = st.text_area(
            "어디에 사용하실 건가요?",
            max_chars=MAX_INPUT_CHARS, height=160, help=INPUT_LENGTH_HINT,
            value=st.session_state.get("purpose", "모니터 없이 홈 서버로 사용하고 싶어요."),
            placeholder="예: 모니터 없이 홈 서버로 사용하고 싶어요.",
        )
        st.caption(f"{INPUT_LENGTH_HINT} · 사용 목적과 환경을 자유롭게 적어주세요.")
        st.markdown("**추가 조건 (선택)**")
        st.caption("선택하지 않아도 추천할 수 있어요. 직접 선택한 항목만 입력한 글보다 우선합니다.")
        c1, c2, c3, c4, c5, c6 = st.columns([1, 1, 1, 1, 1, 1])
        with c1:
            user_level = st.selectbox("사용자 수준", ["선택 안 함", "입문자", "중급자", "고급자"])
        with c2:
            performance = st.selectbox("성능 우선순위", ["선택 안 함", "낮음", "보통", "높음"])
        with c3:
            wifi = st.selectbox("Wi-Fi 필요", [None, True, False], format_func=optional_boolean_label)
        with c4:
            camera = st.selectbox("카메라 사용", [None, True, False], format_func=optional_boolean_label)
        with c5:
            gpio = st.selectbox("GPIO 사용", [None, True, False], format_func=optional_boolean_label)
        with c6:
            monitor_absent = st.selectbox("모니터 없음", [None, True, False], format_func=optional_boolean_label)
        submitted = st.form_submit_button("추천 결과 보기  ✨", use_container_width=True)

    if submitted:
        if not 1 <= len(purpose.strip()) <= MAX_INPUT_CHARS:
            st.error(INPUT_LENGTH_HINT)
            return
        form = RecommendationFormInput.from_widget_values(
            request_id=str(uuid.uuid4()),
            free_text=purpose.strip(),
            user_level_label=user_level,
            performance_priority_label=performance,
            wireless_required=wifi,
            camera_required=camera,
            gpio_required=gpio,
            monitor_absent=monitor_absent,
        )
        try:
            with st.status("추천을 준비하고 있습니다…", expanded=True) as progress:
                progress.write("입력한 목적과 필수 조건을 확인하고 있습니다.")
                progress.write("조건 JSON → 제품 catalog → 공식 문서 근거 순서로 검증합니다.")
                st.session_state.recommendation_response = recommendation_service().answer_form(
                    form=form,
                    trace=True,
                )
                progress.write("추천 제품과 인용 근거의 일치를 확인했습니다.")
                progress.update(label="추천 답변 준비 완료", state="complete", expanded=False)
            st.session_state.purpose = purpose
        except Exception as exc:
            st.error(f"제품 추천 런타임을 준비하지 못했습니다: {exc}")

    response: ChatResponse | None = st.session_state.get("recommendation_response")
    if response is None:
        if not RUNTIME_READINESS.ready:
            st.warning(RUNTIME_READINESS.message)
        return

    section_title(f"추천 제품 {len(response.products)}개", response.status)
    if response.products:
        cards = "".join(product_card(product).strip() for product in response.products)
        st.markdown(f'<div class="product-grid">{cards}</div>', unsafe_allow_html=True)

    with st.container(key="recommendation_evidence"):
        with st.expander("추천 근거", expanded=False):
            render_sources(
                response.citations,
                preferred_use_case=response.conditions.use_case if response.conditions else None,
            )
    render_citation_media(response.media, grid_images=True)
    render_answer(response, stream_key="recommendation")
    if response.conditions is not None:
        with st.expander("🧩 검증된 조건 JSON", expanded=False):
            st.json(response.conditions.model_dump(mode="json"))


def answer_label_class(status: str) -> str:
    """Return a visual class for answer status labels."""

    blocked = {
        "error",
        "insufficient_evidence",
        "needs_clarification",
        "out_of_scope",
        "safety_blocked",
    }
    return "blocked" if status in blocked else ""


def render_citation_media(
    media_items: list[MediaItem],
    *,
    grid_images: bool = False,
    show_title: bool = True,
    container_key_prefix: str = "citation_media",
) -> None:
    """Render only guide media already resolved from final citations by the server."""

    if not media_items:
        return
    with st.container(key=f"{container_key_prefix}_card"):
        if show_title:
            section_title("인용 근거와 연결된 이미지·영상")

        images = [item for item in media_items if item.media_type == "image"]
        videos = [item for item in media_items if item.media_type != "image"]

        def render_media_item(item: MediaItem) -> None:
            if item.media_type == "image":
                st.image(str(item.url), caption=item.alt_text or item.title, use_container_width=True)
            else:
                st.video(str(item.url))
            st.caption(
                f"{item.title} · {item.source_citation_id} · "
                f"{item.attribution} · {item.license}"
            )

        if grid_images and len(images) == 1:
            with st.container(key=f"{container_key_prefix}_single"):
                _, center, _ = st.columns([1, 2, 1])
                with center:
                    render_media_item(images[0])
        elif grid_images and len(images) > 1:
            with st.container(key=f"{container_key_prefix}_grid"):
                for start in range(0, len(images), 2):
                    columns = st.columns(2, gap="medium")
                    for column, item in zip(columns, images[start : start + 2], strict=False):
                        with column:
                            render_media_item(item)
        else:
            for item in images:
                render_media_item(item)

        for item in videos:
            render_media_item(item)


def render_answer(response: ChatResponse, *, stream_key: str) -> None:
    """Render a validated answer once with a typewriter-style stream."""

    status_labels = {
        "answered": "근거 확인 완료",
        "needs_clarification": "추가 정보 필요",
        "insufficient_evidence": "근거 부족",
        "out_of_scope": "답변 범위 외",
        "safety_blocked": "안전 정책으로 보류",
        "error": "실행 오류",
    }
    status = response.status
    st.markdown(
        f'<div class="answer-label {answer_label_class(status)}">● {html.escape(status_labels[status])}</div>',
        unsafe_allow_html=True,
    )
    streamed_request_key = f"{stream_key}_streamed_request_id"
    if st.session_state.get(streamed_request_key) != response.request_id:
        st.write_stream(iter_text_chunks(response.answer))
        st.session_state[streamed_request_key] = response.request_id
    else:
        st.markdown(response.answer)
    for question in response.clarification_questions:
        st.info(question)
    if response.warnings:
        with st.expander("실행 추적 정보", expanded=False):
            st.code("\n".join(response.warnings), language=None)


def submit_qa(question: str) -> None:
    """Run the real document-grounded chain and store the latest UI response."""

    clean_question = question.strip()
    st.session_state.qa_question = clean_question
    st.session_state.qa_response = qa_chat_service().answer(
        request_id=str(uuid.uuid4()),
        question=clean_question,
        retrieval_mode="hybrid",
        trace=True,
    )


def render_qa_page() -> None:
    """Render the document-grounded QA screen."""

    render_hero(
        "무엇이 궁금하신가요?",
        None,
        "사용법, 문제 해결, 공식 지원 절차를 문서 근거와 함께 알려드려요.",
    )

    categories = st.columns(3)
    for column, icon, label in zip(
        categories, ["💻", "🔧", "🛡️"], ["설치·사용법", "문제 해결", "A/S·리콜"], strict=True
    ):
        with column:
            st.markdown(f'<div class="qa-category"><span style="font-size:1.5rem">{icon}</span>&nbsp;&nbsp;{label}</div>', unsafe_allow_html=True)

    response: ChatResponse | None = st.session_state.get("qa_response")
    if response is not None:
        st.markdown(
            f'<div class="user-bubble">{html.escape(st.session_state.qa_question)}</div>',
            unsafe_allow_html=True,
        )
        left, right = st.columns([1.35, 1], gap="large")
        with left:
            with st.container(key="qa_answer_bubble_0"):
                st.markdown('<div class="qa-answer-speaker">🤖 PiCare</div>', unsafe_allow_html=True)
                render_answer(response, stream_key="qa")
            if response.media:
                with st.expander("인용 근거와 연결된 이미지·영상", expanded=False):
                    render_citation_media(
                        response.media,
                        grid_images=True,
                        show_title=False,
                        container_key_prefix="qa_media_0",
                    )
        with right:
            with st.container(key="qa_sources_panel_0"):
                section_title(f"공식 문서 출처 {len(response.citations)}건")
                render_sources(response.citations)
    elif not RUNTIME_READINESS.ready:
        st.warning(RUNTIME_READINESS.message)

    st.markdown("---")
    if st.session_state.pop("clear_qa_input", False):
        st.session_state.qa_input = ""
    if "lab_qa_prefill" in st.session_state:
        st.session_state.qa_input = st.session_state.pop("lab_qa_prefill")
    with st.form("qa_form", clear_on_submit=False):
        c1, c2 = st.columns([8, 1.2])
        with c1:
            question = st.text_area(
                "질문",
                max_chars=MAX_INPUT_CHARS, help=INPUT_LENGTH_HINT,
                placeholder="질문을 입력하세요",
                label_visibility="collapsed",
                key="qa_input",
            )
        with c2:
            sent = st.form_submit_button("✈ 보내기", use_container_width=True)
        st.caption(INPUT_LENGTH_HINT)
        st.caption("🛡 입력한 내용은 명령으로 실행되지 않습니다. 검색 근거가 없으면 답변을 보류합니다.")
    if sent:
        if not 1 <= len(question.strip()) <= MAX_INPUT_CHARS:
            st.warning(INPUT_LENGTH_HINT)
        else:
            try:
                with st.status("공식 근거를 확인하고 있습니다…", expanded=True) as progress:
                    progress.write("질문 범위와 안전 정책을 확인하고 있습니다.")
                    progress.write("공식 문서에서 관련 청크를 검색하고 있습니다.")
                    submit_qa(question)
                    progress.write("답변의 핵심 주장과 인용 근거를 검증했습니다.")
                    progress.update(label="근거 기반 답변 준비 완료", state="complete", expanded=False)
                st.session_state.clear_qa_input = True
                st.rerun()
            except Exception as exc:
                st.error(f"QA 런타임을 준비하지 못했습니다: {exc}")


def render_about_page() -> None:
    """Render a readable project introduction and clear paths into the service."""

    render_hero(
        "Raspberry Pi @@@@@@@@@@@@@@@ 시작을 위한 실용 가이드",
        "실용 가이드",
        "제품 선택부터 설치와 문제 해결까지, Raspberry Pi 공식 문서를 바탕으로 필요한 정보를 안내합니다.",
    )
    cards = (
        (
            "🧩",
            "맞춤형 제품 추천",
            "사용 목적과 환경에 맞는 제품·준비 항목 안내",
            "제품 추천 시작하기",
            "?page=recommend",
        ),
        (
            "🔎",
            "사용법·문제 해결 Q&A",
            "공식 문서 기반 사용법·문제 해결 안내",
            "질문 바로 하기",
            "?page=qa",
        ),
    )
    card_markup = "".join(
        f'<div class="about-card" style="width:335px;height:180px">'
        f'<div class="about-card-title"><span class="about-card-icon">{icon}</span>'
        f'<span>{title}</span></div>'
        f'<div class="about-card-body"><p>{text}</p>'
        f'<a class="about-card-action" href="{action_url}">{action_label}<span>→</span></a>'
        f'</div></div>'
        for icon, title, text, action_label, action_url in cards
    )
    st.markdown(
        f'<div class="about-card-grid" style="grid-template-columns:335px 335px">{card_markup}</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="about-abstention">
          <div class="about-abstention-icon">🛡️</div>
          <div>
            <strong>확인할 수 없으면 보류</strong>
            <p>근거가 부족한 내용은 추측하지 않고 추가 확인 정보 안내</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not RUNTIME_READINESS.ready:
        st.info("화면은 열려 있지만, 답변을 만들려면 검색 색인과 모델 실행 환경이 준비되어야 합니다.")
        with st.expander("실행 환경 준비 상태 보기", expanded=False):
            st.code(RUNTIME_READINESS.message, language=None)

    st.markdown(
        """
        <div class="about-source">
          대표 출처: <a href="https://www.raspberrypi.com/documentation/" target="_blank" rel="noopener noreferrer">Raspberry Pi Documentation ↗</a>
        </div>
        """,
        unsafe_allow_html=True,
    )


page = render_header(current_page())
if page == "recommend":
    render_recommendation_page()
elif page == "qa":
    render_qa_page()
elif page == "lab":
    from streamlit_app.command_lab import render_command_lab_page
    render_command_lab_page()
else:
    render_about_page()
