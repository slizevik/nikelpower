"""Эмбеддинги через Yandex Cloud AI для поиска похожих сущностей в словаре."""

from __future__ import annotations

import logging

from openai import BadRequestError

from app.config import settings
from app.llm.token_budget import clip_text_to_token_limit, count_tokens
from app.llm.tracked_api import embeddings_create
from app.llm.yandex_client import get_yandex_client

logger = logging.getLogger(__name__)

YANDEX_EMBEDDING_HARD_LIMIT = 2048


def _embedding_model_uri() -> str:
    if not settings.yandex_embedding_model:
        raise RuntimeError(
            "YANDEX_EMBEDDING_MODEL не задан. "
            "Пример: emb://<folder_id>/text-search-doc/latest"
        )
    model = settings.yandex_embedding_model
    folder = settings.yandex_cloud_folder
    if folder and model.startswith("emb://"):
        rest = model[6:]
        model_folder, _, tail = rest.partition("/")
        if model_folder and model_folder != folder and tail:
            return f"emb://{folder}/{tail}"
    return model


def _prepare_embedding_text(text: str, max_tokens: int) -> str:
    return clip_text_to_token_limit(text.strip(), max_tokens)


def embed_text(text: str) -> list[float]:
    client = get_yandex_client()
    limits = [
        settings.embedding_max_input_tokens,
        1500,
        1200,
        900,
    ]
    last_error: Exception | None = None

    for limit in limits:
        clipped = _prepare_embedding_text(text, limit)
        if not clipped:
            continue
        try:
            response = embeddings_create(
                client,
                model=_embedding_model_uri(),
                input=clipped,
            )
            if limit < settings.embedding_max_input_tokens:
                logger.info(
                    "Embedding clipped to %s tokens (was ~%s)",
                    count_tokens(clipped),
                    count_tokens(text),
                )
            return response.data[0].embedding
        except BadRequestError as exc:
            last_error = exc
            message = str(exc)
            if "2048" not in message and "token" not in message.lower():
                raise
            logger.warning("Embedding token limit hit at %s tokens, retry smaller: %s", limit, exc)

    if last_error is not None:
        raise last_error
    raise ValueError("Cannot embed empty text")


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Yandex text-search-doc принимает только одну строку на запрос."""
    if not texts:
        return []
    return [embed_text(t) for t in texts]


def embedding_input_for_entity(canonical_name: str, aliases: list[str]) -> str:
    parts = [canonical_name, *aliases]
    return " | ".join(dict.fromkeys(p.strip() for p in parts if p.strip()))
