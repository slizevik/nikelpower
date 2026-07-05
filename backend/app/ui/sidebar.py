"""Боковое меню: навигация и история чатов."""

from __future__ import annotations

import streamlit as st

from app.chat.repository import ChatRepository
from app.ui.token_display import render_token_sidebar

PAGES = {
    "chat": "Чат с LLM",
    "upload": "Загрузка документов",
}


def render_app_sidebar() -> str:
    st.sidebar.markdown("### NikelPower")
    page_key = st.sidebar.radio(
        "Раздел",
        options=list(PAGES.keys()),
        format_func=lambda k: PAGES[k],
        index=0,
        label_visibility="collapsed",
    )
    st.sidebar.divider()
    return page_key


def render_chat_history_sidebar() -> None:
    st.sidebar.markdown("**Чаты**")

    if st.sidebar.button("+ Новый чат", use_container_width=True, key="new_chat_btn"):
        _create_new_chat()
        st.rerun()

    try:
        repo = ChatRepository()
        sessions = repo.list_sessions()
    except Exception as exc:
        st.sidebar.error(f"PostgreSQL: {exc}")
        return

    active_id = st.session_state.get("active_chat_id")

    for session in sessions:
        label = session.title[:36] + ("…" if len(session.title) > 36 else "")
        is_active = session.id == active_id
        btn_type = "primary" if is_active else "secondary"
        if st.sidebar.button(
            label,
            key=f"chat_sel_{session.id}",
            use_container_width=True,
            type=btn_type,
        ):
            st.session_state.active_chat_id = session.id
            st.session_state.chat_filters = {
                "domestic": session.filter_domestic,
                "foreign": session.filter_foreign,
            }
            st.rerun()

    st.sidebar.divider()
    render_token_sidebar()


def ensure_active_chat() -> str:
    if st.session_state.get("active_chat_id"):
        return st.session_state.active_chat_id

    try:
        repo = ChatRepository()
        sessions = repo.list_sessions()
        if sessions:
            st.session_state.active_chat_id = sessions[0].id
            return sessions[0].id
        session = repo.create_session()
        st.session_state.active_chat_id = session.id
        return session.id
    except Exception:
        return ""


def _create_new_chat() -> None:
    repo = ChatRepository()
    domestic = st.session_state.get("chat_filters", {}).get("domestic", True)
    foreign = st.session_state.get("chat_filters", {}).get("foreign", True)
    session = repo.create_session(filter_domestic=domestic, filter_foreign=foreign)
    st.session_state.active_chat_id = session.id
