"""Graphiti client wrapper for Neo4j knowledge graph operations."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType

from app.config import settings
from app.ingestion.graphiti_factory import create_graphiti
from app.llm.token_budget import count_tokens, get_token_budget
from app.dictionary.resolver import EntityDictionaryResolver
from app.ingestion.chunker import TextChunk
from app.ontology import EDGE_TYPE_MAP, EDGE_TYPES, ENTITY_TYPES

logger = logging.getLogger(__name__)

_graphiti: Graphiti | None = None
_indices_built = False
_resolver: EntityDictionaryResolver | None = None


def get_resolver() -> EntityDictionaryResolver:
    global _resolver
    if _resolver is None:
        _resolver = EntityDictionaryResolver()
    return _resolver


def get_graphiti() -> Graphiti:
    global _graphiti
    if _graphiti is None:
        _graphiti = create_graphiti()
    return _graphiti


async def ensure_indices() -> None:
    global _indices_built
    if _indices_built:
        return
    graphiti = get_graphiti()
    await graphiti.build_indices_and_constraints()
    await asyncio.to_thread(get_resolver().ensure_ready)
    _indices_built = True
    logger.info("Graphiti and DictEntity indices initialized")


def _instructions_for_chunk(chunk_text: str) -> str:
    return get_resolver().build_instructions_for_chunk(chunk_text)


def _sync_dictionary(nodes: list, source_document: str | None) -> None:
    if not nodes:
        return
    try:
        get_resolver().register_from_graphiti_nodes(nodes, source_document=source_document)
    except Exception as exc:
        logger.warning("Dictionary sync failed: %s", exc)


def _charge_graphiti_tokens(chunk_text: str, operation: str) -> None:
    """Оценка токенов Graphiti (несколько LLM-вызовов на один чанк)."""
    instructions = _instructions_for_chunk(chunk_text)
    estimate = (count_tokens(chunk_text) + count_tokens(instructions)) * 4
    get_token_budget().record(estimate, operation)


async def ingest_chunk(chunk: TextChunk, reference_time: datetime | None = None) -> None:
    await ensure_indices()
    _charge_graphiti_tokens(chunk.text, "graphiti_ingest")
    graphiti = get_graphiti()
    ref = reference_time or datetime.now(timezone.utc)

    episode_name = f"{chunk.source_path}#chunk{chunk.chunk_index}"
    source_description = (
        f"file={chunk.source_path}; pages={chunk.page_start}-{chunk.page_end}; "
        f"type={chunk.doc_type}; lang={chunk.language_hint}"
    )

    result = await graphiti.add_episode(
        name=episode_name,
        episode_body=chunk.text,
        source=EpisodeType.text,
        source_description=source_description,
        reference_time=ref,
        group_id=chunk.group_id,
        entity_types=ENTITY_TYPES,
        edge_types=EDGE_TYPES,
        edge_type_map=EDGE_TYPE_MAP,
        custom_extraction_instructions=_instructions_for_chunk(chunk.text),
    )

    nodes = getattr(result, "nodes", None) or []
    _sync_dictionary(list(nodes), source_document=chunk.source_path)


async def ingest_chunks_bulk(chunks: list[TextChunk]) -> None:
    await ensure_indices()
    combined = "\n".join(c.text[:1500] for c in chunks[:3])
    _charge_graphiti_tokens(combined, "graphiti_ingest_bulk")
    graphiti = get_graphiti()
    ref = datetime.now(timezone.utc)

    from graphiti_core.utils.bulk_utils import RawEpisode

    # Для bulk используем объединённый контекст словаря по первому чанку батча
    combined_context = _instructions_for_chunk(
        "\n".join(c.text[:1500] for c in chunks[:3])
    )

    raw_episodes = []
    for chunk in chunks:
        raw_episodes.append(
            RawEpisode(
                name=f"{chunk.source_path}#chunk{chunk.chunk_index}",
                content=chunk.text,
                source_description=(
                    f"file={chunk.source_path}; pages={chunk.page_start}-{chunk.page_end}; "
                    f"type={chunk.doc_type}; lang={chunk.language_hint}"
                ),
                source=EpisodeType.text,
                reference_time=ref,
                group_id=chunk.group_id,
            )
        )

    results = await graphiti.add_episode_bulk(
        raw_episodes,
        group_id=chunks[0].group_id if chunks else settings.graphiti_group_id,
        entity_types=ENTITY_TYPES,
        edge_types=EDGE_TYPES,
        edge_type_map=EDGE_TYPE_MAP,
        custom_extraction_instructions=combined_context,
    )

    source = chunks[0].source_path if chunks else None
    for item in results or []:
        nodes = getattr(item, "nodes", None) or []
        _sync_dictionary(list(nodes), source_document=source)


async def search_graph(query: str, num_results: int = 10):
    await ensure_indices()
    get_token_budget().record(count_tokens(query) * 2, "graphiti_search")
    graphiti = get_graphiti()
    return await graphiti.search(query=query, num_results=num_results)


async def close_graphiti() -> None:
    global _graphiti, _indices_built, _resolver
    if _graphiti is not None:
        await _graphiti.close()
        _graphiti = None
        _indices_built = False
    if _resolver is not None:
        _resolver.store.close()
        _resolver = None
