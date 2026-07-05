"""Визуализация графа знаний для вкладки «Чат с LLM»."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.neo4j import get_neo4j_driver
from app.ingestion.entity_store import IngestedEntityStore
from app.ontology.entities import ENTITY_TYPE_NAMES

_MATERIAL_TYPES = {"material"}
_PROCESS_TYPES = {"process"}
_EQUIPMENT_TYPES = {"equipment"}
_RESULT_TYPES = {"property", "experiment", "material"}


@dataclass
class GraphNode:
    id: str
    label: str
    entity_type: str
    color: str = "#4a90d9"


@dataclass
class GraphEdge:
    source: str
    target: str
    label: str = ""


@dataclass
class ProcessChain:
    material: str
    process: str | None = None
    equipment: str | None = None
    result: str | None = None


@dataclass
class ChatGraphData:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    chains: list[ProcessChain] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    experts: list[str] = field(default_factory=list)
    facilities: list[str] = field(default_factory=list)


_TYPE_COLORS = {
    "Material": "#5b8def",
    "Process": "#6bbf59",
    "Equipment": "#e6a23c",
    "Property": "#9b59b6",
    "Experiment": "#e74c3c",
    "Expert": "#1abc9c",
    "Facility": "#34495e",
    "Publication": "#95a5a6",
}

_STOP_WORDS = {
    "и", "в", "на", "по", "для", "как", "что", "the", "a", "an", "vs", "или",
    "найти", "найди", "покажи", "расскажи", "информацию", "информация", "данные",
    "про", "об", "о", "ли", "где", "когда", "какой", "какая", "какие", "есть",
    "нужно", "можно", "мне", "этот", "эта", "эти", "том", "этом", "базе", "база",
    "документ", "документы", "статья", "статьи", "источник", "источники",
}


class ChatGraphVisualizationService:
    def __init__(self, entity_store: IngestedEntityStore | None = None) -> None:
        self.entity_store = entity_store or IngestedEntityStore()

    def build_for_query(self, query: str) -> ChatGraphData:
        keywords = _extract_keywords(query)
        patterns = _build_search_patterns(query)

        data = ChatGraphData()
        data.chains = self._find_process_chains(patterns)
        data.gaps = self._detect_gaps(query, keywords, data.chains)
        data.experts = self._find_entities_by_type(patterns, "Expert", limit=8)
        data.facilities = self._find_entities_by_type(patterns, "Facility", limit=8)

        node_ids: set[str] = set()
        edge_keys: set[tuple[str, str, str]] = set()

        for chain in data.chains:
            self._add_chain_nodes(data, chain, node_ids)
        for name in data.experts:
            self._add_node(data, node_ids, name, "Expert")
        for name in data.facilities:
            self._add_node(data, node_ids, name, "Facility")

        seeds = self._find_seed_entities(patterns, limit=12)
        if not seeds:
            seeds = self._vector_search_entities(query, limit=12)

        self._expand_entity_relations(data, seeds, node_ids, edge_keys)

        return data

    def _find_process_chains(self, patterns: list[str]) -> list[ProcessChain]:
        if not patterns:
            return []

        with get_neo4j_driver().session() as session:
            result = session.run(
                """
                MATCH (mat:IngestedEntity)
                WHERE toLower(mat.entity_type) IN $material_types
                  AND ANY(p IN $patterns WHERE toLower(mat.name) CONTAINS toLower(p)
                      OR toLower(coalesce(mat.evidence, '')) CONTAINS toLower(p))
                OPTIONAL MATCH (mat)-[:INGESTED_RELATION]->(proc:IngestedEntity)
                WHERE toLower(proc.entity_type) IN $process_types
                OPTIONAL MATCH (proc)-[:INGESTED_RELATION]->(eq:IngestedEntity)
                WHERE toLower(eq.entity_type) IN $equipment_types
                OPTIONAL MATCH (eq)-[:INGESTED_RELATION]->(res:IngestedEntity)
                WHERE toLower(res.entity_type) IN $result_types
                RETURN mat.name AS material,
                       proc.name AS process,
                       eq.name AS equipment,
                       res.name AS result
                LIMIT 15
                """,
                patterns=patterns,
                material_types=list(_MATERIAL_TYPES),
                process_types=list(_PROCESS_TYPES),
                equipment_types=list(_EQUIPMENT_TYPES),
                result_types=list(_RESULT_TYPES),
            )
            chains: list[ProcessChain] = []
            seen: set[tuple] = set()
            for row in result:
                key = (row["material"], row.get("process"), row.get("equipment"), row.get("result"))
                if key in seen:
                    continue
                seen.add(key)
                chains.append(
                    ProcessChain(
                        material=row["material"],
                        process=row.get("process"),
                        equipment=row.get("equipment"),
                        result=row.get("result"),
                    )
                )
            return chains

    def _find_seed_entities(self, patterns: list[str], limit: int) -> list[dict]:
        if not patterns:
            return []

        with get_neo4j_driver().session() as session:
            result = session.run(
                """
                MATCH (e:IngestedEntity)
                WHERE ANY(p IN $patterns WHERE
                    toLower(e.name) CONTAINS toLower(p)
                    OR toLower(coalesce(e.evidence, '')) CONTAINS toLower(p))
                RETURN DISTINCT e.id AS id, e.name AS name, e.entity_type AS entity_type
                LIMIT $limit
                """,
                patterns=patterns,
                limit=limit,
            )
            return [dict(row) for row in result]

    def _vector_search_entities(self, query: str, limit: int) -> list[dict]:
        try:
            self.entity_store.ensure_schema()
            rows = self.entity_store.search_by_embedding(query, top_k=limit)
            return [
                {"id": row["id"], "name": row["name"], "entity_type": row["entity_type"]}
                for row in rows
                if row.get("id") and row.get("name")
            ]
        except Exception:
            return []

    def _expand_entity_relations(
        self,
        data: ChatGraphData,
        seeds: list[dict],
        node_ids: set[str],
        edge_keys: set[tuple[str, str, str]],
    ) -> None:
        if not seeds:
            return

        seed_ids = [s["id"] for s in seeds if s.get("id")]
        with get_neo4j_driver().session() as session:
            result = session.run(
                """
                MATCH (e:IngestedEntity)
                WHERE e.id IN $seed_ids
                OPTIONAL MATCH (e)-[r:INGESTED_RELATION]-(n:IngestedEntity)
                RETURN e.id AS source_id, e.name AS source_name, e.entity_type AS source_type,
                       n.id AS target_id, n.name AS target_name, n.entity_type AS target_type,
                       coalesce(r.relation_type, '') AS relation_type
                LIMIT 80
                """,
                seed_ids=seed_ids,
            )
            for row in result:
                src_name = row.get("source_name")
                if not src_name:
                    continue
                src_type = _normalize_entity_type(row.get("source_type") or "Entity")
                src_nid = self._add_node(data, node_ids, src_name, src_type)

                tgt_name = row.get("target_name")
                if not tgt_name:
                    continue
                tgt_type = _normalize_entity_type(row.get("target_type") or "Entity")
                tgt_nid = self._add_node(data, node_ids, tgt_name, tgt_type)

                rel = row.get("relation_type") or "→"
                edge_key = (src_nid, tgt_nid, rel)
                if edge_key in edge_keys:
                    continue
                edge_keys.add(edge_key)
                data.edges.append(GraphEdge(source=src_nid, target=tgt_nid, label=rel))

    def _detect_gaps(
        self,
        query: str,
        keywords: list[str],
        chains: list[ProcessChain],
    ) -> list[str]:
        gaps: list[str] = []
        q_lower = query.lower()

        has_material = any(k in q_lower for k in ("никел", "руда", "сплав", "material"))
        has_process = any(k in q_lower for k in ("выщелач", "экстрак", "плавк", "process"))
        has_climate = any(k in q_lower for k in ("холод", "климат", "север"))

        if has_material and has_process:
            with get_neo4j_driver().session() as session:
                count = session.run(
                    """
                    MATCH (e:IngestedEntity)
                    WHERE toLower(e.entity_type) = 'experiment'
                      AND ANY(k IN $keywords WHERE toLower(e.name) CONTAINS toLower(k)
                           OR toLower(coalesce(e.evidence, '')) CONTAINS toLower(k))
                    RETURN count(e) AS c
                    """,
                    keywords=keywords[:5] or [query[:30]],
                ).single()
                exp_count = int(count["c"]) if count else 0
                if exp_count == 0:
                    combo = " + ".join(keywords[:3]) if keywords else query[:80]
                    gaps.append(
                        f"Нет экспериментов для комбинации: {combo}"
                    )

        if has_climate and has_process and not any(
            c.process and "выщелач" in (c.process or "").lower() for c in chains
        ):
            gaps.append(
                "Пробел: нет данных по сочетанию «холодный климат + кучное выщелачивание + никелевая руда»"
            )

        incomplete = [c for c in chains if c.material and not c.process]
        if incomplete and len(incomplete) == len(chains):
            gaps.append(
                f"Неполные цепочки: для материала «{incomplete[0].material}» не найден связанный процесс"
            )

        with get_neo4j_driver().session() as session:
            kw = keywords[:5] or [query[:20]]
            contradict = session.run(
                """
                MATCH (a:IngestedEntity)-[r:INGESTED_RELATION {relation_type: 'contradicts'}]->(b:IngestedEntity)
                WHERE ANY(k IN $keywords WHERE toLower(a.name) CONTAINS toLower(k)
                       OR toLower(b.name) CONTAINS toLower(k))
                RETURN a.name AS src, b.name AS tgt
                LIMIT 5
                """,
                keywords=kw,
            )
            for row in contradict:
                gaps.append(f"Противоречие: «{row['src']}» contradicts «{row['tgt']}»")

        return gaps

    def _find_entities_by_type(
        self,
        patterns: list[str],
        entity_type: str,
        limit: int,
    ) -> list[str]:
        if not patterns:
            return []

        with get_neo4j_driver().session() as session:
            result = session.run(
                """
                MATCH (e:IngestedEntity)
                WHERE toLower(e.entity_type) = toLower($entity_type)
                  AND ANY(p IN $patterns WHERE toLower(e.name) CONTAINS toLower(p)
                      OR toLower(coalesce(e.evidence, '')) CONTAINS toLower(p))
                RETURN DISTINCT e.name AS name
                ORDER BY e.name
                LIMIT $limit
                """,
                patterns=patterns,
                entity_type=entity_type,
                limit=limit,
            )
            return [row["name"] for row in result if row.get("name")]

    def _add_chain_nodes(self, data: ChatGraphData, chain: ProcessChain, node_ids: set[str]) -> None:
        prev_id: str | None = None
        steps = [
            ("Material", chain.material),
            ("Process", chain.process),
            ("Equipment", chain.equipment),
            ("Property", chain.result),
        ]
        for etype, name in steps:
            if not name:
                continue
            nid = self._add_node(data, node_ids, name, etype)
            if prev_id:
                data.edges.append(GraphEdge(source=prev_id, target=nid, label="→"))
            prev_id = nid

    def _add_node(
        self,
        data: ChatGraphData,
        node_ids: set[str],
        name: str,
        entity_type: str,
    ) -> str:
        entity_type = _normalize_entity_type(entity_type)
        nid = f"{entity_type}:{name}"
        if nid not in node_ids:
            node_ids.add(nid)
            data.nodes.append(
                GraphNode(
                    id=nid,
                    label=name,
                    entity_type=entity_type,
                    color=_TYPE_COLORS.get(entity_type, "#888888"),
                )
            )
        return nid


def _normalize_entity_type(entity_type: str) -> str:
    lower = entity_type.strip().lower()
    for name in ENTITY_TYPE_NAMES:
        if name.lower() == lower:
            return name
    return entity_type.strip().title() or "Entity"


def _extract_keywords(query: str) -> list[str]:
    tokens = re.findall(r"[\w\-]+", query.lower())
    return [t for t in tokens if len(t) > 2 and t not in _STOP_WORDS][:8]


def _russian_stem(word: str) -> str | None:
    if len(word) < 5:
        return None
    for suffix in (
        "иями", "ами", "ях", "иях", "ого", "его", "ной", "ный", "ные",
        "ов", "ий", "ие", "ая", "ые", "ом", "ем", "ам", "е", "и", "у", "а", "я", "ь", "й",
    ):
        if word.endswith(suffix):
            root = word[: -len(suffix)]
            if len(root) >= 4:
                return root
    return None


def _build_search_patterns(query: str) -> list[str]:
    patterns: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        value = value.strip().lower()
        if len(value) < 3 or value in _STOP_WORDS or value in seen:
            return
        seen.add(value)
        patterns.append(value)

    for token in re.findall(r"[\w\-]+", query.lower()):
        if len(token) <= 2 or token in _STOP_WORDS:
            continue
        add(token)
        stem = _russian_stem(token)
        if stem:
            add(stem)
        for part in token.split("-"):
            if len(part) >= 4 and part not in _STOP_WORDS:
                add(part)
                stem = _russian_stem(part)
                if stem:
                    add(stem)

    patterns.sort(key=len, reverse=True)
    if patterns:
        return patterns[:10]

    trimmed = query.strip()
    return [trimmed[:40]] if trimmed else []
