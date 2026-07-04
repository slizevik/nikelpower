"""Результаты извлечения сущностей из подготовленного документа."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExtractedEntity(BaseModel):
    entity_type: str = Field(description="Material, Process, Equipment, etc.")
    name: str
    attributes: dict[str, str | float | int | bool | None] = Field(default_factory=dict)
    evidence: str | None = Field(default=None, description="Verbatim quote from source text")


class ExtractedRelation(BaseModel):
    relation_type: str
    source_name: str
    source_type: str = "Entity"
    target_name: str
    target_type: str = "Entity"
    attributes: dict[str, str | float | int | bool | None] = Field(default_factory=dict)
    evidence: str | None = None


class EntityExtractionResult(BaseModel):
    source_path: str
    document_category: str
    document_title: str | None = None
    language_hint: str | None = None
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
    other_entities: list[ExtractedEntity] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    is_final_answer: bool = True
    chunks_processed: int = 1
    prompt_source: str = "builtin"

    @property
    def entity_count(self) -> int:
        return len(self.entities) + len(self.other_entities)

    @property
    def relation_count(self) -> int:
        return len(self.relations)

    @property
    def needs_clarification(self) -> bool:
        return bool(self.clarification_questions) and not self.is_final_answer
