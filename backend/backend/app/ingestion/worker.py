"""RQ worker: фоновая обработка документов."""

from __future__ import annotations

import logging
import sys

from redis import Redis
from rq import Worker

from app.config import settings
from app.ingestion.queue_client import QUEUE_NAME

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("nikelpower.worker")


def main() -> int:
    logger.info("Starting RQ worker, queue=%s, redis=%s", QUEUE_NAME, settings.redis_url)
    try:
        conn = Redis.from_url(settings.redis_url)
        conn.ping()
    except Exception as exc:
        logger.error("Redis unavailable: %s", exc)
        return 1

    worker = Worker([QUEUE_NAME], connection=conn)
    worker.work(with_scheduler=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
