#!/usr/bin/env python3
"""
Smoke-тест Graphiti + Yandex + Neo4j.

Запуск в контейнере graphiti:
    docker compose --profile graphiti up -d graphiti
    docker compose exec graphiti python scripts/test_graphiti.py

С ingest одного тестового эпизода:
    docker compose exec graphiti python scripts/test_graphiti.py --ingest
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("test_graphiti")

SAMPLE_EPISODE = (
    "Электроэкстракция никеля из сульфатного католита проводится "
    "на установке с титановыми катодами. Концентрация никеля в растворе "
    "составляет 45 мг/л при температуре 60 °C."
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
    from app.ingestion.chunker import TextChunk

    logger.info("Neo4j: %s", settings.neo4j_uri)
    logger.info("LLM: %s", settings.yandex_cloud_model)
    logger.info("Embed: %s", settings.yandex_embedding_model)

    try:
        gt = get_graphiti()
        logger.info("Graphiti client OK: %s", type(gt).__name__)

        await ensure_indices()
        logger.info("Индексы Graphiti и DictEntity созданы")

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
                group_id="graphiti_smoke_test",
                chunk_role="body",
                block_ids=[],
                token_count=0,
            )
            logger.info("add_episode (ingest_chunk)...")
            await ingest_chunk(chunk)
            logger.info("Эпизод загружен")

        logger.info("search: %r", SEARCH_QUERY)
        results = await search_graph(SEARCH_QUERY, num_results=5)
        logger.info("Найдено результатов: %s", len(results))
        for i, edge in enumerate(results, 1):
            fact = getattr(edge, "fact", None) or str(edge)
            print(f"  {i}. {fact[:200]}")

        print("\n=== Graphiti smoke test OK ===")
        return 0
    except Exception as exc:
        logger.exception("Graphiti test failed: %s", exc)
        return 1
    finally:
        await close_graphiti()


def main() -> int:
    parser = argparse.ArgumentParser(description="Graphiti smoke test")
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="Загрузить тестовый эпизод перед поиском (расходует токены Yandex)",
    )
    args = parser.parse_args()
    return asyncio.run(run_test(args.ingest))


if __name__ == "__main__":
    sys.exit(main())
