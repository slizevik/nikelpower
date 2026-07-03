"""
Инструкции для LLM-извлечения сущностей.

Статический GLOSSARY_LINES убран: синонимы марок и сплавов
подставляются динамически из Neo4j DictEntity (см. dictionary/resolver.py).
"""

BASE_EXTRACTION_RULES = """
Domain: mining and metallurgy R&D (hydrometallurgy, pyrometallurgy, ecology, waste processing).
Extract entities and relationships from technical documents in Russian and/or English.

Rules:
- Prefer canonical entity names from the "Known entities" section when the text refers to the same concept.
- If a new alloy grade, steel mark, or technology name appears, extract it as a new entity with its exact spelling from the text.
- Always link facts to source document context when possible via described_in.
- For numeric parameters (concentration, temperature, flow rate, throughput), create Property entities with value and unit.
- Distinguish Russian vs foreign practice in Publication.geo or Facility.geo when stated.
- Do not invent numbers; only extract values explicitly present in the text.
- Use confidence levels (high/medium/low) in validated_by when evidence is partial.
"""


def build_extraction_instructions(dynamic_context: str = "") -> str:
    """
    Собирает промпт для Graphiti: базовые правила + релевантные сущности из графа.
    dynamic_context — результат EntityDictionaryResolver.get_context_for_text().
    """
    parts = [BASE_EXTRACTION_RULES.strip()]

    if dynamic_context.strip():
        parts.append(
            "\nKnown entities from the knowledge base (treat aliases as the same concept):\n"
            + dynamic_context.strip()
        )
    else:
        parts.append(
            "\nNo prior entity dictionary context for this chunk. "
            "Extract all material grades, alloy names, and process terms exactly as written."
        )

    return "\n".join(parts)


# Обратная совместимость для модулей, импортирующих константу
EXTRACTION_INSTRUCTIONS = build_extraction_instructions()
