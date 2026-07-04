"""Извлечение сущностей из подготовленного документа через Yandex AI Studio."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app.config import settings
from app.ingestion.entity_extraction_prompt import (
    ExtractionInteractionState,
    build_user_message,
    get_entity_extraction_prompt,
)
from app.llm.token_budget import count_tokens
from app.llm.tracked_api import chat_completions_create
from app.llm.yandex_client import get_yandex_client
from app.models.extraction import (
    EntityExtractionResult,
    ExtractedEntity,
    ExtractedRelation,
)
from app.ontology import ENTITY_TYPE_NAMES, RELATION_TYPE_NAMES

logger = logging.getLogger(__name__)

# Ключи JSON от LLM → типы онтологии Neo4j/Graphiti
_CATEGORY_KEY_MAP: dict[str, str] = {
    "material": "Material",
    "materials": "Material",
    "process": "Process",
    "processes": "Process",
    "equipment": "Equipment",
    "property": "Property",
    "properties": "Property",
    "experiment": "Experiment",
    "experiments": "Experiment",
    "publication": "Publication",
    "publications": "Publication",
    "expert": "Expert",
    "experts": "Expert",
    "facility": "Facility",
    "facilities": "Facility",
}


def _parse_json_response(raw: str) -> dict:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


def _split_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    overlap = max(500, max_chars // 10)
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def _null_if_none_string(value: object) -> object:
    if isinstance(value, str) and value.strip().lower() in {"none", "null", ""}:
        return None
    return value


def _entity_from_item(item: dict, entity_type: str, *, is_expert: bool = False) -> ExtractedEntity | None:
    name = str(item.get("name", "")).strip()
    if not name:
        return None

    description = item.get("description") or item.get("evidence")
    attrs: dict[str, str | float | int | bool | None] = {}

    if is_expert:
        for field in ("canonical_name", "organization", "is_russian"):
            val = _null_if_none_string(item.get(field))
            if val is not None:
                attrs[field] = val
    else:
        for field in ("canonical_name", "organization", "is_russian"):
            if item.get(field) not in (None, "", "null", "None"):
                logger.debug("Ignoring expert-only field %s on %s", field, entity_type)

    return ExtractedEntity(
        entity_type=entity_type,
        name=name,
        attributes=attrs,
        evidence=str(description) if description else None,
    )


def _parse_entities_from_payload(payload: dict) -> tuple[list[ExtractedEntity], list[ExtractedEntity]]:
    mandatory: list[ExtractedEntity] = []
    other: list[ExtractedEntity] = []

    category_keys = (
        "material",
        "process",
        "equipment",
        "property",
        "experiment",
        "publication",
        "experts",
        "expert",
        "facility",
    )
    for key in category_keys:
        items = payload.get(key)
        if not isinstance(items, list):
            continue
        ontology_type = _CATEGORY_KEY_MAP.get(key)
        if not ontology_type:
            continue
        is_expert = ontology_type == "Expert"
        for item in items:
            if not isinstance(item, dict):
                continue
            entity = _entity_from_item(item, ontology_type, is_expert=is_expert)
            if entity:
                mandatory.append(entity)

    for item in payload.get("other_entities") or []:
        if not isinstance(item, dict):
            continue
        dynamic_type = str(item.get("entity_type") or "Other").strip()
        entity = _entity_from_item(item, dynamic_type, is_expert=False)
        if entity:
            other.append(entity)

    # Legacy format support: flat "entities" list
    for item in payload.get("entities") or []:
        if not isinstance(item, dict):
            continue
        et = str(item.get("entity_type", "")).strip()
        if et in ENTITY_TYPE_NAMES:
            entity = _entity_from_item(item, et, is_expert=(et == "Expert"))
            if entity:
                mandatory.append(entity)

    return mandatory, other


def _name_to_type_lookup(
    mandatory: list[ExtractedEntity],
    other: list[ExtractedEntity],
) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for entity in mandatory + other:
        lookup[entity.name.lower()] = entity.entity_type
    return lookup


def _parse_relations_from_payload(
    payload: dict,
    type_lookup: dict[str, str],
) -> list[ExtractedRelation]:
    relations: list[ExtractedRelation] = []
    raw_items = payload.get("relationships") or payload.get("relations") or []

    for item in raw_items:
        if not isinstance(item, dict):
            continue

        source_name = str(item.get("source") or item.get("source_name") or "").strip()
        target_name = str(item.get("target") or item.get("target_name") or "").strip()
        if not source_name or not target_name:
            continue

        rel_type = str(
            item.get("relation_type") or item.get("type") or item.get("relationship") or "related_to"
        ).strip()

        source_type = str(item.get("source_type") or type_lookup.get(source_name.lower(), "Entity"))
        target_type = str(item.get("target_type") or type_lookup.get(target_name.lower(), "Entity"))

        description = item.get("description") or item.get("evidence")
        attrs: dict[str, str | float | int | bool | None] = {}
        if rel_type not in RELATION_TYPE_NAMES:
            attrs["original_relation_type"] = rel_type

        relations.append(
            ExtractedRelation(
                relation_type=rel_type,
                source_name=source_name,
                source_type=source_type,
                target_name=target_name,
                target_type=target_type,
                attributes=attrs,
                evidence=str(description) if description else None,
            )
        )

    return relations


def _merge_results(parts: list[EntityExtractionResult]) -> EntityExtractionResult:
    if not parts:
        return EntityExtractionResult(source_path="", document_category="")

    entities_map: dict[tuple[str, str], ExtractedEntity] = {}
    other_map: dict[tuple[str, str], ExtractedEntity] = {}
    relations_map: dict[tuple[str, str, str], ExtractedRelation] = {}
    clarification: list[str] = []
    is_final = True

    for part in parts:
        for entity in part.entities:
            key = (entity.entity_type, entity.name.lower())
            entities_map.setdefault(key, entity)
        for entity in part.other_entities:
            key = (entity.entity_type, entity.name.lower())
            other_map.setdefault(key, entity)
        for rel in part.relations:
            key = (rel.relation_type, rel.source_name.lower(), rel.target_name.lower())
            relations_map.setdefault(key, rel)
        clarification.extend(part.clarification_questions)
        is_final = is_final and part.is_final_answer

    base = parts[0]
    return EntityExtractionResult(
        source_path=base.source_path,
        document_category=base.document_category,
        document_title=base.document_title,
        language_hint=base.language_hint,
        entities=list(entities_map.values()),
        other_entities=list(other_map.values()),
        relations=list(relations_map.values()),
        clarification_questions=list(dict.fromkeys(clarification)),
        is_final_answer=is_final,
        chunks_processed=sum(p.chunks_processed for p in parts),
        prompt_source=base.prompt_source,
    )


def _extract_chunk(
    chunk: str,
    *,
    doc_class: str,
    doc_title: str,
    file_path: str,
    language_hint: str | None,
    system_prompt: str,
    prompt_source: str,
    interaction: ExtractionInteractionState | None = None,
) -> EntityExtractionResult:
    if not settings.yandex_cloud_model:
        raise RuntimeError("YANDEX_CLOUD_MODEL не задан в .env")

    user_message = build_user_message(
        chunk,
        doc_class=doc_class,
        doc_title=doc_title,
        file_path=file_path,
        interaction=interaction,
    )

    client = get_yandex_client()
    response = chat_completions_create(
        client,
        model=settings.yandex_cloud_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    raw = response.choices[0].message.content or "{}"
    payload = _parse_json_response(raw)

    entities, other_entities = _parse_entities_from_payload(payload)
    type_lookup = _name_to_type_lookup(entities, other_entities)
    relations = _parse_relations_from_payload(payload, type_lookup)

    questions = [
        str(q).strip()
        for q in (payload.get("clarification_questions") or [])
        if str(q).strip()
    ]
    is_final = bool(payload.get("is_final_answer", True))

    return EntityExtractionResult(
        source_path=file_path,
        document_category=doc_class,
        document_title=doc_title,
        language_hint=language_hint,
        entities=entities,
        other_entities=other_entities,
        relations=relations,
        clarification_questions=questions,
        is_final_answer=is_final,
        chunks_processed=1,
        prompt_source=prompt_source,
    )


def extract_entities_from_prepared_text(
    prepared_text: str,
    *,
    source_path: str,
    document_category: str,
    document_title: str | None = None,
    language_hint: str | None = None,
    interaction: ExtractionInteractionState | None = None,
) -> EntityExtractionResult:
    system_prompt, prompt_source = get_entity_extraction_prompt()
    max_chars = settings.entity_extraction_max_chars
    chunks = _split_text(prepared_text.strip(), max_chars)
    title = document_title or Path(source_path).name

    logger.info(
        "Entity extraction: %s chars, %s chunk(s), prompt=%s",
        len(prepared_text),
        len(chunks),
        prompt_source,
    )

    partials: list[EntityExtractionResult] = []
    for i, chunk in enumerate(chunks, 1):
        logger.info("Extracting chunk %s/%s (~%s tokens)", i, len(chunks), count_tokens(chunk))
        partials.append(
            _extract_chunk(
                chunk,
                doc_class=document_category,
                doc_title=title,
                file_path=source_path,
                language_hint=language_hint,
                system_prompt=system_prompt,
                prompt_source=prompt_source,
                interaction=interaction,
            )
        )

    return _merge_results(partials)


def extract_entities_from_prepared_file(
    prepared_path: Path,
    *,
    source_path: str,
    document_category: str,
    document_title: str | None = None,
    language_hint: str | None = None,
    interaction: ExtractionInteractionState | None = None,
) -> EntityExtractionResult:
    text = prepared_path.read_text(encoding="utf-8")
    return extract_entities_from_prepared_text(
        text,
        source_path=source_path,
        document_category=document_category,
        document_title=document_title,
        language_hint=language_hint,
        interaction=interaction,
    )


def save_extraction_result(result: EntityExtractionResult, prepared_path: str | Path) -> Path:
    root = Path(prepared_path).parent
    out = root / "extracted_entities.json"
    out.write_text(
        result.model_dump_json(indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return out
