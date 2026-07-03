import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _path_from_env(name: str, default: str) -> Path:
    return Path(os.getenv(name, default))


class Settings:
    neo4j_uri: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user: str = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password: str = os.getenv("NEO4J_PASSWORD", "nikelpower2026")

    # Yandex Cloud AI (OpenAI-совместимый API) — см. backend/sample.py
    yandex_cloud_folder: str = os.getenv("YANDEX_CLOUD_FOLDER", "")
    yandex_cloud_api_key: str = os.getenv("YANDEX_CLOUD_API_KEY", "")
    yandex_cloud_model: str = os.getenv("YANDEX_CLOUD_MODEL", "")
    yandex_embedding_model: str = os.getenv("YANDEX_EMBEDDING_MODEL", "")
    yandex_cloud_base_url: str = os.getenv(
        "YANDEX_CLOUD_BASE_URL", "https://ai.api.cloud.yandex.net/v1"
    )

    # Размерность вектора эмбеддингов (Yandex text-search-doc: 256)
    embedding_dimensions: int = int(os.getenv("EMBEDDING_DIMENSIONS", "256"))
    embedding_similarity_threshold: float = float(
        os.getenv("EMBEDDING_SIMILARITY_THRESHOLD", "0.82")
    )
    dictionary_context_top_k: int = int(os.getenv("DICTIONARY_CONTEXT_TOP_K", "15"))

    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    documents_dir: Path = _path_from_env("DOCUMENTS_DIR", "data/documents")
    ingestion_state_dir: Path = _path_from_env("INGESTION_STATE_DIR", "data/ingestion")

    chunk_size_chars: int = int(os.getenv("CHUNK_SIZE_CHARS", "6000"))
    chunk_overlap_chars: int = int(os.getenv("CHUNK_OVERLAP_CHARS", "400"))
    ingestion_batch_size: int = int(os.getenv("INGESTION_BATCH_SIZE", "10"))

    graphiti_group_id: str = os.getenv("GRAPHITI_GROUP_ID", "nikelpower")


settings = Settings()
