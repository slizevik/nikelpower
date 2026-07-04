"""Модели ответа вкладки «Чат с LLM»."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatSearchFilters(BaseModel):
    include_domestic: bool = Field(default=True, description="Отечественные источники")
    include_foreign: bool = Field(default=True, description="Зарубежные источники")
    document_category: str | None = Field(default=None, description="article, report, ... or None")
    material: str | None = None
    process_type: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    min_relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)

    @property
    def country(self) -> str:
        if self.include_domestic and self.include_foreign:
            return "all"
        if self.include_domestic:
            return "russia"
        if self.include_foreign:
            return "foreign"
        return "all"


class ChatDocumentResult(BaseModel):
    title: str
    summary: str
    author_or_source: str | None = None
    updated_at: str | None = None
    download_path: str | None = None
    group_id: str | None = None
    document_category: str | None = None
    relevance_score: float = 0.0
    matched_pages: str | None = None
    reliability: str = Field(default="medium", description="high | medium | low")


class ChatAgentResponse(BaseModel):
    query: str
    augmented_query: str
    filters_applied: ChatSearchFilters
    documents: list[ChatDocumentResult] = Field(default_factory=list)
    no_data: bool = False
    message: str = ""
    comparative_note: str | None = Field(
        default=None,
        description="Сравнительный анализ для запросов «A vs B»",
    )
