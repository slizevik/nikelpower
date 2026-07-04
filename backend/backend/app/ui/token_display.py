"""Отображение расхода токенов в Streamlit."""

from __future__ import annotations

import streamlit as st

from app.llm.token_budget import TOKEN_LIMIT, get_token_budget


def render_token_sidebar() -> None:
    budget = get_token_budget()
    snap = budget.snapshot()

    st.sidebar.markdown("### Расход токенов")

    request_tokens = (
        snap.current_request_tokens
        if snap.current_request_tokens > 0
        else snap.last_request_tokens
    )
    st.sidebar.metric("За текущий / последний запрос", f"{request_tokens:,}")
    st.sidebar.metric(
        "Всего потрачено",
        f"{snap.total_tokens:,}",
        delta=f"лимит {TOKEN_LIMIT:,}",
        delta_color="off",
    )
    st.sidebar.metric("Остаток лимита", f"{snap.remaining:,}")
    st.sidebar.progress(
        min(snap.usage_percent / 100.0, 1.0),
        text=f"{snap.usage_percent:.1f}% от лимита",
    )

    if snap.total_tokens >= TOKEN_LIMIT:
        st.sidebar.error("Лимит токенов исчерпан. Новые запросы к LLM заблокированы.")
