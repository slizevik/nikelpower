#!/usr/bin/env python3
"""
Инициализация схемы БД: Graphiti indices + DictEntity vector index.

Запуск локально:
    cd backend && ..\\.venv\\Scripts\\python.exe scripts/init_graph_db.py

В контейнере graphiti:
    docker compose --profile graphiti exec graphiti python scripts/init_graph_db.py
"""

from __future__ import annotations

import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("init_graph_db")


async def main() -> int:
    from app.config import settings
    from app.core.neo4j import verify_neo4j_connection
    from app.ingestion.graphiti_client import close_graphiti, ensure_indices
    from app.ontology import ENTITY_TYPE_NAMES, RELATION_TYPE_NAMES
    from app.services.graph_query import GraphQueryService

    logger.info("Neo4j URI: %s", settings.neo4j_uri)
    logger.info("Graphiti group: %s", settings.graphiti_group_id)

    try:
        message = verify_neo4j_connection()
        logger.info("Neo4j: %s", message)

        await ensure_indices()
        logger.info("Graphiti indices + DictEntity schema ready")

        service = GraphQueryService()
        checks = service.verify_ontology_constraints()
        stats = service.get_stats()

        print("\n=== Ontology (code) ===")
        print(f"Entity types ({len(ENTITY_TYPE_NAMES)}): {', '.join(ENTITY_TYPE_NAMES)}")
        print(f"Relation types ({len(RELATION_TYPE_NAMES)}): {', '.join(RELATION_TYPE_NAMES)}")

        print("\n=== Graph stats ===")
        for entity_type, count in stats.entity_counts.items():
            print(f"  {entity_type}: {count}")
        for rel_name, count in stats.relation_counts.items():
            print(f"  {rel_name}: {count}")
        print(f"  DictEntity: {stats.dict_entity_count}")
        print(f"  Episodic: {stats.episodic_count}")

        print("\n=== Checks ===")
        for key, ok in checks.items():
            print(f"  {key}: {'OK' if ok else 'WARN'}")

        print("\n=== init_graph_db OK ===")
        return 0
    except Exception as exc:
        logger.exception("init_graph_db failed: %s", exc)
        return 1
    finally:
        await close_graphiti()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
