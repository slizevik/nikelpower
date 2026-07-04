"""Конвертация DOCX/PPTX → PDF через LibreOffice (headless)."""

from __future__ import annotations

import logging
import shutil
import subprocess
import uuid
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

CONVERTIBLE_EXTENSIONS = frozenset({".docx", ".pptx", ".doc", ".ppt"})


def ensure_pdf(source: Path) -> Path:
    """
    Возвращает путь к PDF. Если source уже PDF — без конвертации.
    DOCX/PPTX конвертируются через LibreOffice во временный каталог.
    """
    source = source.resolve()
    suffix = source.suffix.lower()
    if suffix == ".pdf":
        return source
    if suffix not in CONVERTIBLE_EXTENSIONS:
        raise ValueError(f"LibreOffice не конвертирует формат: {suffix}")

    out_dir = settings.converted_pdf_dir / uuid.uuid4().hex[:12]
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info("LibreOffice: %s → PDF в %s", source.name, out_dir)

    cmd = [
        settings.libreoffice_binary,
        "--headless",
        "--nologo",
        "--nofirststartwizard",
        "--convert-to",
        "pdf",
        "--outdir",
        str(out_dir),
        str(source),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=settings.libreoffice_timeout_sec,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"LibreOffice exit {result.returncode}: {result.stderr or result.stdout}"
        )

    pdf_path = out_dir / f"{source.stem}.pdf"
    if not pdf_path.exists():
        candidates = list(out_dir.glob("*.pdf"))
        if not candidates:
            raise FileNotFoundError(f"LibreOffice не создал PDF для {source}")
        pdf_path = candidates[0]

    stable = settings.converted_pdf_dir / f"{source.stem}_{uuid.uuid4().hex[:8]}.pdf"
    shutil.copy2(pdf_path, stable)
    shutil.rmtree(out_dir, ignore_errors=True)
    return stable
