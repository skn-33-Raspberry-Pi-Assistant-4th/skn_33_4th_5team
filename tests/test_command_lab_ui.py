from pathlib import Path
from streamlit.testing.v1 import AppTest


def test_lab_edit_drawer_and_qa_handoff():
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "streamlit_app/app.py"), default_timeout=20)
    app.query_params["page"] = "lab"
    app.run()
    assert not app.exception
    app.selectbox(key="lab_template").set_value("cmd-remote-access-004").run()
    app.text_input(key="lab_cmd-remote-access-004_part-02").set_value("pi@192.168.0.20").run()
    assert not app.exception
    assert any(c.value == "ssh pi@192.168.0.20" for c in app.code)
    next(b for b in app.button if b.label == "현재 실험을 임시 서랍에 담기").click().run()
    assert app.session_state["lab_drawer"][0]["command_snapshot"] == "ssh pi@192.168.0.20"
    next(b for b in app.button if b.label == "이 명령을 Q&A에서 질문하기").click().run()
    assert not app.exception
    assert "ssh pi@192.168.0.20" in app.text_area[0].value


def test_lab_analyze_changes_selected_template():
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "streamlit_app/app.py"), default_timeout=20)
    app.query_params["page"] = "lab"
    app.run()
    app.text_input[0].set_value("ssh demo@raspberrypi.local")
    next(b for b in app.button if b.label == "명령어 분석").click().run()
    assert not app.exception
    assert app.selectbox(key="lab_template").value == "cmd-remote-access-004"
    assert any(c.value == "ssh demo@raspberrypi.local" for c in app.code)
