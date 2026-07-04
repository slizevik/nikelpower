"""Извлечение paragraph blocks из ParsedDocument для lexical chunking."""

from __future__ import annotations

from app.ingestion.lexical import (
    ParagraphBlock,
    detect_block_type,
    make_block_id,
    split_page_paragraphs,
)
from app.ingestion.parser import ParsedDocument


def document_to_blocks(doc: ParsedDocument) -> list[ParagraphBlock]:
    """
    Строит упорядоченный список параграфов из страниц документа.
    Каждый параграф — узел lexical graph с типом body/caption/table/heading.
    """
    blocks: list[ParagraphBlock] = []
    order = 0
    current_section: str | None = None

    for page_num, page_text in doc.pages:
        for para_text in split_page_paragraphs(page_text):
            block_type = detect_block_type(para_text)
            if block_type == "heading":
                current_section = para_text.split("\n", 1)[0].strip()[:200]

            blocks.append(
                ParagraphBlock(
                    block_id=make_block_id(doc.source_path, order),
                    page=page_num,
                    order_index=order,
                    text=para_text,
                    block_type=block_type,
                    section_hint=current_section,
                )
            )
            order += 1

    return blocks
