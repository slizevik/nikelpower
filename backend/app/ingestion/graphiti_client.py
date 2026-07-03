"""Graphiti client wrapper for Neo4j knowledge graph operations."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType

from app.config import settings
from app.ingestion.chunker import TextChunk
from app.ontology import EDGE_TYPE_MAP, EDGE_TYPES, ENTITY_TYPES, EXTRACTION_INSTRUCTIONS

logger = logging.getLogger(__name__)

_graphiti: Graphiti | None = None
_indices_built = False


def get_graphiti() -> Graphiti:
    global _graphiti
    if _graphiti is None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for Graphiti LLM extraction")
        _graphiti = Graphiti(
            settings.neo4j_uri,
            settings.neo4j_user,
            settings.neo4j_password,
        )
    return _graphiti


async def ensure_indices() -> None:
    global _indices_built
    if _indices_built:
        return
    graphiti = get_graphiti()
    await graphiti.build_indices_and_constraints()
    _indices_built = True
    logger.info("Graphiti indices and constraints initialized")


async def ingest_chunk(chunk: TextChunk, reference_time: datetime | None = None) -> None:
    await ensure_indices()
    graphiti = get_graphiti()
    ref = reference_time or datetime.now(timezone.utc)

    episode_name = f"{chunk.source_path}#chunk{chunk.chunk_index}"
    source_description = (
        f"file={chunk.source_path}; pages={chunk.page_start}-{chunk.page_end}; "
        f"type={chunk.doc_type}; lang={chunk.language_hint}"
    )

    await graphiti.add_episode(
        name=episode_name,
        episode_body=chunk.text,
        source=EpisodeType.text,
        source_description=source_description,
        reference_time=ref,
        group_id=chunk.group_id,
        entity_types=ENTITY_TYPES,
        edge_types=EDGE_TYPES,
        edge_type_map=EDGE_TYPE_MAP,
        custom_extraction_instructions=EXTRACTION_INSTRUCTIONS,
    )


async def ingest_chunks_bulk(chunks: list[TextChunk]) -> None:
    await ensure_indices()
    graphiti = get_graphiti()
    ref = datetime.now(timezone.utc)

    from graphiti_core.utils.bulk_utils import RawEpisode

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

    await graphiti.add_episode_bulk(
        raw_episodes,
        group_id=chunks[0].group_id if chunks else settings.graphiti_group_id,
        entity_types=ENTITY_TYPES,
        edge_types=EDGE_TYPES,
        edge_type_map=EDGE_TYPE_MAP,
        custom_extraction_instructions=EXTRACTION_INSTRUCTIONS,
    )


async def search_graph(query: str, num_results: int = 10):
    await ensure_indices()
    graphiti = get_graphiti()
    return await graphiti.search(query=query, num_results=num_results)


async def close_graphiti() -> None:
    global _graphiti, _indices_built
    if _graphiti is not None:
        await _graphiti.close()
        _graphiti = None
        _indices_built = False
