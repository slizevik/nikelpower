"""Эмбеддинги через Yandex Cloud AI для поиска похожих сущностей в словаре."""

from __future__ import annotations

from app.config import settings
from app.llm.tracked_api import embeddings_create
from app.llm.yandex_client import get_yandex_client


def _embedding_model_uri() -> str:
    if not settings.yandex_embedding_model:
        raise RuntimeError(
            "YANDEX_EMBEDDING_MODEL не задан. "
            "Пример: emb://<folder_id>/text-search-doc/latest"
        )
    model = settings.yandex_embedding_model
    folder = settings.yandex_cloud_folder
    if folder and model.startswith("emb://"):
        # URI модели должен использовать тот же folder, что и API-ключ (x-folder-id).
        rest = model[6:]  # после emb://
        model_folder, _, tail = rest.partition("/")
        if model_folder and model_folder != folder and tail:
            return f"emb://{folder}/{tail}"
    return model


def embed_text(text: str) -> list[float]:
    client = get_yandex_client()
    clipped = text[:8000]
    response = embeddings_create(
        client,
        model=_embedding_model_uri(),
        input=clipped,
    )
    return response.data[0].embedding


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Yandex text-search-doc принимает только одну строку на запрос."""
    if not texts:
        return []
    return [embed_text(t) for t in texts]


def embedding_input_for_entity(canonical_name: str, aliases: list[str]) -> str:
    parts = [canonical_name, *aliases]
    return " | ".join(dict.fromkeys(p.strip() for p in parts if p.strip()))
