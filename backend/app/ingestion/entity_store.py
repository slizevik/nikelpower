"""Сохранение извлечённых сущностей и связей в Neo4j."""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone

from neo4j import Driver

from app.config import settings
from app.core.neo4j import get_neo4j_driver
from app.models.extraction import EntityExtractionResult, ExtractedEntity, ExtractedRelation
from app.ingestion.relation_inference import infer_relations, merge_relations

logger = logging.getLogger(__name__)

INGESTED_ENTITY_INDEX = "ingested_entity_embedding"


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.lower().strip())


def _resolve_entity_id(
    name: str,
    entity_type: str,
    id_by_key: dict[tuple[str, str], str],
) -> str | None:
    name_l = _normalize_name(name)
    exact = id_by_key.get((entity_type, name_l))
    if exact:
        return exact
    for (etype, ename), eid in id_by_key.items():
        if ename == name_l:
            return eid

    fuzzy: list[str] = []
    for (_, ename), eid in id_by_key.items():
        if len(name_l) >= 4 and (name_l in ename or ename in name_l):
            fuzzy.append(eid)
    if len(fuzzy) == 1:
        return fuzzy[0]
    return None


class IngestedEntityStore:
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
                "CREATE CONSTRAINT ingested_entity_id IF NOT EXISTS "
                "FOR (n:IngestedEntity) REQUIRE n.id IS UNIQUE"
            )
            session.run(
                f"""
                CREATE VECTOR INDEX {INGESTED_ENTITY_INDEX} IF NOT EXISTS
                FOR (n:IngestedEntity)
                ON (n.embedding)
                OPTIONS {{indexConfig: {{
                    `vector.dimensions`: $dims,
                    `vector.similarity_function`: 'cosine'
                }}}}
                """,
                dims=settings.embedding_dimensions,
            )

    def clear_document_entities(self, group_id: str) -> None:
        with self.driver.session() as session:
            session.run(
                """
                MATCH (d:SourceDocument {group_id: $group_id})-[:HAS_INGESTED_ENTITY]->(e:IngestedEntity)
                DETACH DELETE e
                """,
                group_id=group_id,
            )

    def save_extraction(
        self,
        group_id: str,
        extraction: EntityExtractionResult,
        entity_embeddings: list[list[float]],
    ) -> tuple[int, int]:
        all_entities = extraction.entities + extraction.other_entities
        if len(all_entities) != len(entity_embeddings):
            raise ValueError("Число сущностей и эмбеддингов должно совпадать")

        relations = merge_relations(
            extraction.relations,
            infer_relations(all_entities),
        )

        now = datetime.now(timezone.utc).isoformat()
        self.clear_document_entities(group_id)

        id_by_key: dict[tuple[str, str], str] = {}
        saved_entities = 0

        with self.driver.session() as session:
            for entity, vector in zip(all_entities, entity_embeddings):
                entity_id = str(uuid.uuid4())
                key = (entity.entity_type, entity.name.lower())
                id_by_key[key] = entity_id

                session.run(
                    """
                    MATCH (d:SourceDocument {group_id: $group_id})
                    CREATE (e:IngestedEntity {
                        id: $id,
                        name: $name,
                        entity_type: $entity_type,
                        evidence: $evidence,
                        attributes_json: $attributes_json,
                        embedding: $embedding,
                        group_id: $group_id,
                        created_at: $now
                    })
                    MERGE (d)-[:HAS_INGESTED_ENTITY]->(e)
                    """,
                    group_id=group_id,
                    id=entity_id,
                    name=entity.name,
                    entity_type=entity.entity_type,
                    evidence=entity.evidence,
                    attributes_json=json.dumps(entity.attributes, ensure_ascii=False),
                    embedding=vector,
                    now=now,
                )
                saved_entities += 1

            saved_relations = 0
            for rel in relations:
                source_id = _resolve_entity_id(rel.source_name, rel.source_type, id_by_key)
                target_id = _resolve_entity_id(rel.target_name, rel.target_type, id_by_key)
                if not source_id or not target_id:
                    continue

                session.run(
                    """
                    MATCH (a:IngestedEntity {id: $source_id})
                    MATCH (b:IngestedEntity {id: $target_id})
                    MERGE (a)-[r:INGESTED_RELATION {relation_type: $relation_type}]->(b)
                    SET r.evidence = $evidence,
                        r.attributes_json = $attributes_json,
                        r.updated_at = $now
                    """,
                    source_id=source_id,
                    target_id=target_id,
                    relation_type=rel.relation_type,
                    evidence=rel.evidence,
                    attributes_json=json.dumps(rel.attributes, ensure_ascii=False),
                    now=now,
                )
                saved_relations += 1

        return saved_entities, saved_relations

    def backfill_inferred_relations(self) -> tuple[int, int]:
        """Добавляет выведенные связи для уже загруженных документов."""
        groups_added = 0
        relations_added = 0

        with self.driver.session() as session:
            group_rows = session.run(
                "MATCH (d:SourceDocument) RETURN DISTINCT d.group_id AS group_id"
            )
            group_ids = [row["group_id"] for row in group_rows if row.get("group_id")]

        for group_id in group_ids:
            with self.driver.session() as session:
                entity_rows = session.run(
                    """
                    MATCH (d:SourceDocument {group_id: $group_id})-[:HAS_INGESTED_ENTITY]->(e:IngestedEntity)
                    RETURN e.id AS id, e.name AS name, e.entity_type AS entity_type, e.evidence AS evidence
                    """,
                    group_id=group_id,
                ).data()
                if len(entity_rows) < 2:
                    continue

                existing = session.run(
                    """
                    MATCH (a:IngestedEntity {group_id: $group_id})-[r:INGESTED_RELATION]->(b:IngestedEntity)
                    RETURN a.name AS source_name, b.name AS target_name, r.relation_type AS relation_type
                    """,
                    group_id=group_id,
                ).data()

            entities = [
                ExtractedEntity(
                    entity_type=row["entity_type"],
                    name=row["name"],
                    evidence=row.get("evidence"),
                )
                for row in entity_rows
            ]
            id_by_name = {row["name"].lower(): row["id"] for row in entity_rows}

            existing_keys = {
                (
                    row["relation_type"],
                    (row.get("source_name") or "").lower(),
                    (row.get("target_name") or "").lower(),
                )
                for row in existing
            }
            inferred = infer_relations(entities)
            new_relations = [
                rel
                for rel in inferred
                if (rel.relation_type, rel.source_name.lower(), rel.target_name.lower()) not in existing_keys
            ]
            if not new_relations:
                continue

            now = datetime.now(timezone.utc).isoformat()
            id_by_key = {
                (entity.entity_type, entity.name.lower()): id_by_name[entity.name.lower()]
                for entity in entities
                if entity.name.lower() in id_by_name
            }

            added_for_group = 0
            with self.driver.session() as session:
                for rel in new_relations:
                    source_id = _resolve_entity_id(rel.source_name, rel.source_type, id_by_key)
                    target_id = _resolve_entity_id(rel.target_name, rel.target_type, id_by_key)
                    if not source_id or not target_id or source_id == target_id:
                        continue

                    session.run(
                        """
                        MATCH (a:IngestedEntity {id: $source_id})
                        MATCH (b:IngestedEntity {id: $target_id})
                        MERGE (a)-[r:INGESTED_RELATION {relation_type: $relation_type}]->(b)
                        SET r.evidence = coalesce(r.evidence, $evidence),
                            r.attributes_json = $attributes_json,
                            r.updated_at = $now
                        """,
                        source_id=source_id,
                        target_id=target_id,
                        relation_type=rel.relation_type,
                        evidence=rel.evidence,
                        attributes_json=json.dumps(rel.attributes, ensure_ascii=False),
                        now=now,
                    )
                    added_for_group += 1

            if added_for_group:
                groups_added += 1
                relations_added += added_for_group

        return groups_added, relations_added

    @staticmethod
    def embedding_input(entity: ExtractedEntity) -> str:
        parts = [entity.entity_type, entity.name]
        if entity.evidence:
            parts.append(entity.evidence)
        return " | ".join(parts)

    def search_by_embedding(self, query: str, top_k: int = 10) -> list[dict]:
        from app.dictionary.embeddings import embed_text

        vector = embed_text(query)
        with self.driver.session() as session:
            result = session.run(
                """
                CALL db.index.vector.queryNodes($index_name, $top_k, $embedding)
                YIELD node, score
                RETURN node.id AS id,
                       node.name AS name,
                       node.entity_type AS entity_type,
                       score
                ORDER BY score DESC
                """,
                index_name=INGESTED_ENTITY_INDEX,
                top_k=top_k,
                embedding=vector,
            )
            return [dict(row) for row in result]

    def find_group_ids_by_geo(self, geo: str) -> list[str] | None:
        """geo: all → None (без фильтра), russia | foreign → список group_id."""
        if geo in ("", "all"):
            return None

        with self.driver.session() as session:
            if geo == "russia":
                result = session.run(
                    """
                    MATCH (d:SourceDocument)-[:HAS_INGESTED_ENTITY]->(e:IngestedEntity)
                    WHERE e.entity_type IN ['Expert', 'Publication', 'Facility']
                      AND (
                        toLower(coalesce(e.attributes_json, '')) CONTAINS '"is_russian": true'
                        OR toLower(coalesce(e.attributes_json, '')) CONTAINS '"is_russian":true'
                        OR toLower(coalesce(e.attributes_json, '')) CONTAINS 'росси'
                        OR toLower(coalesce(e.evidence, '')) CONTAINS 'росси'
                        OR toLower(e.name) CONTAINS 'росси'
                      )
                    RETURN DISTINCT d.group_id AS group_id
                    """
                )
            else:
                result = session.run(
                    """
                    MATCH (d:SourceDocument)-[:HAS_INGESTED_ENTITY]->(e:IngestedEntity)
                    WHERE e.entity_type IN ['Expert', 'Publication', 'Facility']
                      AND (
                        toLower(coalesce(e.attributes_json, '')) CONTAINS 'foreign'
                        OR toLower(coalesce(e.attributes_json, '')) CONTAINS 'зарубеж'
                        OR toLower(coalesce(e.evidence, '')) CONTAINS 'international'
                      )
                    RETURN DISTINCT d.group_id AS group_id
                    """
                )
            return [row["group_id"] for row in result if row.get("group_id")]

    def get_authors_for_document(self, group_id: str) -> list[str]:
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (d:SourceDocument {group_id: $group_id})-[:HAS_INGESTED_ENTITY]->(e:IngestedEntity)
                WHERE e.entity_type IN ['Expert', 'Publication']
                RETURN e.name AS name, e.entity_type AS entity_type,
                       e.attributes_json AS attributes_json
                ORDER BY e.entity_type, e.name
                LIMIT 10
                """,
                group_id=group_id,
            )
            authors: list[str] = []
            for row in result:
                name = (row.get("name") or "").strip()
                if name and name not in authors:
                    authors.append(name)
            return authors
