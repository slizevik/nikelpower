"""Сохранение извлечённых сущностей и связей в Neo4j."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from neo4j import Driver

from app.config import settings
from app.core.neo4j import get_neo4j_driver
from app.models.extraction import EntityExtractionResult, ExtractedEntity, ExtractedRelation

logger = logging.getLogger(__name__)

INGESTED_ENTITY_INDEX = "ingested_entity_embedding"


def _resolve_entity_id(
    name: str,
    entity_type: str,
    id_by_key: dict[tuple[str, str], str],
) -> str | None:
    name_l = name.lower()
    exact = id_by_key.get((entity_type, name_l))
    if exact:
        return exact
    for (etype, ename), eid in id_by_key.items():
        if ename == name_l:
            return eid
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
            for rel in extraction.relations:
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

    @staticmethod
    def embedding_input(entity: ExtractedEntity) -> str:
        parts = [entity.entity_type, entity.name]
        if entity.evidence:
            parts.append(entity.evidence)
        return " | ".join(parts)
