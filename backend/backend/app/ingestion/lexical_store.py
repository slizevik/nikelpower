"""Запись lexical graph (ParagraphBlock → :LexicalNode) в Neo4j."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from neo4j import Driver

from app.core.neo4j import get_neo4j_driver
from app.ingestion.lexical import ParagraphBlock

logger = logging.getLogger(__name__)


class LexicalNodeStore:
    def __init__(self, driver: Driver | None = None) -> None:
        self._driver = driver

    @property
    def driver(self) -> Driver:
        if self._driver is None:
            self._driver = get_neo4j_driver()
        return self._driver

    def ensure_schema(self) -> None:
        with self.driver.session() as session:
            session.run(
                "CREATE CONSTRAINT lexical_node_id IF NOT EXISTS "
                "FOR (n:LexicalNode) REQUIRE n.node_id IS UNIQUE"
            )

    def upsert_blocks(self, group_id: str, blocks: list[ParagraphBlock]) -> None:
        if not blocks:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self.driver.session() as session:
            for block in blocks:
                session.run(
                    """
                    MATCH (d:SourceDocument {group_id: $group_id})
                    MERGE (l:LexicalNode {node_id: $node_id})
                    SET l.page = $page,
                        l.order_index = $order_index,
                        l.block_type = $block_type,
                        l.section_hint = $section_hint,
                        l.text_preview = $text_preview,
                        l.group_id = $group_id,
                        l.updated_at = $now
                    MERGE (d)-[:HAS_LEXICAL_NODE]->(l)
                    """,
                    group_id=group_id,
                    node_id=block.block_id,
                    page=block.page,
                    order_index=block.order_index,
                    block_type=block.block_type,
                    section_hint=block.section_hint,
                    text_preview=block.text[:500],
                    now=now,
                )
            for prev, nxt in zip(blocks, blocks[1:]):
                session.run(
                    """
                    MATCH (a:LexicalNode {node_id: $prev_id})
                    MATCH (b:LexicalNode {node_id: $next_id})
                    MERGE (a)-[:NEXT]->(b)
                    """,
                    prev_id=prev.block_id,
                    next_id=nxt.block_id,
                )

    def link_chunk_to_blocks(self, chunk_id: str, block_ids: list[str]) -> None:
        with self.driver.session() as session:
            for node_id in block_ids:
                session.run(
                    """
                    MATCH (c:DocumentChunk {chunk_id: $chunk_id})
                    MATCH (l:LexicalNode {node_id: $node_id})
                    MERGE (c)-[:CONTAINS]->(l)
                    """,
                    chunk_id=chunk_id,
                    node_id=node_id,
                )
