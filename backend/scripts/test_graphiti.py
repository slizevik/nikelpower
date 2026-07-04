#!/usr/bin/env python3
"""
Smoke-тест Graphiti + Yandex + Neo4j.

Запуск:
    docker compose --profile graphiti exec graphiti python scripts/test_graphiti.py --ingest
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_graphiti")

SAMPLE_EPISODE = (
    "Электроэкстракция никеля из сульфатного католита проводится "
    "на установке с титановыми катодами. Концентрация никеля в растворе "
    "составляет 45 мг/л при температуре 60 °C. Процесс описан в отчёте "
    "пилотной установки Nikelpower 2024."
)

SEARCH_QUERY = "электроэкстракция никеля"


async def run_test(do_ingest: bool) -> int:
    from app.config import settings
    from app.ingestion.graphiti_client import (
        close_graphiti,
        ensure_indices,
        get_graphiti,
        ingest_chunk,
        search_graph,
    )
    from app.models.chunk import TextChunk
    from app.services.graph_query import GraphQueryService

    logger.info("Neo4j: %s", settings.neo4j_uri)
    logger.info("LLM: %s", settings.yandex_cloud_model)

    try:
        gt = get_graphiti()
        logger.info("Graphiti client OK: %s", type(gt).__name__)

        await ensure_indices()

        if do_ingest:
            chunk = TextChunk(
                chunk_id="test_graphiti_001",
                source_path="/test/graphiti_smoke.txt",
                doc_type="text",
                language_hint="ru",
                page_start=1,
                page_end=1,
                chunk_index=0,
                text=SAMPLE_EPISODE,
                group_id=settings.graphiti_group_id,
            )
            await ingest_chunk(chunk)
            logger.info("Test episode ingested")

        results = await search_graph(SEARCH_QUERY, num_results=5)
        logger.info("Search results: %s", len(results))
        for i, edge in enumerate(results, 1):
            fact = getattr(edge, "fact", None) or str(edge)
            print(f"  {i}. {fact[:200]}")

        stats = GraphQueryService().get_stats()
        print(f"\nEntity nodes in graph: {sum(stats.entity_counts.values())}")
        print(f"Relations in graph: {sum(stats.relation_counts.values())}")
        print("\n=== Graphiti smoke test OK ===")
        return 0
    except Exception as exc:
        logger.exception("Graphiti test failed: %s", exc)
        return 1
    finally:
        await close_graphiti()


def main() -> int:
    parser = argparse.ArgumentParser(description="Graphiti smoke test")
    parser.add_argument("--ingest", action="store_true", help="Ingest sample episode")
    args = parser.parse_args()
    return asyncio.run(run_test(args.ingest))


if __name__ == "__main__":
    sys.exit(main())
