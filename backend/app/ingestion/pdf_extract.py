"""Извлечение текста и изображений из PDF (PyMuPDF)."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from app.ingestion.language import detect_language_hint
from app.ingestion.models import DocumentImage

logger = logging.getLogger(__name__)

MIN_IMAGE_BYTES = 512


def _image_id(source_path: str, page: int, index: int) -> str:
    key = f"{source_path}:p{page}:i{index}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def extract_pdf_content(
    pdf_path: Path, source_path: str
) -> tuple[list[tuple[int, str]], list[DocumentImage], str]:
    import fitz

    pages: list[tuple[int, str]] = []
    images: list[DocumentImage] = []

    with fitz.open(pdf_path) as doc:
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            page_images: list[str] = []

            for img_index, img in enumerate(page.get_images(full=True)):
                xref = img[0]
                try:
                    base = doc.extract_image(xref)
                except Exception as exc:
                    logger.warning("Не удалось извлечь xref=%s: %s", xref, exc)
                    continue
                data = base.get("image") or b""
                if len(data) < MIN_IMAGE_BYTES:
                    continue
                mime = base.get("ext", "png")
                if mime == "jpeg":
                    mime = "jpg"
                mime_type = f"image/{mime}" if not mime.startswith("image/") else mime
                if mime in ("png", "jpg", "jpeg"):
                    mime_type = f"image/{mime.replace('jpg', 'jpeg')}"

                img_id = _image_id(source_path, page_num, img_index)
                images.append(
                    DocumentImage(
                        image_id=img_id,
                        page=page_num,
                        data=data,
                        mime=mime_type if "image/" in mime_type else f"image/{mime}",
                        width=img[2] if len(img) > 2 else 0,
                        height=img[3] if len(img) > 3 else 0,
                    )
                )
                page_images.append(f"[IMG:{img_id}]")

            if page_images:
                block = "\n".join(page_images)
                text = f"{text}\n{block}".strip() if text else block

            if text:
                pages.append((page_num, text))

    full_text = "\n\n".join(t for _, t in pages)
    lang = detect_language_hint(full_text)
    logger.info("PDF %s: %s стр., %s изображений", pdf_path.name, len(pages), len(images))
    return pages, images, lang
