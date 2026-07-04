"""PostgreSQL: история чатов."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from app.config import settings

logger = logging.getLogger(__name__)

_schema_ready = False

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL DEFAULT 'Новый чат',
    filter_domestic BOOLEAN NOT NULL DEFAULT TRUE,
    filter_foreign BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    response_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session
    ON chat_messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated
    ON chat_sessions(updated_at DESC);
"""


@contextmanager
def get_connection() -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(settings.database_url, row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    try:
        with get_connection() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
            conn.execute(SCHEMA_SQL)
        _schema_ready = True
        logger.info("PostgreSQL chat schema ready")
    except Exception as exc:
        logger.warning("PostgreSQL unavailable: %s", exc)
        raise
