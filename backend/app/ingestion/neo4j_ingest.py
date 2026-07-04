"""
Загрузка подготовленного документа в Neo4j: чанки RAG + сущности + метаданные.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import settings
from app.dictionary.embeddings import embed_texts
from app.ingestion.archive_store import archive_original_document
from app.ingestion.checkpoint import (
    CheckpointStore,
    compute_file_content_hash,
    document_group_id,
)
from app.ingestion.chunk_store import DocumentChunkStore, IngestStats
from app.ingestion.chunker import chunk_document
from app.ingestion.entity_store import IngestedEntityStore
from app.ingestion.orchestrator import to_legacy_parsed_document
from app.ingestion.paragraphs import document_to_blocks
from app.ingestion.steps import ProgressCallback
from app.models.extraction import EntityExtractionResult
from app.ingestion.models import ParseResult
from app.models.chunk import TextChunk

logger = logging.getLogger(__name__)


class Neo4jIngestionPipeline:
    def __init__(
        self,
        chunk_store: DocumentChunkStore | None = None,
        entity_store: IngestedEntityStore | None = None,
        checkpoint_store: CheckpointStore | None = None,
    ) -> None:
        self.chunk_store = chunk_store or DocumentChunkStore()
        self.entity_store = entity_store or IngestedEntityStore()
        self.checkpoint = checkpoint_store or CheckpointStore()

    def close(self) -> None:
        self.chunk_store.close()

    def ingest_to_neo4j(
        self,
        parse_result: ParseResult,
        extraction: EntityExtractionResult,
        *,
        document_category: str,
        source_file: Path,
        force_reingest: bool | None = None,
        on_progress: ProgressCallback | None = None,
        run_graphiti: bool | None = None,
    ) -> IngestStats:
        force = settings.force_reingest if force_reingest is None else force_reingest
        graphiti_enabled = (
            settings.enable_graphiti_enrichment if run_graphiti is None else run_graphiti
        )

        parsed = to_legacy_parsed_document(parse_result)
        if not parsed.full_text.strip():
            raise ValueError("Документ не содержит текста для загрузки в БД")

        content_hash = compute_file_content_hash(source_file)
        group_id = document_group_id(content_hash)

        checkpoint = self.checkpoint.get_or_create(
            group_id=group_id,
            source_path=str(parse_result.source_path),
            content_hash=content_hash,
            document_category=document_category,
        )

        if self.checkpoint.is_completed(group_id, content_hash) and not force:
            logger.info("Документ уже загружен (group_id=%s), пропуск", group_id)
            self.checkpoint.mark_skipped(group_id)
            return IngestStats(
                source_path=str(parse_result.source_path),
                group_id=group_id,
                document_category=document_category,
                content_hash=content_hash,
                chunks_total=checkpoint.graphiti_chunks_total,
                chunks_saved=checkpoint.graphiti_chunks_total,
                entities_saved=0,
                relations_saved=0,
                original_storage_path=None,
                prepared_document_path=parse_result.prepared_document_path,
                document_node_created=False,
                skipped_reingest=True,
                graphiti_chunks_ingested=checkpoint.graphiti_chunks_ingested,
                graphiti_chunks_skipped=checkpoint.graphiti_chunks_total,
                graphiti_skipped=True,
                graphiti_skip_reason="already_ingested",
            )

        chunks = chunk_document(parsed, group_id=group_id)
        if not chunks:
            raise ValueError("Не удалось создать чанки для RAG")

        blocks = document_to_blocks(parsed)
        self.checkpoint.mark_processing(group_id)

        original_path = archive_original_document(source_file, group_id)

        self.chunk_store.ensure_schema()
        self.entity_store.ensure_schema()

        self.chunk_store.upsert_source_document(
            source_path=str(parse_result.source_path),
            group_id=group_id,
            doc_type=parse_result.doc_type,
            language_hint=parse_result.language_hint,
            document_category=document_category,
            document_title=Path(parse_result.source_path).name,
            chunks_count=len(chunks),
            content_hash=content_hash,
            original_storage_path=str(original_path),
            prepared_document_path=parse_result.prepared_document_path,
        )
        self.chunk_store.upsert_lexical_blocks(group_id, blocks)

        chunks_saved = self._save_chunks_with_embeddings(chunks)
        self.checkpoint.mark_neo4j_complete(group_id, chunks_total=len(chunks))

        all_entities = extraction.entities + extraction.other_entities
        entity_vectors = embed_texts(
            [IngestedEntityStore.embedding_input(e) for e in all_entities]
        ) if all_entities else []

        entities_saved, relations_saved = self.entity_store.save_extraction(
            group_id,
            extraction,
            entity_vectors,
        )

        graphiti_stats = None
        if graphiti_enabled:
            from app.ingestion.graphiti_enrichment import enrich_document_with_graphiti

            graphiti_stats = enrich_document_with_graphiti(
                chunks,
                group_id=group_id,
                checkpoint=self.checkpoint,
                on_progress=on_progress,
            )

        self.checkpoint.mark_completed(group_id)

        logger.info(
            "Neo4j ingest: group=%s chunks=%s entities=%s relations=%s",
            group_id,
            chunks_saved,
            entities_saved,
            relations_saved,
        )

        return IngestStats(
            source_path=str(parse_result.source_path),
            group_id=group_id,
            document_category=document_category,
            content_hash=content_hash,
            chunks_total=len(chunks),
            chunks_saved=chunks_saved,
            entities_saved=entities_saved,
            relations_saved=relations_saved,
            original_storage_path=str(original_path),
            prepared_document_path=parse_result.prepared_document_path,
            document_node_created=True,
            graphiti_chunks_ingested=graphiti_stats.chunks_ingested if graphiti_stats else 0,
            graphiti_chunks_skipped=graphiti_stats.chunks_skipped if graphiti_stats else 0,
            graphiti_skipped=graphiti_stats.skipped if graphiti_stats else True,
            graphiti_skip_reason=graphiti_stats.skip_reason if graphiti_stats else "disabled",
        )

    def _save_chunks_with_embeddings(self, chunks: list[TextChunk]) -> int:
        batch_size = max(1, settings.ingestion_batch_size)
        saved = 0
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            vectors = embed_texts([c.text for c in batch])
            saved += self.chunk_store.save_chunk_batch(batch, vectors)
        return saved
