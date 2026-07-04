"""Визуализация графа знаний для вкладки «Чат с LLM»."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.neo4j import get_neo4j_driver


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


class ChatGraphVisualizationService:
    def build_for_query(self, query: str) -> ChatGraphData:
        keywords = _extract_keywords(query)
        pattern = keywords[0] if keywords else query[:40]

        data = ChatGraphData()
        data.chains = self._find_process_chains(pattern)
        data.gaps = self._detect_gaps(query, keywords, data.chains)
        data.experts = self._find_entities_by_type(pattern, "Expert", limit=8)
        data.facilities = self._find_entities_by_type(pattern, "Facility", limit=8)

        node_ids: set[str] = set()
        for chain in data.chains:
            self._add_chain_nodes(data, chain, node_ids)
        for name in data.experts:
            self._add_node(data, node_ids, name, "Expert")
        for name in data.facilities:
            self._add_node(data, node_ids, name, "Facility")

        return data

    def _find_process_chains(self, pattern: str) -> list[ProcessChain]:
        with get_neo4j_driver().session() as session:
            result = session.run(
                """
                MATCH (mat:IngestedEntity)
                WHERE mat.entity_type = 'Material'
                  AND toLower(mat.name) CONTAINS toLower($pattern)
                OPTIONAL MATCH (mat)-[:INGESTED_RELATION]->(proc:IngestedEntity)
                WHERE proc.entity_type = 'Process'
                OPTIONAL MATCH (proc)-[:INGESTED_RELATION]->(eq:IngestedEntity)
                WHERE eq.entity_type = 'Equipment'
                OPTIONAL MATCH (eq)-[:INGESTED_RELATION]->(res:IngestedEntity)
                WHERE res.entity_type IN ['Property', 'Experiment', 'Material']
                RETURN mat.name AS material,
                       proc.name AS process,
                       eq.name AS equipment,
                       res.name AS result
                LIMIT 15
                """,
                pattern=pattern,
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
                    MATCH (e:IngestedEntity {entity_type: 'Experiment'})
                    WHERE ANY(k IN $keywords WHERE toLower(e.name) CONTAINS toLower(k)
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

        if has_climate and has_process and not any(c.process and "выщелач" in (c.process or "").lower() for c in chains):
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

    def _find_entities_by_type(self, pattern: str, entity_type: str, limit: int) -> list[str]:
        with get_neo4j_driver().session() as session:
            result = session.run(
                """
                MATCH (e:IngestedEntity {entity_type: $entity_type})
                WHERE toLower(e.name) CONTAINS toLower($pattern)
                   OR toLower(coalesce(e.evidence, '')) CONTAINS toLower($pattern)
                RETURN DISTINCT e.name AS name
                ORDER BY e.name
                LIMIT $limit
                """,
                pattern=pattern,
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


def _extract_keywords(query: str) -> list[str]:
    stop = {"и", "в", "на", "по", "для", "как", "что", "the", "a", "an", "vs", "или"}
    tokens = re.findall(r"[\w\-]+", query.lower())
    return [t for t in tokens if len(t) > 2 and t not in stop][:8]
