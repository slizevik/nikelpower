"""NikelPower — Streamlit Frontend."""

from __future__ import annotations

import streamlit as st

from app.ui.chat_tab import render_chat_page
from app.ui.sidebar import render_app_sidebar
from app.ui.styles import apply_minimal_theme
from app.ui.upload_tab import render_upload_tab

st.set_page_config(
    page_title="NikelPower",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_minimal_theme()

page = render_app_sidebar()

if page == "chat":
    render_chat_page()
else:
    from app.ui.token_display import render_token_sidebar

    st.sidebar.divider()
    render_token_sidebar()
    render_upload_tab()
