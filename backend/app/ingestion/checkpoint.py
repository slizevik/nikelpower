"""Track ingestion progress with JSON checkpoint store."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from app.config import settings

Status = Literal["pending", "processing", "completed", "failed", "skipped"]


@dataclass
class FileRecord:
    path: str
    status: Status = "pending"
    chunks_total: int = 0
    chunks_ingested: int = 0
    error: str | None = None
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class IngestionState:
    files: dict[str, FileRecord] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"files": {k: asdict(v) for k, v in self.files.items()}}

    @classmethod
    def from_dict(cls, data: dict) -> IngestionState:
        state = cls()
        for path, rec in data.get("files", {}).items():
            state.files[path] = FileRecord(**rec)
        return state


class CheckpointStore:
    def __init__(self, state_dir: Path | None = None) -> None:
        self.state_dir = state_dir or settings.ingestion_state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.state_dir / "ingestion_state.json"

    def load(self) -> IngestionState:
        if not self.state_file.exists():
            return IngestionState()
        return IngestionState.from_dict(json.loads(self.state_file.read_text(encoding="utf-8")))

    def save(self, state: IngestionState) -> None:
        self.state_file.write_text(
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_or_create(self, path: str) -> FileRecord:
        state = self.load()
        if path not in state.files:
            state.files[path] = FileRecord(path=path)
            self.save(state)
        return state.files[path]

    def update(self, record: FileRecord) -> None:
        state = self.load()
        record.updated_at = datetime.now(timezone.utc).isoformat()
        state.files[record.path] = record
        self.save(state)

    def summary(self) -> dict[str, int]:
        state = self.load()
        counts = {"pending": 0, "processing": 0, "completed": 0, "failed": 0, "skipped": 0}
        for rec in state.files.values():
            counts[rec.status] = counts.get(rec.status, 0) + 1
        counts["total"] = len(state.files)
        return counts
