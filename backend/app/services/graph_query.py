"""
Cypher-запросы к графу знаний (Graphiti + DictEntity).

Поддерживает обход связей доменной онтологии и проверку схемы.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import settings
from app.core.neo4j import get_neo4j_driver
from app.ontology import ENTITY_TYPE_NAMES, RELATION_TYPE_NAMES


@dataclass
class EntitySummary:
    uuid: str
    name: str
    entity_type: str
    group_id: str | None = None


@dataclass
class RelationSummary:
    uuid: str
    name: str
    fact: str | None
    source_name: str
    target_name: str
    source_type: str | None
    target_type: str | None


@dataclass
class GraphStats:
    entity_counts: dict[str, int]
    relation_counts: dict[str, int]
    dict_entity_count: int
    episodic_count: int


def _entity_type_from_labels(labels: list[str]) -> str:
    for label in ENTITY_TYPE_NAMES:
        if label in labels:
            return label
    return "Entity"


class GraphQueryService:
    def __init__(self, group_id: str | None = None) -> None:
        self.group_id = group_id or settings.graphiti_group_id

    def get_stats(self) -> GraphStats:
        with get_neo4j_driver().session() as session:
            entity_counts: dict[str, int] = {}
            for entity_type in ENTITY_TYPE_NAMES:
                row = session.run(
                    f"""
                    MATCH (n:Entity:{entity_type})
                    WHERE n.group_id = $group_id OR $group_id IS NULL
                    RETURN count(n) AS c
                    """,
                    group_id=self.group_id,
                ).single()
                entity_counts[entity_type] = int(row["c"]) if row else 0

            relation_counts: dict[str, int] = {}
            for rel_name in RELATION_TYPE_NAMES:
                row = session.run(
                    """
                    MATCH ()-[r:RELATES_TO]->()
                    WHERE r.name = $rel_name
                      AND (r.group_id = $group_id OR $group_id IS NULL)
                      AND r.invalid_at IS NULL
                    RETURN count(r) AS c
                    """,
                    rel_name=rel_name,
                    group_id=self.group_id,
                ).single()
                relation_counts[rel_name] = int(row["c"]) if row else 0

            dict_row = session.run("MATCH (n:DictEntity) RETURN count(n) AS c").single()
            episodic_row = session.run(
                """
                MATCH (e:Episodic)
                WHERE e.group_id = $group_id OR $group_id IS NULL
                RETURN count(e) AS c
                """,
                group_id=self.group_id,
            ).single()

        return GraphStats(
            entity_counts=entity_counts,
            relation_counts=relation_counts,
            dict_entity_count=int(dict_row["c"]) if dict_row else 0,
            episodic_count=int(eppisodic_row["c"]) if episodic_row else 0,
        )

    def find_entities(
        self,
        name_pattern: str,
        entity_type: str | None = None,
        limit: int = 20,
    ) -> list[EntitySummary]:
        type_clause = f":{entity_type}" if entity_type else ""
        with get_neo4j_driver().session() as session:
            result = session.run(
                f"""
                MATCH (n:Entity{type_clause})
                WHERE toLower(n.name) CONTAINS toLower($pattern)
                  AND (n.group_id = $group_id OR $group_id IS NULL)
                RETURN n.uuid AS uuid, n.name AS name, labels(n) AS labels, n.group_id AS group_id
                ORDER BY n.name
                LIMIT $limit
                """,
                pattern=name_pattern,
                group_id=self.group_id,
                limit=limit,
            )
            entities: list[EntitySummary] = []
            for row in result:
                labels = list(row["labels"] or [])
                entities.append(
                    EntitySummary(
                        uuid=row["uuid"],
                        name=row["name"],
                        entity_type=_entity_type_from_labels(labels),
                        group_id=row["group_id"],
                    )
                )
            return entities

    def traverse_from_entity(
        self,
        entity_name: str,
        relation_types: list[str] | None = None,
        max_hops: int = 2,
        limit: int = 50,
    ) -> list[RelationSummary]:
        rel_filter = relation_types or list(RELATION_TYPE_NAMES)
        hops = min(max(1, max_hops), 3)
        with get_neo4j_driver().session() as session:
            result = session.run(
                f"""
                MATCH path = (start:Entity {{name: $name}})-[:RELATES_TO*1..{hops}]-(end:Entity)
                WHERE ALL(rel IN relationships(path) WHERE rel.name IN $rel_types)
                  AND ALL(rel IN relationships(path) WHERE rel.invalid_at IS NULL)
                  AND (start.group_id = $group_id OR $group_id IS NULL)
                WITH relationships(path) AS rels, nodes(path) AS nodes
                UNWIND range(0, size(rels)-1) AS i
                WITH rels[i] AS r, nodes[i] AS src, nodes[i+1] AS tgt
                RETURN DISTINCT r.uuid AS uuid,
                       r.name AS name,
                       r.fact AS fact,
                       src.name AS source_name,
                       tgt.name AS target_name,
                       labels(src) AS source_labels,
                       labels(tgt) AS target_labels
                LIMIT $limit
                """,
                name=entity_name,
                rel_types=rel_filter,
                group_id=self.group_id,
                limit=limit,
            )
            return [
                RelationSummary(
                    uuid=row["uuid"],
                    name=row["name"],
                    fact=row["fact"],
                    source_name=row["source_name"],
                    target_name=row["target_name"],
                    source_type=_entity_type_from_labels(list(row["source_labels"] or [])),
                    target_type=_entity_type_from_labels(list(row["target_labels"] or [])),
                )
                for row in result
            ]

    def get_publications_for_entity(self, entity_name: str, limit: int = 20) -> list[RelationSummary]:
        with get_neo4j_driver().session() as session:
            result = session.run(
                """
                MATCH (src:Entity {name: $name})-[r:RELATES_TO {name: 'described_in'}]->(pub:Entity:Publication)
                WHERE r.invalid_at IS NULL
                  AND (src.group_id = $group_id OR $group_id IS NULL)
                RETURN r.uuid AS uuid, r.name AS name, r.fact AS fact,
                       src.name AS source_name, pub.name AS target_name,
                       labels(src) AS source_labels, labels(pub) AS target_labels
                LIMIT $limit
                """,
                name=entity_name,
                group_id=self.group_id,
                limit=limit,
            )
            return [
                RelationSummary(
                    uuid=row["uuid"],
                    name=row["name"],
                    fact=row["fact"],
                    source_name=row["source_name"],
                    target_name=row["target_name"],
                    source_type=_entity_type_from_labels(list(row["source_labels"] or [])),
                    target_type="Publication",
                )
                for row in result
            ]

    def verify_ontology_constraints(self) -> dict[str, bool]:
        """Проверяет наличие узлов/связей доменной онтологии в графе."""
        stats = self.get_stats()
        entities_ok = any(count > 0 for count in stats.entity_counts.values())
        relations_ok = any(count > 0 for count in stats.relation_counts.values())
        return {
            "neo4j_connected": True,
            "entity_types_defined": len(ENTITY_TYPE_NAMES) == 8,
            "relation_types_defined": len(RELATION_TYPE_NAMES) == 6,
            "graph_has_entities": entities_ok,
            "graph_has_relations": relations_ok,
        }
