"""Yandex Cloud AI client (OpenAI-compatible API via AI Studio)."""

from __future__ import annotations

from openai import OpenAI

from app.config import settings

_client: OpenAI | None = None


def get_yandex_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.yandex_cloud_api_key:
            raise RuntimeError("YANDEX_CLOUD_API_KEY не задан. Укажите ключ в .env")
        if not settings.yandex_cloud_folder:
            raise RuntimeError("YANDEX_CLOUD_FOLDER не задан. Укажите ID каталога в .env")
        folder = settings.yandex_cloud_folder
        _client = OpenAI(
            api_key=settings.yandex_cloud_api_key,
            base_url=settings.yandex_cloud_base_url,
            project=folder,
            default_headers={"x-folder-id": folder},
        )
    return _client
