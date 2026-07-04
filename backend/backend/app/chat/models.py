"""Модели истории чатов (PostgreSQL)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class ChatSession:
    id: str
    title: str
    filter_domestic: bool
    filter_foreign: bool
    created_at: datetime
    updated_at: datetime


@dataclass
class ChatMessage:
    id: str
    session_id: str
    role: str
    content: str
    response_json: dict[str, Any] | None
    created_at: datetime
