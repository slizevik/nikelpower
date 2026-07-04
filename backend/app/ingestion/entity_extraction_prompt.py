"""
Промпт для извлечения сущностей из подготовленного документа.

Системный промпт задан в коде (ENTITY_EXTRACTION_SYSTEM_PROMPT).
Переопределение: ENTITY_EXTRACTION_PROMPT_FILE в .env
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings

ENTITY_EXTRACTION_SYSTEM_PROMPT = """You are an expert data extraction AI. Extract entities and relationships from the provided text.

**MANDATORY ENTITY CATEGORIES (CRITICAL):**
You MUST explicitly check the text for the following 8 predefined entity types. If a type is not present in the text, its list MUST be strictly empty `[]`.
1. **material**: Substances, alloys, chemicals, compounds (e.g., 'titanium', 'ti-6al-4v').
2. **process**: Methods, reactions, treatments, manufacturing steps (e.g., 'melting', 'synthesis').
3. **equipment**: Machines, tools, devices, instruments (e.g., 'microscope', 'reactor').
4. **property**: Characteristics, metrics, physical/chemical properties (e.g., 'density', 'corrosion resistance').
5. **experiment**: Specific tests, trials, studies, setups (e.g., 'tensile test', 'trial #4').
6. **publication**: Papers, articles, books, reports (e.g., 'nature paper', 'report 2023').
7. **expert**: People, researchers, authors, scientists (e.g., 'ivanov i.i.').
8. **facility**: Laboratories, institutes, plants, organizations (e.g., 'msu', 'boeing').

Any other entity types found in the text should be placed in `other_entities` with a dynamically generated `entity_type`.

**STRICT GROUNDING & ANTI-HALLUCINATION RULES:**
1. **NO HALLUCINATIONS**: Use ONLY the provided text. Do not add external knowledge.
2. **VERBATIM EVIDENCE**: The 'description' field for EVERY entity MUST contain a direct, word-for-word quote from the text.
3. **EXPERT FIELDS**: Fields `canonical_name`, `organization`, and `is_russian` MUST ONLY be filled for entities in the `experts` list. For ALL other entity types (materials, processes, etc.), these fields MUST be strictly `null`.
4. **MISSING DATA**: If an expert's metadata is not found, output JSON `null`. NEVER use strings like "None".

**RELATIONSHIPS:**
- Extract relationships between ANY extracted entities (from both mandatory and other categories).
- Ensure `source` and `target` exactly match the `name` of extracted entities.
- Use relation_type from: uses_material, operates_at_condition, produces_output, described_in, validated_by, contradicts when applicable; otherwise use a short descriptive relation_type.

**CLARIFICATION & INTERACTION PROTOCOL:**
1. **WHEN TO ASK**: You MAY ask questions in `clarification_questions` ONLY IF critical information is ambiguous.
2. **HARD LIMITS**: Check `{questions_asked_count}`. If it is 5 or more, you MUST provide the final answer immediately.
3. **FORCE ANSWER**: If `{user_force_answer}` is True, stop asking questions and output the final result.
4. **FINAL ANSWER**: When done, set `is_final_answer` to True and leave `clarification_questions` empty.

**OUTPUT FORMAT (strict JSON, no markdown):**
{
  "material": [{"name": "...", "description": "verbatim quote", "canonical_name": null, "organization": null, "is_russian": null}],
  "process": [],
  "equipment": [],
  "property": [],
  "experiment": [],
  "publication": [],
  "experts": [{"name": "...", "description": "verbatim quote", "canonical_name": null, "organization": null, "is_russian": null}],
  "facility": [],
  "other_entities": [{"entity_type": "...", "name": "...", "description": "verbatim quote"}],
  "relationships": [{"source": "...", "target": "...", "relation_type": "...", "description": "verbatim quote or null"}],
  "clarification_questions": [],
  "is_final_answer": true
}
"""

ENTITY_USER_MESSAGE_TEMPLATE = """Document Class: {doc_class}
Document Title: {doc_title}
Text to analyze:
{chunk}
File Path: {file_path}

--- INTERACTION STATE ---
Questions asked so far: {questions_asked_count}
Previous questions asked: {previous_questions}
User's answers to previous questions: {user_answers}
User forced final answer: {user_force_answer}
"""


@dataclass
class ExtractionInteractionState:
    questions_asked_count: int = 0
    previous_questions: list[str] = field(default_factory=list)
    user_answers: list[str] = field(default_factory=list)
    user_force_answer: bool = False


def _load_prompt_file(path: Path) -> str | None:
    raw = path.read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    content = "\n".join(lines).strip()
    return content or None


def get_entity_extraction_prompt() -> tuple[str, str]:
    prompt_file = settings.entity_extraction_prompt_file
    if prompt_file and prompt_file.exists():
        text = _load_prompt_file(prompt_file)
        if text:
            return text, f"file:{prompt_file}"
    return ENTITY_EXTRACTION_SYSTEM_PROMPT.strip(), "builtin"


def has_custom_prompt_file() -> bool:
    prompt_file = settings.entity_extraction_prompt_file
    if not prompt_file or not prompt_file.exists():
        return False
    return _load_prompt_file(prompt_file) is not None


def build_user_message(
    chunk: str,
    *,
    doc_class: str,
    doc_title: str,
    file_path: str,
    interaction: ExtractionInteractionState | None = None,
) -> str:
    state = interaction or ExtractionInteractionState()
    return ENTITY_USER_MESSAGE_TEMPLATE.format(
        doc_class=doc_class,
        doc_title=doc_title,
        chunk=chunk,
        file_path=file_path,
        questions_asked_count=state.questions_asked_count,
        previous_questions=state.previous_questions or [],
        user_answers=state.user_answers or [],
        user_force_answer=state.user_force_answer,
    ).strip()
