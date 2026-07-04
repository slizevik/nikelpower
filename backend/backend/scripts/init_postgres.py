"""Инициализация схемы PostgreSQL для истории чатов."""

from __future__ import annotations

import logging
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("init_postgres")


def main() -> int:
    from app.db.postgres import ensure_schema

    ensure_schema()
    logger.info("PostgreSQL chat schema initialized")
    return 0


if __name__ == "__main__":
    sys.exit(main())
