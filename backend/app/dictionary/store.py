"""
Хранилище динамического словаря сущностей в Neo4j.

Узлы :DictEntity — живой словарь марок, сплавов, процессов и т.д.
Векторный индекс по полю embedding для поиска по сходству имён и алиасов.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from neo4j import GraphDatabase, Driver

from app.config import settings
from app.dictionary.embeddings import embed_text, embedding_input_for_entity

logger = logging.getLogger(__name__)

VECTOR_INDEX_NAME = "dict_entity_embedding"


@dataclass
class DictEntityRecord:
    id: str
    canonical_name: str
    entity_type: str
    aliases: list[str]
    score: float = 0.0
    mention_count: int = 1
    source_documents: list[str] | None = None


class EntityDictionaryStore:
    def __init__(self, driver: Driver | None = None) -> None:
        self._driver = driver

    @property
    def driver(self) -> Driver:
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
        return self._driver

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def ensure_schema(self) -> None:
        """Создаёт ограничения уникальности и векторный индекс."""
        with self.driver.session() as session:
            session.run(
                "CREATE CONSTRAINT dict_entity_id IF NOT EXISTS "
                "FOR (n:DictEntity) REQUIRE n.id IS UNIQUE"
            )
            session.run(
                "CREATE CONSTRAINT dict_entity_canonical IF NOT EXISTS "
                "FOR (n:DictEntity) REQUIRE n.canonical_name IS UNIQUE"
            )
            # Пересоздаём индекс при смене размерности (идемпотентно через IF NOT EXISTS)
            session.run(
                f"""
                CREATE VECTOR INDEX {VECTOR_INDEX_NAME} IF NOT EXISTS
                FOR (n:DictEntity)
                ON (n.embedding)
                OPTIONS {{indexConfig: {{
                    `vector.dimensions`: $dims,
                    `vector.similarity_function`: 'cosine'
                }}}}
                """,
                dims=settings.embedding_dimensions,
            )
        logger.info("DictEntity schema and vector index ensured")

    def find_similar(
        self,
        embedding: list[float],
        top_k: int = 10,
        min_score: float | None = None,
    ) -> list[DictEntityRecord]:
        threshold = min_score if min_score is not None else 0.0
        with self.driver.session() as session:
            result = session.run(
                f"""
                CALL db.index.vector.queryNodes($index_name, $top_k, $embedding)
                YIELD node, score
                WHERE score >= $min_score
                RETURN node.id AS id,
                       node.canonical_name AS canonical_name,
                       node.entity_type AS entity_type,
                       node.aliases AS aliases,
                       node.mention_count AS mention_count,
                       node.source_documents AS source_documents,
                       score
                ORDER BY score DESC
                """,
                index_name=VECTOR_INDEX_NAME,
                top_k=top_k,
                embedding=embedding,
                min_score=threshold,
            )
            records = []
            for row in result:
                records.append(
                    DictEntityRecord(
                        id=row["id"],
                        canonical_name=row["canonical_name"],
                        entity_type=row["entity_type"] or "Material",
                        aliases=list(row["aliases"] or []),
                        mention_count=row["mention_count"] or 1,
                        source_documents=list(row["source_documents"] or []),
                        score=row["score"],
                    )
                )
            return records

    def get_by_canonical_name(self, name: str) -> DictEntityRecord | None:
        with self.driver.session() as session:
            row = session.run(
                """
                MATCH (n:DictEntity {canonical_name: $name})
                RETURN n.id AS id, n.canonical_name AS canonical_name,
                       n.entity_type AS entity_type, n.aliases AS aliases,
                       n.mention_count AS mention_count,
                       n.source_documents AS source_documents
                """,
                name=name,
            ).single()
            if not row:
                return None
            return DictEntityRecord(
                id=row["id"],
                canonical_name=row["canonical_name"],
                entity_type=row["entity_type"] or "Material",
                aliases=list(row["aliases"] or []),
                mention_count=row["mention_count"] or 1,
                source_documents=list(row["source_documents"] or []),
            )

    def upsert_entity(
        self,
        canonical_name: str,
        entity_type: str,
        aliases: list[str] | None = None,
        source_document: str | None = None,
        embedding: list[float] | None = None,
    ) -> DictEntityRecord:
        """
        Добавляет сущность или дополняет алиасы существующей.
        Перед созданием ищет похожую запись по вектору.
        """
        aliases = [a.strip() for a in (aliases or []) if a.strip()]
        text_for_embed = embedding_input_for_entity(canonical_name, aliases)
        vector = embedding or embed_text(text_for_embed)

        similar = self.find_similar(
            vector,
            top_k=1,
            min_score=settings.embedding_similarity_threshold,
        )
        now = datetime.now(timezone.utc).isoformat()

        if similar:
            return self._merge_into_existing(
                similar[0], canonical_name, aliases, source_document, vector, now
            )
        return self._create_new(
            canonical_name, entity_type, aliases, source_document, vector, now
        )

    def _merge_into_existing(
        self,
        existing: DictEntityRecord,
        new_name: str,
        new_aliases: list[str],
        source_document: str | None,
        vector: list[float],
        now: str,
    ) -> DictEntityRecord:
        merged_aliases = list(
            dict.fromkeys(
                existing.aliases
                + new_aliases
                + ([new_name] if new_name != existing.canonical_name else [])
            )
        )
        docs = list(existing.source_documents or [])
        if source_document and source_document not in docs:
            docs.append(source_document)

        with self.driver.session() as session:
            session.run(
                """
                MATCH (n:DictEntity {id: $id})
                SET n.aliases = $aliases,
                    n.mention_count = coalesce(n.mention_count, 0) + 1,
                    n.source_documents = $source_documents,
                    n.embedding = $embedding,
                    n.updated_at = $now
                """,
                id=existing.id,
                aliases=merged_aliases,
                source_documents=docs,
                embedding=vector,
                now=now,
            )
        logger.info(
            "Merged '%s' into existing DictEntity '%s'",
            new_name,
            existing.canonical_name,
        )
        return DictEntityRecord(
            id=existing.id,
            canonical_name=existing.canonical_name,
            entity_type=existing.entity_type,
            aliases=merged_aliases,
            mention_count=existing.mention_count + 1,
            source_documents=docs,
        )

    def _create_new(
        self,
        canonical_name: str,
        entity_type: str,
        aliases: list[str],
        source_document: str | None,
        vector: list[float],
        now: str,
    ) -> DictEntityRecord:
        entity_id = str(uuid.uuid4())
        docs = [source_document] if source_document else []

        with self.driver.session() as session:
            session.run(
                """
                CREATE (n:DictEntity {
                    id: $id,
                    canonical_name: $canonical_name,
                    entity_type: $entity_type,
                    aliases: $aliases,
                    embedding: $embedding,
                    mention_count: 1,
                    source_documents: $source_documents,
                    created_at: $now,
                    updated_at: $now
                })
                """,
                id=entity_id,
                canonical_name=canonical_name,
                entity_type=entity_type,
                aliases=aliases,
                embedding=vector,
                source_documents=docs,
                now=now,
            )
        logger.info("Created DictEntity '%s' (%s)", canonical_name, entity_type)
        return DictEntityRecord(
            id=entity_id,
            canonical_name=canonical_name,
            entity_type=entity_type,
            aliases=aliases,
            mention_count=1,
            source_documents=docs,
        )

    def list_entities(self, limit: int = 100, entity_type: str | None = None) -> list[DictEntityRecord]:
        type_filter = "WHERE n.entity_type = $entity_type" if entity_type else ""
        with self.driver.session() as session:
            result = session.run(
                f"""
                MATCH (n:DictEntity)
                {type_filter}
                RETURN n.id AS id, n.canonical_name AS canonical_name,
                       n.entity_type AS entity_type, n.aliases AS aliases,
                       n.mention_count AS mention_count,
                       n.source_documents AS source_documents
                ORDER BY n.mention_count DESC, n.canonical_name
                LIMIT $limit
                """,
                limit=limit,
                entity_type=entity_type,
            )
            return [
                DictEntityRecord(
                    id=row["id"],
                    canonical_name=row["canonical_name"],
                    entity_type=row["entity_type"] or "Material",
                    aliases=list(row["aliases"] or []),
                    mention_count=row["mention_count"] or 1,
                    source_documents=list(row["source_documents"] or []),
                )
                for row in result
            ]

    def count(self) -> int:
        with self.driver.session() as session:
            row = session.run("MATCH (n:DictEntity) RETURN count(n) AS c").single()
            return int(row["c"]) if row else 0
