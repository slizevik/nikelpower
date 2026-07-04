"""Хранение DocumentChunk и SourceDocument в Neo4j для RAG."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from neo4j import Driver

from app.config import settings
from app.core.neo4j import get_neo4j_driver
from app.ingestion.lexical import ParagraphBlock
from app.ingestion.lexical_store import LexicalNodeStore
from app.models.chunk import TextChunk

logger = logging.getLogger(__name__)

CHUNK_VECTOR_INDEX = "document_chunk_embedding"


@dataclass
class IngestStats:
    source_path: str
    group_id: str
    document_category: str
    chunks_total: int
    chunks_saved: int
    entities_saved: int
    relations_saved: int
    content_hash: str = ""
    original_storage_path: str | None = None
    prepared_document_path: str | None = None
    document_node_created: bool = False
    skipped_reingest: bool = False
    graphiti_chunks_ingested: int = 0
    graphiti_chunks_skipped: int = 0
    graphiti_skipped: bool = False
    graphiti_skip_reason: str | None = None


class DocumentChunkStore:
    def __init__(self, driver: Driver | None = None) -> None:
        self._driver = driver
        self._lexical = LexicalNodeStore(driver)

    @property
    def lexical_store(self) -> LexicalNodeStore:
        return self._lexical

    @property
    def driver(self) -> Driver:
        if self._driver is None:
            self._driver = get_neo4j_driver()
            self._lexical._driver = self._driver
        return self._driver

    def close(self) -> None:
        pass

    def ensure_schema(self) -> None:
        self._lexical.ensure_schema()
        with self.driver.session() as session:
            session.run(
                "CREATE CONSTRAINT document_chunk_id IF NOT EXISTS "
                "FOR (c:DocumentChunk) REQUIRE c.chunk_id IS UNIQUE"
            )
            session.run(
                "CREATE CONSTRAINT source_document_group IF NOT EXISTS "
                "FOR (d:SourceDocument) REQUIRE d.group_id IS UNIQUE"
            )
            session.run(
                f"""
                CREATE VECTOR INDEX {CHUNK_VECTOR_INDEX} IF NOT EXISTS
                FOR (c:DocumentChunk)
                ON (c.embedding)
                OPTIONS {{indexConfig: {{
                    `vector.dimensions`: $dims,
                    `vector.similarity_function`: 'cosine'
                }}}}
                """,
                dims=settings.embedding_dimensions,
            )

    def upsert_lexical_blocks(self, group_id: str, blocks: list[ParagraphBlock]) -> None:
        self._lexical.upsert_blocks(group_id, blocks)

    def upsert_source_document(
        self,
        *,
        source_path: str,
        group_id: str,
        doc_type: str,
        language_hint: str,
        document_category: str,
        document_title: str,
        chunks_count: int,
        content_hash: str | None = None,
        original_storage_path: str | None = None,
        prepared_document_path: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.driver.session() as session:
            session.run(
                """
                MERGE (d:SourceDocument {group_id: $group_id})
                SET d.source_path = $source_path,
                    d.doc_type = $doc_type,
                    d.language_hint = $language_hint,
                    d.document_category = $document_category,
                    d.document_title = $document_title,
                    d.chunks_count = $chunks_count,
                    d.content_hash = $content_hash,
                    d.original_storage_path = $original_storage_path,
                    d.prepared_document_path = $prepared_document_path,
                    d.updated_at = $now
                """,
                group_id=group_id,
                source_path=source_path,
                doc_type=doc_type,
                language_hint=language_hint,
                document_category=document_category,
                document_title=document_title,
                chunks_count=chunks_count,
                content_hash=content_hash,
                original_storage_path=original_storage_path,
                prepared_document_path=prepared_document_path,
                now=now,
            )

    def save_chunk_batch(
        self,
        chunks: list[TextChunk],
        embeddings: list[list[float]],
    ) -> int:
        if len(chunks) != len(embeddings):
            raise ValueError("Число чанков и эмбеддингов должно совпадать")

        now = datetime.now(timezone.utc).isoformat()
        saved = 0

        with self.driver.session() as session:
            for chunk, vector in zip(chunks, embeddings):
                session.run(
                    """
                    MATCH (d:SourceDocument {group_id: $group_id})
                    MERGE (c:DocumentChunk {chunk_id: $chunk_id})
                    SET c.text = $text,
                        c.chunk_index = $chunk_index,
                        c.page_start = $page_start,
                        c.page_end = $page_end,
                        c.doc_type = $doc_type,
                        c.language_hint = $language_hint,
                        c.source_path = $source_path,
                        c.embedding = $embedding,
                        c.chunk_role = $chunk_role,
                        c.block_ids = $block_ids,
                        c.token_count = $token_count,
                        c.section_hint = $section_hint,
                        c.group_id = $group_id,
                        c.updated_at = $now
                    MERGE (d)-[:HAS_CHUNK]->(c)
                    """,
                    group_id=chunk.group_id,
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    chunk_index=chunk.chunk_index,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    doc_type=chunk.doc_type,
                    language_hint=chunk.language_hint,
                    source_path=chunk.source_path,
                    embedding=vector,
                    chunk_role=chunk.chunk_role,
                    block_ids=chunk.block_ids,
                    token_count=chunk.token_count,
                    section_hint=chunk.section_hint,
                    now=now,
                )
                if chunk.block_ids:
                    self._lexical.link_chunk_to_blocks(chunk.chunk_id, chunk.block_ids)
                saved += 1

        return saved

    def search_chunks(
        self,
        embedding: list[float],
        top_k: int = 5,
        group_id: str | None = None,
    ) -> list[dict]:
        with self.driver.session() as session:
            if group_id:
                result = session.run(
                    f"""
                    CALL db.index.vector.queryNodes($index_name, $top_k, $embedding)
                    YIELD node, score
                    WHERE node.group_id = $group_id
                    MATCH (d:SourceDocument {group_id: $group_id})-[:HAS_CHUNK]->(node)
                    RETURN node.chunk_id AS chunk_id,
                           node.text AS text,
                           node.source_path AS source_path,
                           node.page_start AS page_start,
                           node.page_end AS page_end,
                           d.document_category AS document_category,
                           d.document_title AS document_title,
                           score
                    ORDER BY score DESC
                    """,
                    index_name=CHUNK_VECTOR_INDEX,
                    top_k=top_k,
                    embedding=embedding,
                    group_id=group_id,
                )
            else:
                result = session.run(
                    f"""
                    CALL db.index.vector.queryNodes($index_name, $top_k, $embedding)
                    YIELD node, score
                    OPTIONAL MATCH (d:SourceDocument {group_id: node.group_id})-[:HAS_CHUNK]->(node)
                    RETURN node.chunk_id AS chunk_id,
                           node.text AS text,
                           node.source_path AS source_path,
                           node.page_start AS page_start,
                           node.page_end AS page_end,
                           d.document_category AS document_category,
                           d.document_title AS document_title,
                           score
                    ORDER BY score DESC
                    """,
                    index_name=CHUNK_VECTOR_INDEX,
                    top_k=top_k,
                    embedding=embedding,
                )
            return [dict(row) for row in result]
