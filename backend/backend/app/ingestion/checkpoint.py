"""Checkpoint загрузки документов: идемпотентность Neo4j + Graphiti."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from app.config import settings

CheckpointStatus = Literal[
    "pending",
    "processing",
    "completed",
    "failed",
    "awaiting_clarification",
    "skipped",
]


@dataclass
class DocumentCheckpoint:
    group_id: str
    source_path: str
    content_hash: str
    document_category: str
    status: CheckpointStatus = "pending"
    neo4j_completed: bool = False
    graphiti_completed: bool = False
    graphiti_episodes: list[str] = field(default_factory=list)
    graphiti_chunks_total: int = 0
    graphiti_chunks_ingested: int = 0
    clarification_questions: list[str] = field(default_factory=list)
    error: str | None = None
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def compute_file_content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def document_group_id(content_hash: str) -> str:
    return content_hash[:16]


class CheckpointStore:
    def __init__(self, checkpoints_dir: Path | None = None) -> None:
        self.checkpoints_dir = checkpoints_dir or (settings.ingestion_state_dir / "checkpoints")
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, group_id: str) -> Path:
        return self.checkpoints_dir / f"{group_id}.json"

    def load(self, group_id: str) -> DocumentCheckpoint | None:
        path = self._path(group_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return DocumentCheckpoint(**data)

    def save(self, checkpoint: DocumentCheckpoint) -> None:
        checkpoint.updated_at = datetime.now(timezone.utc).isoformat()
        self._path(checkpoint.group_id).write_text(
            json.dumps(asdict(checkpoint), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_or_create(
        self,
        *,
        group_id: str,
        source_path: str,
        content_hash: str,
        document_category: str,
    ) -> DocumentCheckpoint:
        existing = self.load(group_id)
        if existing:
            return existing
        checkpoint = DocumentCheckpoint(
            group_id=group_id,
            source_path=source_path,
            content_hash=content_hash,
            document_category=document_category,
        )
        self.save(checkpoint)
        return checkpoint

    def is_completed(self, group_id: str, content_hash: str) -> bool:
        checkpoint = self.load(group_id)
        if checkpoint is None:
            return False
        return (
            checkpoint.status == "completed"
            and checkpoint.content_hash == content_hash
            and checkpoint.neo4j_completed
        )

    def mark_processing(self, group_id: str) -> None:
        checkpoint = self.load(group_id)
        if not checkpoint:
            return
        checkpoint.status = "processing"
        self.save(checkpoint)

    def mark_neo4j_complete(self, group_id: str, *, chunks_total: int = 0) -> None:
        checkpoint = self.load(group_id)
        if not checkpoint:
            return
        checkpoint.neo4j_completed = True
        checkpoint.graphiti_chunks_total = chunks_total
        self.save(checkpoint)

    def mark_graphiti_episodes(self, group_id: str, episode_names: list[str]) -> None:
        checkpoint = self.load(group_id)
        if not checkpoint:
            return
        for name in episode_names:
            if name not in checkpoint.graphiti_episodes:
                checkpoint.graphiti_episodes.append(name)
        checkpoint.graphiti_chunks_ingested = len(checkpoint.graphiti_episodes)
        self.save(checkpoint)

    def mark_graphiti_complete(self, group_id: str) -> None:
        checkpoint = self.load(group_id)
        if not checkpoint:
            return
        checkpoint.graphiti_completed = True
        self.save(checkpoint)

    def mark_completed(self, group_id: str) -> None:
        checkpoint = self.load(group_id)
        if not checkpoint:
            return
        checkpoint.status = "completed"
        checkpoint.clarification_questions = []
        self.save(checkpoint)

    def mark_failed(self, group_id: str, error: str) -> None:
        checkpoint = self.load(group_id)
        if not checkpoint:
            return
        checkpoint.status = "failed"
        checkpoint.error = error
        self.save(checkpoint)

    def mark_awaiting_clarification(self, group_id: str, questions: list[str]) -> None:
        checkpoint = self.load(group_id)
        if not checkpoint:
            return
        checkpoint.status = "awaiting_clarification"
        checkpoint.clarification_questions = questions
        self.save(checkpoint)

    def mark_skipped(self, group_id: str) -> None:
        checkpoint = self.load(group_id)
        if not checkpoint:
            return
        checkpoint.status = "skipped"
        self.save(checkpoint)
