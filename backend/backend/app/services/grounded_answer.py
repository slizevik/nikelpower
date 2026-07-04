"""
Grounded Q&A: ответ только на основе фактов из Neo4j/Graphiti.

LLM — Yandex AI Studio (OpenAI-compatible). Запрещено ссылаться на документы,
которых нет в переданном контексте из графа.
"""

from __future__ import annotations

import asyncio
import json
import logging

from app.config import settings
from app.ingestion.graphiti_client import search_graph
from app.llm.tracked_api import chat_completions_create
from app.llm.yandex_client import get_yandex_client
from app.models.answer import GroundedAnswer, SourceCitation
from app.services.graph_query import GraphQueryService

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
You are a materials science research assistant for Nikelpower.
Answer ONLY using the FACTS provided in the user message from the knowledge graph.
Rules:
- Do NOT invent documents, publications, experiments, or numeric values.
- If facts are insufficient, set insufficient_data=true and explain what is missing.
- Every claim must map to at least one citation from the provided facts.
- Respond in the same language as the user query (Russian or English).
- Output valid JSON matching the schema exactly.
"""


class GroundedAnswerService:
    def __init__(self) -> None:
        self.graph = GraphQueryService()

    async def answer(self, query: str, num_graph_results: int = 8) -> GroundedAnswer:
        graph_facts = await search_graph(query, num_results=num_graph_results)
        citations: list[SourceCitation] = []

        for edge in graph_facts:
            fact = getattr(edge, "fact", None) or str(edge)
            rel_name = getattr(edge, "name", None)
            source_uuid = getattr(edge, "source_node_uuid", None)
            target_uuid = getattr(edge, "target_node_uuid", None)
            citations.append(
                SourceCitation(
                    fact=fact,
                    relation=rel_name,
                    source_entity=source_uuid,
                    target_entity=target_uuid,
                    episode_source=_episode_source_from_edge(edge),
                )
            )

        if not citations:
            return GroundedAnswer(
                query=query,
                answer="В базе знаний нет данных, релевантных вашему запросу.",
                confidence="insufficient_data",
                citations=[],
                entities_mentioned=[],
                insufficient_data=True,
            )

        context_block = _format_facts_for_prompt(citations)
        user_prompt = f"""
User query: {query}

Graph facts (ONLY source of truth):
{context_block}

Return JSON:
{{
  "answer": "string",
  "confidence": "high|medium|low|insufficient_data",
  "entities_mentioned": ["..."],
  "insufficient_data": false,
  "citation_indices": [1, 2]
}}
"""

        client = get_yandex_client()
        response = chat_completions_create(
            client,
            model=settings.yandex_cloud_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )

        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)

        selected_indices = parsed.get("citation_indices") or list(range(1, len(citations) + 1))
        selected_citations = [
            citations[i - 1] for i in selected_indices if 0 < i <= len(citations)
        ]

        return GroundedAnswer(
            query=query,
            answer=parsed.get("answer", ""),
            confidence=parsed.get("confidence", "medium"),
            citations=selected_citations or citations,
            entities_mentioned=parsed.get("entities_mentioned") or [],
            insufficient_data=bool(parsed.get("insufficient_data", False)),
        )

    def answer_sync(self, query: str, num_graph_results: int = 8) -> GroundedAnswer:
        return asyncio.run(self.answer(query, num_graph_results=num_graph_results))


def _format_facts_for_prompt(citations: list[SourceCitation]) -> str:
    lines = []
    for i, cite in enumerate(citations, 1):
        rel = f" [{cite.relation}]" if cite.relation else ""
        lines.append(f"{i}. {cite.fact}{rel}")
    return "\n".join(lines)


def _episode_source_from_edge(edge: object) -> str | None:
    for attr in ("source_description", "episode_source", "group_id"):
        value = getattr(edge, attr, None)
        if isinstance(value, str) and value.strip():
            return value
    return None
