"""Вкладка «Чат с LLM» — PostgreSQL история, фильтры, граф."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from app.chat.repository import ChatRepository
from app.config import settings
from app.llm.token_budget import TokenBudgetExceeded, get_token_budget
from app.models.chat import ChatAgentResponse, ChatSearchFilters
from app.services.chat_agent import ChatAgentService
from app.ui.graph_panel import render_graph_panel
from app.ui.sidebar import ensure_active_chat, render_chat_history_sidebar

_RELIABILITY_LABELS = {"high": "Высокая", "medium": "Средняя", "low": "Низкая"}


def render_chat_page() -> None:
    render_chat_history_sidebar()
    session_id = ensure_active_chat()

    st.markdown("## Чат с LLM")
    st.caption("Поиск по базе через AI-агента · косинусная близость эмбеддингов")

    filters = _render_source_filters(session_id)
    _persist_filters(session_id, filters)

    messages = _load_messages(session_id)
    last_user_query: str | None = None

    for msg in messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("response"):
                _render_agent_response(msg["response"], message_id=msg.get("id", ""))
        if msg["role"] == "user":
            last_user_query = msg["content"]

    with st.expander("Граф знаний", expanded=bool(last_user_query)):
        render_graph_panel(last_user_query)

    user_query = st.text_input(
        "Запрос",
        placeholder="Опишите, какую информацию нужно найти в базе…",
        key="chat_query_input",
        label_visibility="collapsed",
    )
    col_send, _ = st.columns([1, 4])
    send = col_send.button("Отправить", type="primary", use_container_width=True)

    if send and user_query.strip():
        _handle_submit(session_id, user_query.strip(), filters)
        st.rerun()


def _render_source_filters(session_id: str) -> ChatSearchFilters:
    stored = st.session_state.get("chat_filters", {})
    domestic = stored.get("domestic", True)
    foreign = stored.get("foreign", True)

    if session_id:
        try:
            session = ChatRepository().get_session(session_id)
            if session:
                domestic = session.filter_domestic
                foreign = session.filter_foreign
        except Exception:
            pass

    st.markdown("**Источники**")
    c1, c2 = st.columns(2)
    with c1:
        include_domestic = st.checkbox("Отечественные источники", value=domestic, key="flt_domestic")
    with c2:
        include_foreign = st.checkbox("Зарубежные источники", value=foreign, key="flt_foreign")

    st.session_state.chat_filters = {"domestic": include_domestic, "foreign": include_foreign}

    return ChatSearchFilters(
        include_domestic=include_domestic,
        include_foreign=include_foreign,
        min_relevance_score=float(settings.embedding_similarity_threshold * 0.85),
    )


def _persist_filters(session_id: str, filters: ChatSearchFilters) -> None:
    if not session_id:
        return
    try:
        ChatRepository().update_session(
            session_id,
            filter_domestic=filters.include_domestic,
            filter_foreign=filters.include_foreign,
        )
    except Exception:
        pass


def _load_messages(session_id: str) -> list[dict]:
    if not session_id:
        return []
    try:
        rows = ChatRepository().list_messages(session_id)
    except Exception:
        return []

    out: list[dict] = []
    for row in rows:
        item: dict = {"id": row.id, "role": row.role, "content": row.content}
        if row.response_json:
            try:
                item["response"] = ChatAgentResponse.model_validate(row.response_json)
            except Exception:
                pass
        out.append(item)
    return out


def _handle_submit(session_id: str, user_query: str, filters: ChatSearchFilters) -> None:
    if not session_id:
        st.error("PostgreSQL недоступен — история чатов не сохраняется.")
        return

    repo = ChatRepository()
    budget = get_token_budget()
    budget.begin_request()

    try:
        repo.add_message(session_id, role="user", content=user_query)

        session = repo.get_session(session_id)
        if session and session.title == "Новый чат":
            title = user_query[:50] + ("…" if len(user_query) > 50 else "")
            repo.update_session(session_id, title=title)

        with st.spinner("AI-агент ищет в базе…"):
            response = ChatAgentService().search_documents(user_query, filters)

        assistant_text = response.message
        if response.no_data:
            assistant_text = response.message or "Данные не найдены."
        elif response.comparative_note:
            assistant_text += f"\n\n**Сравнение:** {response.comparative_note}"

        repo.add_message(
            session_id,
            role="assistant",
            content=assistant_text,
            response_json=json.loads(response.model_dump_json()),
        )
    except TokenBudgetExceeded as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(f"Ошибка AI-агента: {exc}")
    finally:
        budget.finish_request()


def _render_agent_response(response: ChatAgentResponse, *, message_id: str = "") -> None:
    if response.no_data or not response.documents:
        st.warning(response.message or "По запросу не найдено ни одного источника.")
        return

    for i, doc in enumerate(response.documents, 1):
        with st.container(border=True):
            rel = _RELIABILITY_LABELS.get(doc.reliability, doc.reliability)
            st.markdown(f"**{i}. {doc.title}**")
            st.markdown(doc.summary)
            m1, m2, m3 = st.columns(3)
            m1.caption(f"Автор: {doc.author_or_source or '—'}")
            m2.caption(f"Актуализация: {doc.updated_at or '—'}")
            m3.caption(f"Score: {doc.relevance_score:.3f} ({rel})")
            if doc.download_path:
                path = Path(doc.download_path)
                if path.is_file():
                    st.download_button(
                        f"Скачать ({path.name})",
                        data=path.read_bytes(),
                        file_name=path.name,
                        key=f"dl_{message_id}_{doc.group_id or 'na'}_{i}",
                    )
