"""Минималистичные стили Streamlit."""

from __future__ import annotations

import streamlit as st

MINIMAL_CSS = """
<style>
    .block-container { padding-top: 1.5rem; padding-bottom: 2rem; max-width: 1100px; }
    [data-testid="stSidebar"] { background-color: #fafafa; border-right: 1px solid #eee; }
    [data-testid="stSidebar"] .stRadio label { font-size: 0.95rem; }
    h1 { font-weight: 600; letter-spacing: -0.02em; }
    h2, h3 { font-weight: 500; }
    .stChatMessage { border-radius: 8px; }
    div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 8px; }
</style>
"""


def apply_minimal_theme() -> None:
    st.markdown(MINIMAL_CSS, unsafe_allow_html=True)
