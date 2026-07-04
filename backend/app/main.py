import asyncio
import json

import streamlit as st

from app.config import settings
from app.core.neo4j import verify_neo4j_connection
from app.llm.token_budget import TokenBudgetExceeded, get_token_budget
from app.ontology import ENTITY_TYPE_NAMES
from app.services.graph_query import GraphQueryService
from app.ui.token_display import render_token_sidebar
from app.ui.upload_tab import render_upload_tab

st.set_page_config(page_title="NikelPower", page_icon="🔬", layout="wide")

render_token_sidebar()

st.title("🔬 NikelPower")
st.caption("Neo4j + Graphiti + Yandex AI Studio")

tab_upload, tab_graph, tab_qa = st.tabs(
    ["Загрузка документа", "Граф знаний", "Поиск и Q&A"]
)

with tab_upload:
    render_upload_tab()

with tab_graph:
    budget = get_token_budget()
    snap = budget.snapshot()
    col1, col2, col3 = st.columns(3)
    col1.metric("Токены (всего)", f"{snap.total_tokens:,}")
    col2.metric("Лимит", f"{snap.limit:,}")
    col3.metric("Neo4j", settings.neo4j_uri)

    st.divider()
    st.subheader("Состояние графа знаний")

    if st.button("Обновить статистику", key="graph_stats"):
        budget.begin_request()
        try:
            service = GraphQueryService()
            stats = service.get_stats()
            checks = service.verify_ontology_constraints()

            st.success(verify_neo4j_connection())
            st.write("**Сущности (Graphiti):**")
            st.json(stats.entity_counts)
            st.write("**Связи:**")
            st.json(stats.relation_counts)
            st.write(f"DictEntity: {stats.dict_entity_count} | Episodic: {stats.episodic_count}")
            st.write("**Проверки онтологии:**")
            st.json(checks)
        except Exception as exc:
            st.error(str(exc))
        finally:
            budget.finish_request()

    st.divider()
    st.subheader("Cypher: поиск сущностей")
    entity_pattern = st.text_input("Имя (фрагмент)", value="никель", key="entity_pattern")
    entity_type = st.selectbox("Тип", ["", *ENTITY_TYPE_NAMES], key="entity_type")

    if st.button("Найти сущности", key="find_entities"):
        budget.begin_request()
        try:
            found = GraphQueryService().find_entities(
                entity_pattern,
                entity_type=entity_type or None,
                limit=20,
            )
            if not found:
                st.info("Сущности не найдены.")
            for item in found:
                st.write(f"- [{item.entity_type}] **{item.name}**")
        except Exception as exc:
            st.error(str(exc))
        finally:
            budget.finish_request()

with tab_qa:
    budget = get_token_budget()

    st.subheader("Graphiti search")
    search_query = st.text_input("Запрос", value="электроэкстракция никеля", key="search_query")

    if st.button("Искать в графе", key="graph_search"):
        budget.begin_request()
        try:
            from app.ingestion.graphiti_client import search_graph

            results = asyncio.run(search_graph(search_query, num_results=5))
            st.write(f"Найдено: {len(results)}")
            for i, edge in enumerate(results, 1):
                fact = getattr(edge, "fact", None) or str(edge)
                st.write(f"{i}. {fact}")
        except TokenBudgetExceeded as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(str(exc))
        finally:
            budget.finish_request()

    st.divider()
    st.subheader("RAG-поиск по документам")
    rag_query = st.text_input("Запрос RAG", value="электроэкстракция никеля", key="rag_query")

    if st.button("RAG search", key="rag_search"):
        budget.begin_request()
        try:
            from app.services.rag_search import RagSearchService

            hits = RagSearchService().search(rag_query, top_k=5)
            st.write(f"Найдено фрагментов: {len(hits)}")
            for i, hit in enumerate(hits, 1):
                title = hit.document_title or hit.source_path or "документ"
                st.markdown(f"**{i}. {title}** (score={hit.score:.3f}, стр. {hit.page_start}-{hit.page_end})")
                st.text(hit.text[:1500])
        except TokenBudgetExceeded as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(str(exc))
        finally:
            budget.finish_request()

    st.divider()
    st.subheader("Grounded Q&A (только данные из БД)")
    user_query = st.text_input(
        "Вопрос", value="Какая концентрация никеля упоминается?", key="user_query"
    )

    if st.button("Ответить", key="grounded_answer"):
        budget.begin_request()
        try:
            from app.services.grounded_answer import GroundedAnswerService

            answer = GroundedAnswerService().answer_sync(user_query)
            st.json(json.loads(answer.model_dump_json(ensure_ascii=False)))
        except TokenBudgetExceeded as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(str(exc))
        finally:
            budget.finish_request()

    st.divider()
    st.subheader("Эмбеддинги (Yandex text-search-doc)")
    test_text = st.text_input("Текст", value="никель электроэкстракция католит", key="embed_text")

    if st.button("Эмбеддинг", key="run_embed"):
        budget.begin_request()
        try:
            from app.dictionary.embeddings import embed_text

            vector = embed_text(test_text)
            st.success(f"Размерность: {len(vector)}")
        except TokenBudgetExceeded as exc:
            st.error(str(exc))
        except Exception as exc:
            st.error(str(exc))
        finally:
            budget.finish_request()
