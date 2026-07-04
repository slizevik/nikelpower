"""Панель визуализации графа знаний (pyvis)."""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from app.services.chat_graph_viz import ChatGraphData, ChatGraphVisualizationService


def render_graph_panel(query: str | None) -> None:
    st.markdown("#### Граф знаний по запросу")
    if not query or not query.strip():
        st.caption("Отправьте запрос — здесь появится визуализация связей.")
        return

    try:
        data = ChatGraphVisualizationService().build_for_query(query)
    except Exception as exc:
        st.warning(f"Граф недоступен: {exc}")
        return

    if data.gaps:
        st.markdown("**Пробелы и противоречия**")
        for gap in data.gaps:
            st.markdown(f"- :orange[{gap}]")

    if data.chains:
        st.markdown("**Цепочки: материал → процесс → оборудование → результат**")
        for chain in data.chains[:6]:
            parts = [chain.material]
            if chain.process:
                parts.append(chain.process)
            if chain.equipment:
                parts.append(chain.equipment)
            if chain.result:
                parts.append(chain.result)
            st.markdown(" → ".join(f"**{p}**" for p in parts))

    col1, col2 = st.columns(2)
    with col1:
        if data.experts:
            st.markdown("**Эксперты**")
            for name in data.experts:
                st.markdown(f"- {name}")
        else:
            st.caption("Эксперты по теме не найдены.")
    with col2:
        if data.facilities:
            st.markdown("**Лаборатории / предприятия**")
            for name in data.facilities:
                st.markdown(f"- {name}")
        else:
            st.caption("Лаборатории по теме не найдены.")

    if data.nodes:
        html = _build_pyvis_html(data)
        components.html(html, height=420, scrolling=True)
    else:
        st.info("Сущности для построения графа не найдены в Neo4j.")


def _build_pyvis_html(data: ChatGraphData) -> str:
    from pyvis.network import Network

    net = Network(height="380px", width="100%", bgcolor="#ffffff", font_color="#333333")
    net.barnes_hut(gravity=-8000, central_gravity=0.3, spring_length=120)

    for node in data.nodes:
        net.add_node(
            node.id,
            label=node.label,
            title=node.entity_type,
            color=node.color,
            shape="dot",
            size=18,
        )
    for edge in data.edges:
        net.add_edge(edge.source, edge.target, title=edge.label, arrows="to")

    net.set_options(
        """
        var options = {
          "physics": {"enabled": true, "stabilization": {"iterations": 80}},
          "edges": {"color": {"inherit": true}, "smooth": {"type": "continuous"}},
          "interaction": {"hover": true}
        }
        """
    )
    return net.generate_html(notebook=False)
