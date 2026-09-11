"""CSS used by the PiCare Streamlit application."""

APP_CSS = r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700;800&display=swap');

:root {
  --picare-red: #ed003f;
  --picare-red-dark: #c90036;
  --picare-pink: #fff0f3;
  --picare-ink: #101820;
  --picare-muted: #677180;
  --picare-line: #dde2e8;
  --picare-green: #14822b;
}

html, body, [class*="css"] { font-family: 'Noto Sans KR', sans-serif; }
.stApp { background: #ffffff; color: var(--picare-ink); }
.block-container { max-width: 1440px; padding: 0 2.8rem 4rem; }
[data-testid="stHeader"] { display: none; }
[data-testid="stToolbar"] { display: none; }
#MainMenu, footer { visibility: hidden; }

.st-key-topbar { min-height: 50px; }
.st-key-topbar > [data-testid="stHorizontalBlock"] { min-height: 50px; align-items: center; }
.st-key-topbar .stMarkdown:has(.picare-brand) { height: 38px; }
.picare-brand { height: 38px; display: flex; align-items: center; font-size: 1.5rem; font-weight: 800; color: var(--picare-red); letter-spacing: -.03em; line-height: 1; }
.picare-brand span { font-size: 1.5rem; margin-right: .45rem; }
.st-key-top_navigation { width: 368px; min-width: 368px; margin: 0 auto; }
.st-key-top_navigation [data-testid="stHorizontalBlock"] { flex-wrap: nowrap; gap: 16px; }
.st-key-top_navigation [data-testid="stColumn"] { width: 112px !important; min-width: 112px !important; flex: 0 0 112px !important; }
.st-key-top_navigation_about .stButton > button,
.st-key-top_navigation_recommend .stButton > button,
.st-key-top_navigation_qa .stButton > button { width: 112px; min-width: 112px; min-height: 38px; border-radius: 999px; padding: .45rem .5rem; font-size: .9rem; white-space: nowrap; }
.st-key-top_navigation_about .stButton,
.st-key-top_navigation_recommend .stButton,
.st-key-top_navigation_qa .stButton { display: flex; justify-content: center; }
.st-key-top_navigation_about .stButton > button[kind="secondary"],
.st-key-top_navigation_recommend .stButton > button[kind="secondary"],
.st-key-top_navigation_qa .stButton > button[kind="secondary"] { border: 1px solid rgba(237, 0, 63, .18); color: #8d4355; background: #fff; }
.st-key-top_navigation_about .stButton > button[kind="secondary"]:hover,
.st-key-top_navigation_recommend .stButton > button[kind="secondary"]:hover,
.st-key-top_navigation_qa .stButton > button[kind="secondary"]:hover { border-color: #f4b5c6; color: var(--picare-red-dark); background: var(--picare-pink); transform: translateY(-1px); }
.st-key-top_navigation_about .stButton > button[kind="primary"],
.st-key-top_navigation_recommend .stButton > button[kind="primary"],
.st-key-top_navigation_qa .stButton > button[kind="primary"] { border-color: var(--picare-red); box-shadow: 0 4px 10px rgba(237, 0, 63, .16); }
.picare-header-line { border-bottom: 1px solid var(--picare-line); margin: 0 -2.8rem 1.5rem; }

.hero { text-align: center; padding: .3rem 0 1.3rem; }
.hero h1 { font-size: clamp(2rem, 4vw, 3.1rem); margin: 0; letter-spacing: -.045em; }
.hero h1 em { color: var(--picare-red); font-style: normal; }
.hero p { color: var(--picare-muted); font-size: 1.05rem; margin: .45rem 0 0; }
[data-testid="stForm"] { border: 1px solid var(--picare-line); border-radius: 14px; padding: 1.1rem 1.4rem 1.2rem; background: #fff; box-shadow: 0 3px 14px rgba(22, 31, 40, .035); }
[data-testid="stForm"] [data-testid="stWidgetLabel"] p { color: var(--picare-ink); font-size: .96rem; font-weight: 700; }
[data-testid="stForm"] [data-testid="stCaptionContainer"] { font-size: .9rem; }
[data-testid="stForm"] input, [data-testid="stForm"] [data-baseweb="select"] { font-size: 1rem; }
[data-testid="stTextInput"] [data-baseweb="input"] { border: 1px solid rgba(237, 0, 63, .18); border-radius: 9px; background: #fff; }
[data-testid="stTextInput"] [data-baseweb="input"]:focus-within { border-color: rgba(237, 0, 63, .45); box-shadow: 0 0 0 1px rgba(237, 0, 63, .12); }
.stButton > button, .stFormSubmitButton > button { border-radius: 9px; min-height: 42px; font-weight: 700; }
.stFormSubmitButton > button { background: linear-gradient(135deg, var(--picare-red), #d9003b); border-color: var(--picare-red); color: white; }
.stFormSubmitButton > button:hover { background: var(--picare-red-dark); color: white; border-color: var(--picare-red-dark); }

.section-title { display: flex; align-items: center; gap: .65rem; margin: 1.3rem 0 .75rem; }
.section-title h2 { font-size: 1.25rem; margin: 0; }
.status-pill { background: #e9f8ed; color: var(--picare-green); border-radius: 999px; padding: .25rem .65rem; font-size: .78rem; font-weight: 700; }

.product-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.25rem; align-items: stretch; }
.product-card { display: flex; flex-direction: column; min-height: 405px; height: 100%; box-sizing: border-box; overflow: hidden; border: 1px solid #f3c2ce; border-radius: 20px; background: #fff; box-shadow: 0 12px 32px rgba(38,31,34,.08); }
.product-card-header { display: flex; align-items: center; justify-content: center; min-height: 58px; padding: .65rem 1rem; background: linear-gradient(135deg, var(--picare-red) 0%, var(--picare-red-dark) 100%); color: #fff; text-align: center; }
.product-card-body { display: flex; flex: 1; flex-direction: column; padding: .9rem 1rem 1rem; }
.product-card-footer { display: flex; flex-direction: column; align-items: flex-start; margin-top: auto; width: 100%; }
.product-badge { display: inline-block; width: fit-content; padding: 0; font-size: .84rem; font-weight: 600; }
.product-badge.tone-red { color: #a96073; background: transparent; }
.tone-primary { color: white; background: var(--picare-red); }
.tone-warm { color: #c25b05; background: #fff1e5; border: 1px solid #ffd3ad; }
.tone-green { color: var(--picare-green); background: #eaf7ec; border: 1px solid #cbe9d0; }
.product-name { font-size: 1.16rem; font-weight: 800; line-height: 1.35; }
.product-image { width: 100%; height: 145px; object-fit: contain; }
.spec-grid { display: grid; grid-template-columns: 4.2rem 1fr; gap: .35rem .5rem; font-size: .82rem; margin-top: .55rem; }
.spec-grid strong { color: #333c47; }
.product-reason { margin-top: .8rem; padding: .5rem .65rem; border-radius: 7px; background: var(--picare-pink); color: var(--picare-red-dark); font-size: .94rem; font-weight: 700; line-height: 1.55; text-align: center; }
.product-limitations { margin-top: .7rem; color: var(--picare-muted); font-size: .88rem; line-height: 1.6; }
.product-link { display: flex; align-items: center; justify-content: center; gap: .4rem; width: 100%; box-sizing: border-box; margin: .65rem auto; border: 1px solid #f3c2ce; border-radius: 7px; padding: .48rem .8rem; background: #fff0f3; color: #c90036 !important; font-size: .86rem; font-weight: 800; text-align: center; text-decoration: none !important; transition: background .16s ease, color .16s ease; }
.product-link span { font-size: 1rem; transition: transform .16s ease; }
.product-link:hover { background: #ed003f; color: #fff !important; }
.product-link:hover span { transform: translateX(3px); }
.st-key-recommendation_evidence { margin-top: .55rem; }
.st-key-citation_media_card, [class*="st-key-qa_media_"][class*="_card"] { margin-top: 1rem; border: 1px solid var(--picare-line); border-radius: 14px; background: #fff; padding: .1rem 1.25rem 1.25rem; }
.st-key-citation_media_single [data-testid="stImage"] img, [class*="st-key-qa_media_"][class*="_single"] [data-testid="stImage"] img { width: 100%; max-height: 420px; object-fit: contain; }
.st-key-citation_media_grid [data-testid="stImage"] img, [class*="st-key-qa_media_"][class*="_grid"] [data-testid="stImage"] img { width: 100%; height: 260px; object-fit: contain; }
.st-key-citation_media_grid [data-testid="stImage"] figcaption, [class*="st-key-qa_media_"][class*="_grid"] [data-testid="stImage"] figcaption { min-height: 2.8rem; }
.st-key-citation_media_grid [data-testid="stCaptionContainer"], [class*="st-key-qa_media_"][class*="_grid"] [data-testid="stCaptionContainer"] { min-height: 3.2rem; }

.source-card { border: 1px solid var(--picare-line); border-radius: 12px; padding: .85rem 1rem; margin-bottom: .55rem; display: flex; align-items: center; gap: .8rem; }
.source-icon { display: grid; place-items: center; width: 38px; height: 38px; border-radius: 50%; background: #ffe9ee; color: var(--picare-red); font-size: 1.1rem; flex: 0 0 auto; }
.source-title { font-weight: 700; font-size: .95rem; }
.source-meta { color: var(--picare-muted); font-size: .84rem; margin-top: .15rem; }
.source-link { margin-left: auto; color: var(--picare-red); text-decoration: none; font-weight: 800; font-size: 1.1rem; }

.qa-category { border: 1px solid var(--picare-line); border-radius: 10px; padding: .58rem .8rem; text-align: center; font-size: .92rem; font-weight: 700; background: white; }
.user-bubble { width: fit-content; max-width: 75%; margin: .9rem 0 .9rem auto; background: #ffe7eb; border-radius: 18px 18px 3px 18px; padding: .8rem 1.15rem; font-size: .98rem; font-weight: 500; }
[class*="st-key-qa_answer_bubble_"] { position: relative; border: 1px solid var(--picare-line); border-radius: 4px 18px 18px 18px; background: #fff; padding: 1rem 1.2rem; box-shadow: 0 3px 15px rgba(22, 31, 40, .05); }
.qa-answer-speaker { margin-bottom: .55rem; color: var(--picare-red-dark); font-size: .88rem; font-weight: 800; }
[class*="st-key-qa_answer_bubble_"] [data-testid="stMarkdownContainer"] p { font-size: .98rem; line-height: 1.72; }
[class*="st-key-qa_sources_panel_"] .section-title { margin-top: 0; }
.answer-card { border: 1px solid var(--picare-line); border-radius: 14px; padding: 1.2rem 1.3rem; box-shadow: 0 3px 15px rgba(22,31,40,.05); }
.answer-label { color: var(--picare-green); font-size: .94rem; font-weight: 800; margin-bottom: .8rem; }
.answer-label.blocked { color: #b15b00; }
.answer-card h3 { margin: 0 0 .45rem; font-size: 1.2rem; }
.answer-card p { font-size: .98rem; line-height: 1.72; color: #303945; }
.step-row { display: grid; grid-template-columns: 2rem 1fr; gap: .7rem; align-items: center; border: 1px solid var(--picare-line); border-radius: 9px; padding: .65rem .75rem; margin: .4rem 0; }
.step-number { display: grid; place-items: center; width: 1.75rem; height: 1.75rem; border-radius: 50%; background: var(--picare-red); color: white; font-weight: 800; font-size: .82rem; }
.warning-box { margin-top: .7rem; border: 1px solid #f2d59d; background: #fff8e8; color: #a55d00; border-radius: 8px; padding: .65rem .8rem; font-size: .84rem; }
.related-card { border: 1px solid var(--picare-line); border-radius: 9px; padding: .7rem .8rem; margin-bottom: .45rem; color: #37414d; background: #fff; }

.about-card-grid { width: 690px; min-width: 690px; box-sizing: border-box; display: grid; grid-template-columns: repeat(2, 335px); justify-content: center; gap: 20px; align-items: stretch; margin: 0 auto; padding: 6px 0 10px; }
.about-card { width: 100%; height: 180px; box-sizing: border-box; overflow: hidden; border: 1px solid #f3c2ce; border-radius: 20px; background: #fff; box-shadow: 0 12px 32px rgba(38,31,34,.08); text-align: center; transition: transform .18s ease, box-shadow .18s ease; }
.about-card:hover { transform: translateY(-3px); box-shadow: 0 16px 38px rgba(201,0,54,.13); }
.about-card-title { height: 74px; display: flex; align-items: center; justify-content: center; gap: .7rem; background: linear-gradient(135deg, #ed003f 0%, #c90036 100%); color: #fff; font-size: 1.16rem; font-weight: 800; line-height: 1.35; padding: .85rem 1.1rem; }
.about-card-icon { display: grid; place-items: center; width: 42px; height: 42px; flex: 0 0 42px; border: 1px solid rgba(255,255,255,.3); border-radius: 13px; background: rgba(255,255,255,.16); font-size: 1.4rem; }
.about-card-body { height: 104px; display: flex; flex-direction: column; background: #fff; }
.about-card p { margin: 0; padding: 1.05rem .6rem .3rem; color: #3d454f; font-size: .88rem; line-height: 1.62; white-space: nowrap; }
.about-card-action { display: flex; align-items: center; justify-content: center; gap: .55rem; margin: .25rem 1.2rem 1rem; border-radius: 11px; padding: .64rem 1rem; background: #fff0f3; color: #c90036 !important; font-size: .95rem; font-weight: 800; text-decoration: none !important; transition: background .16s ease, color .16s ease; }
.about-card-action span { font-size: 1.1rem; transition: transform .16s ease; }
.about-card-action:hover { background: #ed003f; color: #fff !important; }
.about-card-action:hover span { transform: translateX(3px); }
.about-abstention { width: 690px; min-width: 690px; box-sizing: border-box; margin: 1.6rem auto 1rem; display: flex; align-items: center; justify-content: center; gap: 1rem; border: 1px solid #f2d2da; border-radius: 16px; background: linear-gradient(90deg, #fff7f9 0%, #fff 100%); padding: 1rem 1.35rem; box-shadow: 0 5px 18px rgba(38,31,34,.045); text-align: left; }
.about-abstention-icon { display: grid; place-items: center; width: 44px; height: 44px; flex: 0 0 44px; border-radius: 50%; background: #ffe4eb; font-size: 1.35rem; }
.about-abstention strong { display: block; color: #a7002d; font-size: 1.02rem; margin-bottom: .2rem; }
.about-abstention p { margin: 0; color: #515a65; font-size: .94rem; line-height: 1.55; }
.about-source { margin-top: 1.7rem; padding-top: 1rem; border-top: 1px solid #eef0f2; color: var(--picare-muted); font-size: .9rem; text-align: center; }
.about-source a { color: var(--picare-red-dark); font-weight: 700; }

[data-testid="stJson"] { border: 1px solid var(--picare-line); border-radius: 10px; }
[data-testid="stDataFrame"] { border: 1px solid var(--picare-line); border-radius: 11px; overflow: hidden; }
[data-testid="stChatInput"] { max-width: 1380px; margin: 0 auto; }

@media (max-width: 760px) {
  .block-container { padding: 0 1rem 5rem; }
  .picare-header-line { margin: 0 -1rem 1rem; }
  .st-key-top_navigation { width: 368px; min-width: 368px; }
  .product-card { min-height: auto; }
  .user-bubble { max-width: 94%; }
  .about-card-title { font-size: 1.08rem; }
}
</style>
"""
