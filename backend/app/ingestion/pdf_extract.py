"""Извлечение текста и изображений из PDF (PyMuPDF)."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from app.config import settings
from app.ingestion.language import detect_language_hint
from app.ingestion.models import DocumentImage

logger = logging.getLogger(__name__)


def _image_id(source_path: str, xref: int) -> str:
    key = f"{source_path}:xref{xref}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _passes_size_filter(width: int, height: int, data_len: int) -> bool:
    if data_len < settings.min_image_bytes:
        return False
    if width > 0 and height > 0:
        if width < settings.min_image_width or height < settings.min_image_height:
            return False
    return True


def extract_pdf_content(
    pdf_path: Path, source_path: str
) -> tuple[list[tuple[int, str]], list[DocumentImage], str]:
    import fitz

    pages: list[tuple[int, str]] = []
    images: list[DocumentImage] = []
    xref_to_image: dict[int, DocumentImage] = {}

    with fitz.open(pdf_path) as doc:
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            page_images: list[str] = []

            for img in page.get_images(full=True):
                xref = img[0]
                if xref in xref_to_image:
                    page_images.append(f"[IMG:{xref_to_image[xref].image_id}]")
                    continue

                try:
                    base = doc.extract_image(xref)
                except Exception as exc:
                    logger.warning("Не удалось извлечь xref=%s: %s", xref, exc)
                    continue

                data = base.get("image") or b""
                width = int(img[2]) if len(img) > 2 else 0
                height = int(img[3]) if len(img) > 3 else 0
                if not _passes_size_filter(width, height, len(data)):
                    continue

                mime = base.get("ext", "png")
                if mime == "jpeg":
                    mime = "jpg"
                mime_type = f"image/{mime}" if not mime.startswith("image/") else mime
                if mime in ("png", "jpg", "jpeg"):
                    mime_type = f"image/{mime.replace('jpg', 'jpeg')}"

                img_id = _image_id(source_path, xref)
                document_image = DocumentImage(
                    image_id=img_id,
                    page=page_num,
                    data=data,
                    mime=mime_type if "image/" in mime_type else f"image/{mime}",
                    width=width,
                    height=height,
                )
                xref_to_image[xref] = document_image
                images.append(document_image)
                page_images.append(f"[IMG:{img_id}]")

            if page_images:
                block = "\n".join(page_images)
                text = f"{text}\n{block}".strip() if text else block

            if text:
                pages.append((page_num, text))

    full_text = "\n\n".join(t for _, t in pages)
    lang = detect_language_hint(full_text)
    logger.info(
        "PDF %s: %s стр., %s уник. изображений (xref dedup, min %sx%s px)",
        pdf_path.name,
        len(pages),
        len(images),
        settings.min_image_width,
        settings.min_image_height,
    )
    return pages, images, lang
