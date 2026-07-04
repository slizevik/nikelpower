"""Structured answer models — only facts grounded in the knowledge graph."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SourceCitation(BaseModel):
    fact: str = Field(description="Fact retrieved from the graph")
    relation: str | None = Field(default=None, description="Relation type if known")
    source_entity: str | None = None
    target_entity: str | None = None
    episode_source: str | None = Field(
        default=None, description="Source document path from ingestion metadata"
    )


class GroundedAnswer(BaseModel):
    query: str
    answer: str = Field(description="Answer based only on provided graph facts")
    confidence: str = Field(description="high | medium | low | insufficient_data")
    citations: list[SourceCitation] = Field(default_factory=list)
    entities_mentioned: list[str] = Field(default_factory=list)
    insufficient_data: bool = Field(
        default=False,
        description="True when the graph has no relevant facts for the query",
    )
