"""Graphiti enrichment: идемпотентная загрузка чанков в темпоральный граф."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.config import settings
from app.ingestion.checkpoint import CheckpointStore
from app.ingestion.steps import IngestionStep, ProgressCallback, report_progress
from app.models.chunk import TextChunk

logger = logging.getLogger(__name__)


@dataclass
class GraphitiEnrichmentStats:
    chunks_total: int = 0
    chunks_ingested: int = 0
    chunks_skipped: int = 0
    chunks_failed: int = 0
    skipped: bool = False
    skip_reason: str | None = None


def _episode_name(chunk: TextChunk) -> str:
    return f"{chunk.group_id}#chunk{chunk.chunk_index}"


async def _enrich_async(
    chunks: list[TextChunk],
    *,
    group_id: str,
    checkpoint: CheckpointStore,
    on_progress: ProgressCallback | None = None,
) -> GraphitiEnrichmentStats:
    from app.ingestion.graphiti_client import ingest_chunks_bulk

    if not chunks:
        return GraphitiEnrichmentStats()

    cp = checkpoint.load(group_id)
    existing = set(cp.graphiti_episodes if cp else [])
    pending = [c for c in chunks if _episode_name(c) not in existing]

    stats = GraphitiEnrichmentStats(
        chunks_total=len(chunks),
        chunks_skipped=len(chunks) - len(pending),
    )

    if not pending:
        checkpoint.mark_graphiti_complete(group_id)
        logger.info("Graphiti: all %s chunks already ingested for %s", len(chunks), group_id)
        return stats

    batch_size = max(1, settings.ingestion_batch_size)
    ingested_names: list[str] = []

    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        report_progress(
            on_progress,
            IngestionStep.GRAPHITI_ENRICHMENT,
            f"{start + len(batch)}/{len(pending)}",
        )
        try:
            await ingest_chunks_bulk(batch)
        except Exception as exc:
            logger.exception(
                "Graphiti batch failed (chunks %s–%s): %s",
                start + 1,
                start + len(batch),
                exc,
            )
            stats.chunks_failed += len(batch)
            continue
        batch_names = [_episode_name(c) for c in batch]
        ingested_names.extend(batch_names)
        checkpoint.mark_graphiti_episodes(group_id, batch_names)
        stats.chunks_ingested += len(batch)

    checkpoint.mark_graphiti_complete(group_id)
    logger.info(
        "Graphiti enrichment: group=%s ingested=%s skipped=%s",
        group_id,
        stats.chunks_ingested,
        stats.chunks_skipped,
    )
    return stats


def enrich_document_with_graphiti(
    chunks: list[TextChunk],
    *,
    group_id: str,
    checkpoint: CheckpointStore | None = None,
    on_progress: ProgressCallback | None = None,
) -> GraphitiEnrichmentStats:
    from app.ingestion.graphiti_client import is_graphiti_available

    if not settings.enable_graphiti_enrichment:
        return GraphitiEnrichmentStats(skipped=True, skip_reason="disabled")

    if not is_graphiti_available():
        logger.info("Graphiti enrichment skipped: graphiti-core not installed")
        return GraphitiEnrichmentStats(skipped=True, skip_reason="not_installed")

    store = checkpoint or CheckpointStore()
    report_progress(on_progress, IngestionStep.GRAPHITI_ENRICHMENT)
    return asyncio.run(
        _enrich_async(chunks, group_id=group_id, checkpoint=store, on_progress=on_progress)
    )
