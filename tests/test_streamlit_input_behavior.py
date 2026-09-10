"""Real Streamlit form execution with an explicitly stubbed service boundary."""
from unittest.mock import Mock
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from src.contracts.input_limits import INPUT_LENGTH_HINT, MAX_INPUT_CHARS
from streamlit_app import runtime


def page(name):
    st.cache_resource.clear()
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "streamlit_app/app.py"), default_timeout=15)
    app.query_params["page"] = name
    app.run()
    assert not app.exception
    return app


@pytest.mark.parametrize("name", ["recommend", "qa"])
def test_visible_length_hint_and_widget_maximum(name):
    app = page(name)
    assert any(INPUT_LENGTH_HINT in item.value for item in app.caption)
    assert app.text_area[0].proto.max_chars == MAX_INPUT_CHARS


@pytest.mark.parametrize("text", ["홈 서버를 만들고 싶어요", "설명을 읽으며 홈 서버를 준비합니다. " * 200], ids=["short", "long"])
def test_form_submits_without_optional_selections(monkeypatch, text):
    service = Mock()
    service.answer_form.return_value = None
    monkeypatch.setattr(runtime, "build_recommendation_service", lambda root: service)
    app = page("recommend")
    app.text_area[0].set_value(text)
    next(button for button in app.button if "추천 결과 보기" in button.label).click().run()
    assert not app.exception
    assert not app.error
    service.answer_form.assert_called_once()
    form = service.answer_form.call_args.kwargs["form"]
    assert form.free_text == text.strip()
    assert len(form.to_survey().answers) == 1
    assert form.wireless_required is None
    assert form.camera_required is None


@pytest.mark.parametrize("name", ["recommend", "qa"])
def test_blank_input_never_calls_service(monkeypatch, name):
    factory = Mock()
    monkeypatch.setattr(runtime, "build_recommendation_service", factory)
    monkeypatch.setattr(runtime, "build_qa_service", factory)
    app = page(name)
    app.text_area[0].set_value("  ")
    next(button for button in app.button if "추천 결과 보기" in button.label or "보내기" in button.label).click().run()
    assert not app.exception
    factory.assert_not_called()
    assert any(INPUT_LENGTH_HINT in item.value for item in [*app.error, *app.warning])
