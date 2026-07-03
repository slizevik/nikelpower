"""Regex-based extraction of numeric properties from technical text."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ExtractedProperty:
    parameter_name: str
    value: float | None
    min_value: float | None
    max_value: float | None
    unit: str
    raw_match: str
    context: str


def _parse_number(s: str) -> float:
    return float(s.replace(",", ".").replace(" ", ""))


# Patterns for concentrations, temperatures, flow rates, throughput
PROPERTY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "concentration",
        re.compile(
            r"(?P<name>[а-яА-Яa-zA-Z\s\-]{2,40}?)\s*"
            r"(?:≤|>=|>|<|=|—|-)?\s*"
            r"(?P<val>\d+(?:[.,]\d+)?)\s*"
            r"(?:–|-|до\s+)?\s*"
            r"(?P<val2>\d+(?:[.,]\d+)?)?\s*"
            r"(?P<unit>мг/л|мг/дм³|г/л|ppm|mg/l|mg/L|%)",
            re.IGNORECASE,
        ),
    ),
    (
        "temperature",
        re.compile(
            r"(?P<val>\d+(?:[.,]\d+)?)\s*"
            r"(?:–|-|до\s+)?\s*"
            r"(?P<val2>\d+(?:[.,]\d+)?)?\s*"
            r"(?:°C|°С|град\.?C|K)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "flow_rate",
        re.compile(
            r"(?P<name>скорост[ьи]\s+потока|flow\s+rate|catholyte\s+circulation)"
            r"[^.\n]{0,60}?"
            r"(?P<val>\d+(?:[.,]\d+)?)\s*"
            r"(?P<unit>м/с|м³/ч|л/мин|L/min|m/s)",
            re.IGNORECASE,
        ),
    ),
    (
        "throughput",
        re.compile(
            r"(?P<val>\d+(?:[.,]\d+)?)\s*"
            r"(?:–|-|до\s+)?\s*"
            r"(?P<val2>\d+(?:[.,]\d+)?)?\s*"
            r"(?P<unit>т/сут|t/d|t/day|т/год)",
            re.IGNORECASE,
        ),
    ),
]


def extract_properties(text: str, window: int = 80) -> list[ExtractedProperty]:
    results: list[ExtractedProperty] = []
    seen: set[str] = set()

    for param_kind, pattern in PROPERTY_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(0).strip()
            if raw in seen:
                continue
            seen.add(raw)

            groups = match.groupdict()
            val = _parse_number(groups["val"]) if groups.get("val") else None
            val2_str = groups.get("val2")
            val2 = _parse_number(val2_str) if val2_str else None
            unit = (groups.get("unit") or "").strip()
            name = (groups.get("name") or param_kind).strip()

            start = max(0, match.start() - window)
            end = min(len(text), match.end() + window)
            context = text[start:end].replace("\n", " ")

            results.append(
                ExtractedProperty(
                    parameter_name=name,
                    value=val,
                    min_value=min(val, val2) if val is not None and val2 is not None else val,
                    max_value=max(val, val2) if val is not None and val2 is not None else val2,
                    unit=unit,
                    raw_match=raw,
                    context=context,
                )
            )

    return results


def enrich_chunk_text(text: str) -> str:
    """Append structured property hints to help LLM extraction."""
    props = extract_properties(text)
    if not props:
        return text

    lines = ["\n\n[extracted_numeric_properties]"]
    for p in props[:20]:
        lines.append(
            f"- {p.parameter_name}: {p.raw_match} (unit={p.unit})"
        )
    return text + "\n".join(lines)
