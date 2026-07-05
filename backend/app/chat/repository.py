"""CRUD истории чатов в PostgreSQL."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.chat.models import ChatMessage, ChatSession
from app.db.postgres import ensure_schema, get_connection


class ChatRepository:
    def __init__(self) -> None:
        ensure_schema()

    def list_sessions(self, limit: int = 50) -> list[ChatSession]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, title, filter_domestic, filter_foreign, created_at, updated_at
                FROM chat_sessions
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return [_session_from_row(r) for r in rows]

    def create_session(
        self,
        *,
        title: str = "Новый чат",
        filter_domestic: bool = True,
        filter_foreign: bool = True,
    ) -> ChatSession:
        with get_connection() as conn:
            row = conn.execute(
                """
                INSERT INTO chat_sessions (title, filter_domestic, filter_foreign)
                VALUES (%s, %s, %s)
                RETURNING id, title, filter_domestic, filter_foreign, created_at, updated_at
                """,
                (title, filter_domestic, filter_foreign),
            ).fetchone()
        return _session_from_row(row)

    def get_session(self, session_id: str) -> ChatSession | None:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT id, title, filter_domestic, filter_foreign, created_at, updated_at
                FROM chat_sessions WHERE id = %s
                """,
                (session_id,),
            ).fetchone()
        return _session_from_row(row) if row else None

    def update_session(
        self,
        session_id: str,
        *,
        title: str | None = None,
        filter_domestic: bool | None = None,
        filter_foreign: bool | None = None,
    ) -> None:
        fields: list[str] = ["updated_at = NOW()"]
        params: list[Any] = []
        if title is not None:
            fields.append("title = %s")
            params.append(title)
        if filter_domestic is not None:
            fields.append("filter_domestic = %s")
            params.append(filter_domestic)
        if filter_foreign is not None:
            fields.append("filter_foreign = %s")
            params.append(filter_foreign)
        params.append(session_id)
        with get_connection() as conn:
            conn.execute(
                f"UPDATE chat_sessions SET {', '.join(fields)} WHERE id = %s",
                params,
            )

    def add_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        response_json: dict[str, Any] | None = None,
    ) -> ChatMessage:
        payload = json.dumps(response_json, ensure_ascii=False) if response_json else None
        with get_connection() as conn:
            row = conn.execute(
                """
                INSERT INTO chat_messages (session_id, role, content, response_json)
                VALUES (%s, %s, %s, %s::jsonb)
                RETURNING id, session_id, role, content, response_json, created_at
                """,
                (session_id, role, content, payload),
            ).fetchone()
            conn.execute(
                "UPDATE chat_sessions SET updated_at = NOW() WHERE id = %s",
                (session_id,),
            )
        return _message_from_row(row)

    def list_messages(self, session_id: str) -> list[ChatMessage]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, role, content, response_json, created_at
                FROM chat_messages
                WHERE session_id = %s
                ORDER BY created_at ASC
                """,
                (session_id,),
            ).fetchall()
        return [_message_from_row(r) for r in rows]


def _session_from_row(row: dict) -> ChatSession:
    return ChatSession(
        id=str(row["id"]),
        title=row["title"],
        filter_domestic=bool(row["filter_domestic"]),
        filter_foreign=bool(row["filter_foreign"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _message_from_row(row: dict) -> ChatMessage:
    raw = row.get("response_json")
    if isinstance(raw, str):
        raw = json.loads(raw)
    return ChatMessage(
        id=str(row["id"]),
        session_id=str(row["session_id"]),
        role=row["role"],
        content=row["content"],
        response_json=raw,
        created_at=row["created_at"],
    )
