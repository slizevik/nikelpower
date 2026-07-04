"""Сборка Graphiti с Yandex Cloud AI (OpenAI-compatible API через AI Studio)."""

from __future__ import annotations

from openai import AsyncOpenAI

from graphiti_core import Graphiti
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient

from app.config import settings


def _require_yandex() -> None:
    if not settings.yandex_cloud_api_key:
        raise RuntimeError("YANDEX_CLOUD_API_KEY не задан в .env")
    if not settings.yandex_cloud_folder:
        raise RuntimeError("YANDEX_CLOUD_FOLDER не задан в .env")
    if not settings.yandex_cloud_model:
        raise RuntimeError("YANDEX_CLOUD_MODEL не задан в .env")
    if not settings.yandex_embedding_model:
        raise RuntimeError("YANDEX_EMBEDDING_MODEL не задан в .env")


def _yandex_async_client() -> AsyncOpenAI:
    folder = settings.yandex_cloud_folder
    return AsyncOpenAI(
        api_key=settings.yandex_cloud_api_key,
        base_url=settings.yandex_cloud_base_url,
        project=folder,
        default_headers={"x-folder-id": folder},
    )


def create_graphiti() -> Graphiti:
    _require_yandex()
    base = settings.yandex_cloud_base_url
    key = settings.yandex_cloud_api_key
    llm_model = settings.yandex_cloud_model
    async_client = _yandex_async_client()

    llm_config = LLMConfig(
        api_key=key,
        model=llm_model,
        small_model=llm_model,
        base_url=base,
    )
    llm_client = OpenAIGenericClient(
        config=llm_config,
        client=async_client,
        structured_output_mode="json_object",
    )
    embedder = OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            api_key=key,
            embedding_model=settings.yandex_embedding_model,
            embedding_dim=settings.embedding_dimensions,
            base_url=base,
        ),
        client=async_client,
    )
    rerank_config = LLMConfig(
        api_key=key,
        model=llm_model,
        small_model=llm_model,
        base_url=base,
    )
    cross_encoder = OpenAIRerankerClient(config=rerank_config, client=async_client)

    return Graphiti(
        settings.neo4j_uri,
        settings.neo4j_user,
        settings.neo4j_password,
        llm_client=llm_client,
        embedder=embedder,
        cross_encoder=cross_encoder,
    )
