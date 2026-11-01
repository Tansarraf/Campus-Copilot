"""
Document loaders: turn a PDF / DOCX / Markdown / plain-text / image file into a
list of (text, metadata) pairs, one per location unit (PDF page, section, or
image). OCR is used only when ordinary extraction is insufficient.
"""
from __future__ import annotations

import os
import re

from app.ingestion.ocr import (
    ocr_image_path,
    ocr_pdf_pages,
    text_is_sufficient,
)


def load_pdf(path: str) -> list[dict]:
    from langchain_community.document_loaders import PyPDFLoader

    docs = PyPDFLoader(path).load()
    page_texts: list[str] = []
    units: list[dict] = []
    any_sparse = False

    # Build a dense page list indexed by page number (0-based).
    by_page: dict[int, str] = {}
    for i, d in enumerate(docs):
        page_idx = int(d.metadata.get("page", i))
        by_page[page_idx] = d.page_content or ""

    max_page = max(by_page.keys()) if by_page else -1
    for i in range(max_page + 1):
        text = by_page.get(i, "")
        page_texts.append(text)
        if text_is_sufficient(text):
            units.append(
                {
                    "text": text.strip(),
                    "page_number": i + 1,
                    "section_label": None,
                    "extraction_method": "pdf_text",
                }
            )
        else:
            any_sparse = True

    if not any_sparse and units:
        return units

    # Mixed or scanned PDF: page-level OCR fallback for insufficient pages.
    ocr_units = ocr_pdf_pages(path, page_texts=page_texts if page_texts else None)
    if ocr_units:
        return ocr_units

    # OCR unavailable — keep whatever sparse text we have.
    if units:
        return units
    sparse = [
        {
            "text": (t or "").strip(),
            "page_number": i + 1,
            "section_label": None,
            "extraction_method": "pdf_text_sparse",
        }
        for i, t in enumerate(page_texts)
        if (t or "").strip()
    ]
    return sparse


def load_docx(path: str) -> list[dict]:
    from langchain_community.document_loaders import Docx2txtLoader

    text = Docx2txtLoader(path).load()[0].page_content
    units = _split_on_headings(text)
    for u in units:
        u["extraction_method"] = "docx_text"
    return units


def load_markdown(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    units = _split_on_headings(text)
    for u in units:
        u["extraction_method"] = "markdown_text"
    return units


def load_text(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    units = _split_on_headings(text)
    for u in units:
        u["extraction_method"] = "plain_text"
    return units


def load_image(path: str) -> list[dict]:
    text, meta = ocr_image_path(path)
    method = meta.get("extraction_method") or "ocr"
    if not text.strip():
        # Retain a placeholder unit so ingestion can record failure without crashing.
        return [
            {
                "text": "",
                "page_number": 1,
                "section_label": "Image",
                "extraction_method": method,
                "ocr_error": meta.get("error"),
            }
        ]
    return [
        {
            "text": text,
            "page_number": 1,
            "section_label": "Image",
            "extraction_method": method,
        }
    ]


_HEADING_RE = re.compile(r"^(#{1,3}\s+.*|[A-Z][A-Za-z0-9 /&'-]{3,60}:?)$", re.MULTILINE)


def _split_on_headings(text: str) -> list[dict]:
    """Best-effort section splitter: treats markdown headings ('# Title') or
    short ALL-caps-ish title-case lines as section boundaries. Falls back to
    a single 'General' section if nothing heading-like is found."""
    lines = text.splitlines()
    sections: list[dict] = []
    current_label = "General"
    current_lines: list[str] = []

    def _flush():
        body = "\n".join(current_lines).strip()
        if body:
            sections.append({"text": body, "page_number": None, "section_label": current_label})

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            _flush()
            current_label = stripped.lstrip("#").strip()
            current_lines = []
        elif _HEADING_RE.match(stripped) and len(stripped.split()) <= 8 and stripped == stripped.strip():
            _flush()
            current_label = stripped.rstrip(":")
            current_lines = []
        else:
            current_lines.append(line)
    _flush()
    return sections or [{"text": text.strip(), "page_number": None, "section_label": "General"}]


LOADERS = {
    ".pdf": load_pdf,
    ".docx": load_docx,
    ".md": load_markdown,
    ".markdown": load_markdown,
    ".txt": load_text,
    ".jpg": load_image,
    ".jpeg": load_image,
    ".png": load_image,
}


def load_document(path: str) -> tuple[list[dict], dict]:
    """
    Load document units and aggregate extraction metadata.

    Returns (units, load_meta) where load_meta includes extraction_method summary.
    Empty-text image units are filtered before chunking by the caller if needed.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in LOADERS:
        raise ValueError(f"Unsupported file type: {ext}")
    units = LOADERS[ext](path)
    methods = {u.get("extraction_method") for u in units if u.get("extraction_method")}
    if not methods:
        method = "unknown"
    elif len(methods) == 1:
        method = next(iter(methods))
    elif any(str(m).startswith("ocr") for m in methods):
        method = "mixed_text_ocr"
    else:
        method = "mixed"
    return units, {"extraction_method": method, "unit_count": len(units)}
