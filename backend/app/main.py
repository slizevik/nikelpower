import asyncio
import os

import streamlit as st
from neo4j import GraphDatabase

from app.llm.token_budget import TokenBudgetExceeded, get_token_budget
from app.ui.token_display import render_token_sidebar


def _show_yandex_api_hint(exc: Exception) -> None:
    """Подсказки при ошибках Yandex API (400/403/404)."""
    status = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None) or getattr(exc, "message", "")
    if status:
        st.caption(f"HTTP {status}: {body}")
    if status == 400:
        st.info(
            "400 — неверный запрос. Проверьте в `.env`:\n"
            "1. Без пробелов: `YANDEX_CLOUD_FOLDER=b1g...` (не `= \"...\"`)\n"
            "2. `YANDEX_EMBEDDING_MODEL=emb://<ваш_folder>/text-search-doc/latest`\n"
            "3. Не используйте chat-модель (qwen, aliceai) для эмбеддингов\n"
            "4. folder в `emb://` должен совпадать с `YANDEX_CLOUD_FOLDER`"
        )


st.set_page_config(
    page_title="NikelPower",
    page_icon="🔬",
    layout="wide",
)

render_token_sidebar()

st.title("🔬 NikelPower")
st.write("Карта знаний R&D — горно-металлургия")

neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
neo4j_user = os.getenv("NEO4J_USER", "neo4j")
neo4j_password = os.getenv("NEO4J_PASSWORD", "nikelpower2026")

budget = get_token_budget()

col_main, col_tokens = st.columns([3, 1])
with col_tokens:
    snap = budget.snapshot()
    st.metric("Токены за запрос", f"{snap.last_request_tokens:,}")
    st.metric("Всего", f"{snap.total_tokens:,}")

st.info(f"🔗 Neo4j: `{neo4j_uri}`")

if st.button("Проверить подключение к Neo4j"):
    budget.begin_request()
    try:
        driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
        with driver.session() as session:
            result = session.run("RETURN 'Neo4j работает!' AS message")
            message = result.single()["message"]
        driver.close()
        st.success(f"✅ {message}")
    except Exception as e:
        st.error(f"❌ Ошибка подключения: {e}")
        st.warning("Убедитесь, что Neo4j запущен: `docker compose up -d`")
    finally:
        budget.finish_request()
        st.rerun()

st.divider()
st.subheader("Тест эмбеддингов (Yandex)")
test_text = st.text_input(
    "Текст для эмбеддинга",
    value="никель электроэкстракция католит",
    key="embed_test_text",
)

if st.button("Выполнить эмбеддинг"):
    budget.begin_request()
    try:
        from app.dictionary.embeddings import embed_text

        vector = embed_text(test_text)
        st.success(f"Эмбеддинг получен, размерность: {len(vector)}")
    except TokenBudgetExceeded as exc:
        st.error(str(exc))
    except Exception as e:
        st.error(f"Ошибка: {e}")
        _show_yandex_api_hint(e)
    finally:
        budget.finish_request()
        st.rerun()

st.divider()
st.subheader("Поиск в графе (Graphiti)")
search_query = st.text_input("Запрос", value="методы обессоливания воды")

if st.button("Искать"):
    budget.begin_request()
    try:
        from app.ingestion.graphiti_client import search_graph

        results = asyncio.run(search_graph(search_query, num_results=5))
        st.write(f"Найдено: {len(results)}")
        for i, edge in enumerate(results, 1):
            fact = getattr(edge, "fact", None) or str(edge)
            st.write(f"{i}. {fact}")
    except ImportError:
        st.warning(
            "Graphiti не установлен в этом контейнере (лёгкий образ backend). "
            "Поиск доступен в worker или при локальной установке requirements-worker.txt."
        )
    except TokenBudgetExceeded as exc:
        st.error(str(exc))
    except Exception as e:
        st.error(f"Ошибка поиска: {e}")
    finally:
        budget.finish_request()
        st.rerun()
