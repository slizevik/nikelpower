"""Эмбеддинги через Yandex Cloud AI для поиска похожих сущностей в словаре."""

from __future__ import annotations

from app.config import settings
from app.llm.yandex_client import get_yandex_client


def _embedding_model_uri() -> str:
    if not settings.yandex_embedding_model:
        raise RuntimeError(
            "YANDEX_EMBEDDING_MODEL не задан. "
            "Пример: emb://<folder_id>/text-search-doc/latest"
        )
    return settings.yandex_embedding_model


def embed_text(text: str) -> list[float]:
    client = get_yandex_client()
    response = client.embeddings.create(
        model=_embedding_model_uri(),
        input=text[:8000],
    )
    return response.data[0].embedding


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    client = get_yandex_client()
    response = client.embeddings.create(
        model=_embedding_model_uri(),
        input=[t[:8000] for t in texts],
    )
    return [item.embedding for item in response.data]


def embedding_input_for_entity(canonical_name: str, aliases: list[str]) -> str:
    """Текст для эмбеддинга: каноническое имя + все известные алиасы."""
    parts = [canonical_name, *aliases]
    return " | ".join(dict.fromkeys(p.strip() for p in parts if p.strip()))
