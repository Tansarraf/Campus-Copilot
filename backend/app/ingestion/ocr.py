"""
OCR helpers (Tesseract via pytesseract).

System requirement: install the Tesseract OCR engine separately and ensure
`tesseract` is on PATH (or set TESSERACT_CMD). Installing the Python package
alone is not enough.

OCR is a fallback only — callers should invoke these helpers when ordinary
text extraction is insufficient.
"""
from __future__ import annotations

import logging
import os
import shutil
from typing import Any

logger = logging.getLogger(__name__)

# Heuristic: fewer than this many alphanumeric chars → treat as insufficient.
MIN_USEFUL_CHARS = 40


def tesseract_available() -> bool:
    cmd = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
    return bool(cmd)


def configure_tesseract() -> bool:
    """Point pytesseract at the engine if configured. Returns True if usable."""
    try:
        import pytesseract
    except ImportError:
        return False
    cmd = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
    if not cmd:
        return False
    pytesseract.pytesseract.tesseract_cmd = cmd
    return True


def text_is_sufficient(text: str | None) -> bool:
    if not text:
        return False
    useful = sum(1 for ch in text if ch.isalnum())
    return useful >= MIN_USEFUL_CHARS


def ocr_image_path(path: str) -> tuple[str, dict[str, Any]]:
    """
    OCR a single image file. Returns (text, meta).
    meta.extraction_method is 'ocr' on success, 'ocr_unavailable' / 'ocr_failed' otherwise.
    """
    meta: dict[str, Any] = {"extraction_method": "ocr", "ocr_engine": "tesseract"}
    if not configure_tesseract():
        meta["extraction_method"] = "ocr_unavailable"
        meta["error"] = (
            "Tesseract executable not found. Install Tesseract OCR and add it to PATH, "
            "or set TESSERACT_CMD to the full path of tesseract.exe."
        )
        return "", meta
    try:
        from PIL import Image, UnidentifiedImageError
        import pytesseract

        try:
            with Image.open(path) as img:
                img.load()
                prepared = _prepare_for_ocr(img)
                if prepared is None:
                    raise ValueError("Could not prepare image for OCR")
                text = pytesseract.image_to_string(prepared, config="--psm 6") or ""
        except UnidentifiedImageError as exc:
            meta["extraction_method"] = "ocr_failed"
            meta["error"] = f"Unreadable or corrupted image: {exc}"
            return "", meta
        if not text.strip():
            meta["extraction_method"] = "ocr_empty"
        return text.strip(), meta
    except Exception as exc:  # noqa: BLE001 — surface gracefully to ingestion
        logger.warning("OCR failed for %s: %s", path, exc)
        meta["extraction_method"] = "ocr_failed"
        meta["error"] = str(exc)
        return "", meta


def _prepare_for_ocr(img):
    """Grayscale + mild contrast boost; keeps OCR reliable on mid-quality scans."""
    from PIL import Image, ImageOps

    if not isinstance(img, Image.Image):
        return None
    if img.mode != "L":
        img = img.convert("L")
    return ImageOps.autocontrast(img)


def ocr_pil_image(img) -> str:
    if not configure_tesseract():
        return ""
    try:
        import pytesseract
        from PIL import Image

        if not isinstance(img, Image.Image):
            return ""
        prepared = _prepare_for_ocr(img)
        if prepared is None:
            return ""
        # Assume a block of text (circulars / notices), not a single word.
        return (
            pytesseract.image_to_string(prepared, config="--psm 6") or ""
        ).strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("OCR on rendered page failed: %s", exc)
        return ""


def ocr_pdf_pages(path: str, page_texts: list[str] | None = None) -> list[dict]:
    """
    Page-level OCR fallback for PDFs.

    If page_texts is provided (parallel to PDF pages), only pages with
    insufficient text are OCR'd. Otherwise every page is OCR'd.
    """
    if not configure_tesseract():
        return []
    try:
        import pypdfium2 as pdfium
        from PIL import Image
    except ImportError:
        logger.warning("pypdfium2/Pillow required for PDF page OCR")
        return []

    units: list[dict] = []
    try:
        pdf = pdfium.PdfDocument(path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cannot open PDF for OCR: %s", exc)
        return []

    try:
        for i in range(len(pdf)):
            existing = page_texts[i] if page_texts and i < len(page_texts) else ""
            if text_is_sufficient(existing):
                units.append(
                    {
                        "text": existing.strip(),
                        "page_number": i + 1,
                        "section_label": None,
                        "extraction_method": "pdf_text",
                    }
                )
                continue
            page = pdf[i]
            # 200 DPI balances OCR quality vs memory for multi-page circulars.
            bitmap = page.render(scale=200 / 72)
            pil = bitmap.to_pil()
            if not isinstance(pil, Image.Image):
                pil = Image.fromarray(bitmap.to_numpy())
            ocr_text = ocr_pil_image(pil)
            combined = (existing or "").strip()
            if text_is_sufficient(ocr_text):
                text = ocr_text
                method = "ocr" if not combined else "pdf_text+ocr"
            elif combined:
                text = combined
                method = "pdf_text_sparse"
            else:
                text = ocr_text or ""
                method = "ocr_empty" if not text else "ocr"
            if text.strip():
                units.append(
                    {
                        "text": text.strip(),
                        "page_number": i + 1,
                        "section_label": None,
                        "extraction_method": method,
                    }
                )
    finally:
        pdf.close()
    return units
