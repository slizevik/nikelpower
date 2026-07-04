import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_YANDEX_VISION_MODEL = "gpt://b1ghh2ufu3o0t33psog1/qwen3.6-35b-a3b/latest"


def _path_from_env(name: str, default: str) -> Path:
    return Path(os.getenv(name, default))


class Settings:
    neo4j_uri: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user: str = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password: str = os.getenv("NEO4J_PASSWORD", "nikelpower2026")

    # Yandex Cloud AI (OpenAI-совместимый API) — см. backend/sample.py
    yandex_cloud_folder: str = os.getenv("YANDEX_CLOUD_FOLDER", "").strip().strip('"')
    yandex_cloud_api_key: str = os.getenv("YANDEX_CLOUD_API_KEY", "").strip().strip('"')
    yandex_cloud_model: str = os.getenv("YANDEX_CLOUD_MODEL", "").strip().strip('"')
    yandex_embedding_model: str = os.getenv("YANDEX_EMBEDDING_MODEL", "").strip().strip('"')
    yandex_cloud_base_url: str = os.getenv(
        "YANDEX_CLOUD_BASE_URL", "https://ai.api.cloud.yandex.net/v1"
    ).strip().strip('"')

    # Размерность вектора эмбеддингов (Yandex text-search-doc: 256)
    embedding_dimensions: int = int(os.getenv("EMBEDDING_DIMENSIONS", "256"))
    embedding_similarity_threshold: float = float(
        os.getenv("EMBEDDING_SIMILARITY_THRESHOLD", "0.82")
    )
    dictionary_context_top_k: int = int(os.getenv("DICTIONARY_CONTEXT_TOP_K", "15"))

    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    documents_dir: Path = _path_from_env("DOCUMENTS_DIR", "data/documents")
    ingestion_state_dir: Path = _path_from_env("INGESTION_STATE_DIR", "data/ingestion")

    # Paragraph-aware chunking (MD §1: ~840–860 tokens per chunk)
    chunk_target_tokens: int = int(os.getenv("CHUNK_TARGET_TOKENS", "850"))
    chunk_max_tokens: int = int(os.getenv("CHUNK_MAX_TOKENS", "1000"))
    chunk_overlap_paragraphs: int = int(os.getenv("CHUNK_OVERLAP_PARAGRAPHS", "1"))

    # Legacy char-based settings (fallback / reference only)
    chunk_size_chars: int = int(os.getenv("CHUNK_SIZE_CHARS", "6000"))
    chunk_overlap_percent: float = float(os.getenv("CHUNK_OVERLAP_PERCENT", "15"))
    chunk_overlap_chars: int = int(os.getenv("CHUNK_OVERLAP_CHARS", "0"))
    ingestion_batch_size: int = int(os.getenv("INGESTION_BATCH_SIZE", "10"))

    graphiti_group_id: str = os.getenv("GRAPHITI_GROUP_ID", "nikelpower")

    # Парсинг: LibreOffice + Qwen-VL
    libreoffice_binary: str = os.getenv("LIBREOFFICE_BINARY", "libreoffice")
    libreoffice_timeout_sec: int = int(os.getenv("LIBREOFFICE_TIMEOUT_SEC", "180"))
    converted_pdf_dir: Path = _path_from_env("CONVERTED_PDF_DIR", "data/ingestion/converted")
    yandex_vision_model: str = os.getenv(
        "YANDEX_VISION_MODEL", DEFAULT_YANDEX_VISION_MODEL
    ).strip().strip('"')
    analyze_document_images: bool = os.getenv("ANALYZE_DOCUMENT_IMAGES", "true").lower() in (
        "1",
        "true",
        "yes",
    )

    @property
    def effective_chunk_overlap_chars(self) -> int:
        """Перекрытие чанков: явное значение или процент от размера чанка."""
        if self.chunk_overlap_chars > 0:
            return self.chunk_overlap_chars
        return max(1, int(self.chunk_size_chars * self.chunk_overlap_percent / 100.0))


settings = Settings()
