"""Вывод связей между сущностями по evidence и онтологии."""

from __future__ import annotations

import re

from app.models.extraction import ExtractedEntity, ExtractedRelation
from app.ontology.edges import EDGE_TYPE_MAP
from app.ontology.entities import ENTITY_TYPE_NAMES

_CO_OCCURS = "co_occurs_in_context"


def normalize_entity_type(entity_type: str) -> str:
    lower = entity_type.strip().lower()
    for name in ENTITY_TYPE_NAMES:
        if name.lower() == lower:
            return name
    return entity_type.strip().title() or "Entity"


def merge_relations(
    llm_relations: list[ExtractedRelation],
    inferred_relations: list[ExtractedRelation],
) -> list[ExtractedRelation]:
    seen: set[tuple[str, str, str]] = set()
    merged: list[ExtractedRelation] = []

    for rel in llm_relations + inferred_relations:
        key = (rel.relation_type, rel.source_name.lower(), rel.target_name.lower())
        if key in seen:
            continue
        seen.add(key)
        merged.append(rel)
    return merged


def infer_relations(
    entities: list[ExtractedEntity],
    *,
    max_relations_per_entity: int = 10,
) -> list[ExtractedRelation]:
    if len(entities) < 2:
        return []

    relation_counts: dict[str, int] = {entity.name.lower(): 0 for entity in entities}
    inferred: list[ExtractedRelation] = []
    seen: set[tuple[str, str, str]] = set()

    for i, left in enumerate(entities):
        for right in entities[i + 1 :]:
            if not _should_link(left, right):
                continue

            rel_type = _pick_relation_type(left, right) or _CO_OCCURS
            source, target = _direct_entities(left, right, rel_type)
            key = (rel_type, source.name.lower(), target.name.lower())
            if key in seen:
                continue

            if relation_counts[source.name.lower()] >= max_relations_per_entity:
                continue
            if relation_counts[target.name.lower()] >= max_relations_per_entity:
                continue

            seen.add(key)
            relation_counts[source.name.lower()] += 1
            relation_counts[target.name.lower()] += 1
            inferred.append(
                ExtractedRelation(
                    relation_type=rel_type,
                    source_name=source.name,
                    source_type=source.entity_type,
                    target_name=target.name,
                    target_type=target.entity_type,
                    attributes={"inferred": True},
                    evidence=_shared_evidence(source, right),
                )
            )

    return inferred


def _tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[\w\-]+", text.lower()) if len(token) >= 4}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def _should_link(left: ExtractedEntity, right: ExtractedEntity) -> bool:
    left_evidence = _normalize_text(left.evidence or "")
    right_evidence = _normalize_text(right.evidence or "")
    left_name = left.name.lower().strip()
    right_name = right.name.lower().strip()

    if left_evidence and right_evidence and left_evidence == right_evidence:
        return True

    if len(right_name) >= 4 and right_name in left_evidence:
        return True
    if len(left_name) >= 4 and left_name in right_evidence:
        return True

    if left_evidence and right_evidence:
        overlap = _tokenize(left_evidence) & _tokenize(right_evidence)
        if len(overlap) >= 3:
            return True

    return False


def _shared_evidence(left: ExtractedEntity, right: ExtractedEntity) -> str | None:
    left_evidence = (left.evidence or "").strip()
    right_evidence = (right.evidence or "").strip()
    if left_evidence and right_evidence and _normalize_text(left_evidence) == _normalize_text(right_evidence):
        return left_evidence
    if len(right.name) >= 4 and right.name.lower() in (left.evidence or "").lower():
        return left.evidence
    if len(left.name) >= 4 and left.name.lower() in (right.evidence or "").lower():
        return right.evidence
    return left.evidence or right.evidence


def _pick_relation_type(left: ExtractedEntity, right: ExtractedEntity) -> str | None:
    left_type = normalize_entity_type(left.entity_type)
    right_type = normalize_entity_type(right.entity_type)
    direct = EDGE_TYPE_MAP.get((left_type, right_type))
    if direct:
        return direct[0]
    reverse = EDGE_TYPE_MAP.get((right_type, left_type))
    if reverse:
        return reverse[0]
    return None


def _direct_entities(
    left: ExtractedEntity,
    right: ExtractedEntity,
    relation_type: str,
) -> tuple[ExtractedEntity, ExtractedEntity]:
    left_type = normalize_entity_type(left.entity_type)
    right_type = normalize_entity_type(right.entity_type)

    for (source_type, target_type), relation_types in EDGE_TYPE_MAP.items():
        if relation_type not in relation_types:
            continue
        if left_type == source_type and right_type == target_type:
            return left, right
        if right_type == source_type and left_type == target_type:
            return right, left

    return left, right
