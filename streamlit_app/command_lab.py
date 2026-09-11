"""Thin command-lab UI; reusable service lives in src.services."""
import json
import streamlit as st

from src.services.command_lab_service import CommandLabError, CommandLabService


def render_command_lab_page():
    st.title("명령어 실험실")
    st.caption("명령어를 나누어 이해하고 입력값을 바꿔 보세요. 명령은 실행되지 않습니다.")
    try:
        service = CommandLabService()
    except (OSError, ValueError) as exc:
        st.error(f"실험실 데이터 준비가 필요합니다: {exc}")
        return
    audit = service.audit()
    st.caption(f"검수 완료 {audit['approved']}개 · 검수 대기 {audit['draft']}개")
    if audit["errors"]:
        st.warning("일부 명령의 공식 근거가 일치하지 않아 목록에서 제외했습니다.")
    templates = service.list_templates()
    if not templates:
        st.info("제공 가능한 검수 완료 명령어가 없습니다.")
        return
    by_id = {t["template_id"]: t for t in templates}
    with st.form("lab_analyze"):
        command = st.text_input("분석할 명령어", placeholder="ssh learner@raspberrypi.local", max_chars=2000)
        analyze = st.form_submit_button("명령어 분석")
    if analyze:
        try:
            result = service.analyze(command)
            st.session_state.lab_template = result["template_id"]
            for part in result["parts"]:
                if part["editable"]:
                    st.session_state[f"lab_{result['template_id']}_{part['part_id']}"] = result["values"].get(part["part_id"], part["value"])
        except CommandLabError as exc:
            st.warning(str(exc))
    template_id = st.selectbox("검수된 명령어", list(by_id),
                               format_func=lambda k: by_id[k]["canonical_command"], key="lab_template")
    item = by_id[template_id]
    product_id = st.selectbox("내 제품 연결", [None, *service.products],
                              format_func=lambda k: "선택 안 함" if k is None else service.products[k]["name"])
    values = {}
    for part in item["parts"]:
        if part["editable"]:
            values[part["part_id"]] = st.text_input(part["description_ko"], value=part["value"],
                max_chars=160, key=f"lab_{template_id}_{part['part_id']}")
    try:
        result = service.compose(template_id, values, product_id=product_id)
    except CommandLabError as exc:
        st.warning(str(exc))
        return
    st.subheader("재조합 결과")
    st.code(result["command"], language="bash")
    st.write(result["effect_ko"])
    st.caption(f"사용 위치: {result['execution_context']}")
    st.table([{"구성 요소": p["value"], "역할": p["kind"], "설명": p["description_ko"],
               "수정 가능": "예" if p["editable"] else "아니요"} for p in result["parts"]])
    st.info(result["risk_notice_ko"])
    st.caption(result["limitations_ko"])
    if result["product"]:
        p = result["product"]
        st.link_button(f"{p['name']} 공식 제품 정보", p["product_url"])
        if not p["document_scope_match"]:
            st.warning("선택한 제품이 이 근거 문서의 제품 범위에 명시되어 있지 않습니다.")
        st.caption(p["notice"])
    with st.expander("공식 근거 확인"):
        for c in result["evidence"]:
            st.link_button(f"{c['title']} · {c['section']}", c["source_url"])
            st.text(c["content"])
            st.caption(f"{c['publisher']} · {c['license']} · 문서 버전 {c['document_version']}")
    if st.button("이 명령을 Q&A에서 질문하기"):
        st.session_state.lab_qa_prefill = service.qa_question(template_id, values, product_id=product_id)
        st.query_params["page"] = "qa"
        st.rerun()
    st.link_button("제품 추천으로 이동", "?page=recommend")
    if st.button("현재 실험을 임시 서랍에 담기"):
        payload = service.drawer_payload(template_id, values, product_id=product_id)
        drawer = st.session_state.setdefault("lab_drawer", [])
        if payload not in drawer:
            drawer.append(payload)
        st.success("현재 브라우저 세션에 담았습니다.")
    with st.expander("임시 서랍"):
        st.caption("회원별 영구 저장은 백엔드 연결이 필요합니다. 현재 목록은 브라우저 세션 동안 유지됩니다.")
        for saved in st.session_state.get("lab_drawer", []):
            st.code(saved["command_snapshot"], language="bash")
        st.download_button("서랍 JSON 내려받기", json.dumps(st.session_state.get("lab_drawer", []),
            ensure_ascii=False, indent=2), "command-drawer.json", "application/json")
