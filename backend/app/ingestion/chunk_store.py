"""
Хранение текстовых чанков документов в Neo4j с векторными эмбеддингами.

Узлы :DocumentChunk — фрагменты PDF/DOCX для семантического поиска.
Узлы :SourceDocument — исходный файл, связь HAS_CHUNK.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from neo4j import Driver, GraphDatabase

from app.config import settings
from app.ingestion.chunker import TextChunk
from app.ingestion.lexical import ParagraphBlock
from app.ingestion.lexical_store import LexicalNodeStore

logger = logging.getLogger(__name__)

CHUNK_VECTOR_INDEX = "document_chunk_embedding"


@dataclass
class IngestStats:
    source_path: str
    group_id: str
    chunks_total: int
    chunks_saved: int
    document_node_created: bool


class DocumentChunkStore:
    """Запись чанков и эмбеддингов в граф Neo4j."""

    def __init__(self, driver: Driver | None = None) -> None:
        self._driver = driver
        self._lexical = LexicalNodeStore(driver)

    @property
    def lexical_store(self) -> LexicalNodeStore:
        return self._lexical

    @property
    def driver(self) -> Driver:
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
            self._lexical._driver = self._driver
        return self._driver

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None
        self._lexical._driver = None

    def ensure_schema(self) -> None:
        """Создаёт ограничения и векторный индекс для DocumentChunk и LexicalNode."""
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
        logger.info("DocumentChunk schema ensured")

    def upsert_lexical_blocks(self, group_id: str, blocks: list[ParagraphBlock]) -> None:
        self._lexical.upsert_blocks(group_id, blocks)

    def upsert_source_document(
        self,
        source_path: str,
        group_id: str,
        doc_type: str,
        language_hint: str,
        chunks_count: int,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.driver.session() as session:
            session.run(
                """
                MERGE (d:SourceDocument {group_id: $group_id})
                SET d.source_path = $source_path,
                    d.doc_type = $doc_type,
                    d.language_hint = $language_hint,
                    d.chunks_count = $chunks_count,
                    d.updated_at = $now
                """,
                group_id=group_id,
                source_path=source_path,
                doc_type=doc_type,
                language_hint=language_hint,
                chunks_count=chunks_count,
                now=now,
            )

    def save_chunk_batch(
        self,
        chunks: list[TextChunk],
        embeddings: list[list[float]],
    ) -> int:
        """Сохраняет батч чанков с эмбеддингами и связью HAS_CHUNK."""
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

    def count_chunks_for_document(self, group_id: str) -> int:
        with self.driver.session() as session:
            row = session.run(
                """
                MATCH (d:SourceDocument {group_id: $group_id})-[:HAS_CHUNK]->(c)
                RETURN count(c) AS cnt
                """,
                group_id=group_id,
            ).single()
            return int(row["cnt"]) if row else 0
