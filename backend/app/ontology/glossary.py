"""RU/EN domain glossary for LLM extraction prompts."""

GLOSSARY_LINES = [
    "ПВП = печь взвешенной плавки = fluidized bed furnace",
    "электроэкстракция = electrowinning",
    "кучное выщелачивание = heap leaching",
    "католит = catholyte, анолит = anolyte",
    "штейн = matte, шлак = slag",
    "МПГ = platinum group metals = PGM",
    "обессоливание = desalination / desalting of water",
    "ПВП = fluidized-bed roaster in some contexts",
]

EXTRACTION_INSTRUCTIONS = """
Domain: mining and metallurgy R&D (hydrometallurgy, pyrometallurgy, ecology, waste processing).
Extract entities and relationships from technical documents in Russian and/or English.

Glossary (treat as synonyms):
""" + "\n".join(f"- {line}" for line in GLOSSARY_LINES) + """

Rules:
- Always link facts to source document context when possible via described_in.
- For numeric parameters (concentration, temperature, flow rate, throughput), create Property entities with value and unit.
- Distinguish Russian vs foreign practice in Publication.geo or Facility.geo when stated.
- Do not invent numbers; only extract values explicitly present in the text.
- Use confidence levels (high/medium/low) in validated_by when evidence is partial.
"""
