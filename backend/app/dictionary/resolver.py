"""
Резолвер динамического словаря: контекст для LLM и регистрация новых терминов.

Вместо статического GLOSSARY_LINES для каждого чанка подбираются
релевантные сущности из Neo4j по векторному сходству.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.config import settings
from app.dictionary.embeddings import embed_text
from app.dictionary.store import DictEntityRecord, EntityDictionaryStore
from app.ontology.glossary import build_extraction_instructions

logger = logging.getLogger(__name__)

# Типы сущностей, которые попадают в живой словарь
DICTIONARY_ENTITY_TYPES = frozenset(
    {"Material", "Process", "Equipment", "Property", "Facility"}
)


@dataclass
class ExtractedTerm:
    name: str
    entity_type: str
    aliases: list[str] | None = None


class EntityDictionaryResolver:
    def __init__(self, store: EntityDictionaryStore | None = None) -> None:
        self.store = store or EntityDictionaryStore()

    def ensure_ready(self) -> None:
        self.store.ensure_schema()

    def get_context_for_text(self, text: str, top_k: int | None = None) -> str:
        """
        Векторизует фрагмент текста и возвращает блок известных сущностей
        для подстановки в промпт извлечения Graphiti.
        """
        k = top_k or settings.dictionary_context_top_k
        snippet = text[:4000].strip()
        if not snippet:
            return ""

        if self.store.count() == 0:
            return ""

        try:
            vector = embed_text(snippet)
            matches = self.store.find_similar(vector, top_k=k, min_score=0.75)
        except Exception as exc:
            logger.warning("Dictionary context lookup failed: %s", exc)
            return ""

        if not matches:
            return ""

        lines = []
        for m in matches:
            alias_str = ", ".join(m.aliases) if m.aliases else "—"
            lines.append(
                f"- [{m.entity_type}] {m.canonical_name}"
                f" (aliases: {alias_str}; score={m.score:.2f})"
            )
        return "\n".join(lines)

    def build_instructions_for_chunk(self, chunk_text: str) -> str:
        dynamic_context = self.get_context_for_text(chunk_text)
        return build_extraction_instructions(dynamic_context)

    def register_terms(
        self,
        terms: list[ExtractedTerm],
        source_document: str | None = None,
    ) -> list[DictEntityRecord]:
        """Регистрирует извлечённые термины в словаре (merge или create)."""
        results: list[DictEntityRecord] = []
        for term in terms:
            if term.entity_type not in DICTIONARY_ENTITY_TYPES:
                continue
            if not term.name or len(term.name.strip()) < 2:
                continue
            record = self.store.upsert_entity(
                canonical_name=term.name.strip(),
                entity_type=term.entity_type,
                aliases=term.aliases or [],
                source_document=source_document,
            )
            results.append(record)
        return results

    def register_from_graphiti_nodes(
        self,
        nodes: list,
        source_document: str | None = None,
    ) -> list[DictEntityRecord]:
        """
        Синхронизирует узлы, возвращённые Graphiti после add_episode,
        в динамический словарь DictEntity.
        """
        terms: list[ExtractedTerm] = []
        for node in nodes:
            name = getattr(node, "name", None) or ""
            labels = getattr(node, "labels", None) or []
            entity_type = _resolve_entity_type(labels)
            if not name or not entity_type:
                continue

            aliases: list[str] = []
            attrs = getattr(node, "attributes", None) or {}
            if isinstance(attrs, dict):
                syn = attrs.get("synonyms")
                if isinstance(syn, str) and syn.strip():
                    aliases = [s.strip() for s in re.split(r"[,;/]", syn) if s.strip()]

            terms.append(ExtractedTerm(name=name, entity_type=entity_type, aliases=aliases))

        return self.register_terms(terms, source_document=source_document)


def _resolve_entity_type(labels: list) -> str | None:
    for label in labels:
        if label in DICTIONARY_ENTITY_TYPES:
            return label
        if label == "Entity":
            return "Material"
    return None
