"""
Учёт токенов и лимит использования.

ЛИМИТ: TOKEN_LIMIT (по умолчанию 10 000) задаётся в этом файле.
Переопределение через переменную окружения TOKEN_LIMIT в .env.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import tiktoken

from app.config import settings

# --- Автоматический лимит токенов (основная настройка) ---
TOKEN_LIMIT: int = int(__import__("os").getenv("TOKEN_LIMIT", "10000"))

_STATE_FILE = "token_usage.json"
_lock = threading.Lock()
_encoder: tiktoken.Encoding | None = None


class TokenBudgetExceeded(Exception):
    """Превышен лимит TOKEN_LIMIT."""

    def __init__(self, used: int, requested: int, limit: int) -> None:
        self.used = used
        self.requested = requested
        self.limit = limit
        super().__init__(
            f"Лимит токенов исчерпан: использовано {used}/{limit}, "
            f"запрошено ещё {requested}."
        )


@dataclass
class TokenUsageSnapshot:
    total_tokens: int
    last_request_tokens: int
    current_request_tokens: int
    limit: int
    remaining: int

    @property
    def usage_percent(self) -> float:
        if self.limit <= 0:
            return 100.0
        return min(100.0, (self.total_tokens / self.limit) * 100.0)


def count_tokens(text: str) -> int:
    """Подсчёт токенов (tiktoken cl100k_base, оценка для Yandex/OpenAI-совместимых API)."""
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return len(_encoder.encode(text or ""))


def count_tokens_many(texts: list[str]) -> int:
    return sum(count_tokens(t) for t in texts)


def usage_from_api_response(response: object) -> int | None:
    """Извлекает total_tokens из ответа API, если поле usage присутствует."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    total = getattr(usage, "total_tokens", None)
    if total is not None:
        return int(total)
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    if prompt or completion:
        return prompt + completion
    return None


class TokenBudget:
    def __init__(self, state_path: Path | None = None) -> None:
        self._state_path = state_path or (settings.ingestion_state_dir / _STATE_FILE)
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._current_request_tokens = 0
        self._in_request = False
        self._load()

    def _load(self) -> None:
        if not self._state_path.exists():
            self._total_tokens = 0
            self._last_request_tokens = 0
            return
        data = json.loads(self._state_path.read_text(encoding="utf-8"))
        self._total_tokens = int(data.get("total_tokens", 0))
        self._last_request_tokens = int(data.get("last_request_tokens", 0))

    def _save(self) -> None:
        payload = {
            "total_tokens": self._total_tokens,
            "last_request_tokens": self._last_request_tokens,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._state_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def snapshot(self) -> TokenUsageSnapshot:
        with _lock:
            total = self._total_tokens
            last_req = self._last_request_tokens
            current = self._current_request_tokens
        return TokenUsageSnapshot(
            total_tokens=total,
            last_request_tokens=last_req,
            current_request_tokens=current,
            limit=TOKEN_LIMIT,
            remaining=max(0, TOKEN_LIMIT - total),
        )

    def check_available(self, tokens: int) -> None:
        with _lock:
            if self._total_tokens + tokens > TOKEN_LIMIT:
                raise TokenBudgetExceeded(self._total_tokens, tokens, TOKEN_LIMIT)

    def begin_request(self) -> None:
        with _lock:
            self._in_request = True
            self._current_request_tokens = 0

    def finish_request(self) -> int:
        with _lock:
            self._last_request_tokens = self._current_request_tokens
            self._in_request = False
            current = self._current_request_tokens
            self._current_request_tokens = 0
            self._save()
        return current

    def record(self, tokens: int, operation: str = "api") -> int:
        if tokens <= 0:
            return 0
        with _lock:
            if self._total_tokens + tokens > TOKEN_LIMIT:
                raise TokenBudgetExceeded(self._total_tokens, tokens, TOKEN_LIMIT)
            self._total_tokens += tokens
            if self._in_request:
                self._current_request_tokens += tokens
            self._save()
        return tokens

    def record_text_as_tokens(
        self,
        text: str,
        operation: str = "estimate",
        *,
        response: object | None = None,
    ) -> int:
        """Списывает токены: из ответа API или оценка по тексту."""
        from_api = usage_from_api_response(response) if response is not None else None
        tokens = from_api if from_api is not None else count_tokens(text)
        self.record(tokens, operation)
        return tokens


_budget: TokenBudget | None = None


def get_token_budget() -> TokenBudget:
    global _budget
    if _budget is None:
        _budget = TokenBudget()
    return _budget
