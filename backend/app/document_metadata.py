"""Lightweight structured metadata helpers + supersession validation."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.database import get_conn, now_iso

DOCUMENT_CATEGORIES = (
    "Academic Calendar",
    "Examinations",
    "Fees",
    "Placements",
    "Scholarships",
    "Hostel",
    "Library",
    "Admissions",
    "General Notices",
)

DOCUMENT_STATUSES = ("active", "superseded", "archived")

_DATE_RE = re.compile(
    r"\b((?:19|20)\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])|"
    r"(?:0?[1-9]|[12]\d|3[01])[-/.](?:0?[1-9]|1[0-2])[-/.](?:19|20)\d{2}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+(?:19|20)\d{2})\b",
    re.IGNORECASE,
)

_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\s*[-–/]\s*((?:19|20)?\d{2})\b")


def _normalize_date_token(token: str) -> str | None:
    token = token.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%b %d %Y", "%B %d %Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(token.replace(",", ""), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def infer_document_type(filename: str, file_type: str) -> str:
    ext = (file_type or "").lower().lstrip(".")
    name = (filename or "").lower()
    if ext in ("jpg", "jpeg", "png") or name.endswith((".jpg", ".jpeg", ".png")):
        return "image_notice"
    if ext == "pdf":
        return "pdf"
    if ext == "docx":
        return "docx"
    if ext in ("md", "markdown"):
        return "markdown"
    if ext == "txt":
        return "text"
    return ext or "unknown"


def extract_lightweight_metadata(
    *,
    title: str,
    filename: str,
    category: str | None,
    department: str | None,
    academic_year: str | None,
    file_type: str,
    sample_text: str,
) -> dict[str, Any]:
    """
    Best-effort metadata from filename + text. Never invents values —
    unknown fields stay None.
    """
    text = sample_text or ""
    blob = f"{title}\n{filename}\n{text[:4000]}"

    publication_date = None
    dates = []
    for m in _DATE_RE.finditer(blob):
        norm = _normalize_date_token(m.group(1))
        if norm:
            dates.append(norm)
    if dates:
        publication_date = dates[0]

    year = academic_year
    if not year:
        ym = _YEAR_RE.search(blob)
        if ym:
            a, b = ym.group(1), ym.group(2)
            if len(b) == 2:
                b = a[:2] + b
            year = f"{a}-{b[-2:]}"

    return {
        "document_type": infer_document_type(filename, file_type),
        "publication_date": publication_date,
        "effective_date": None,
        "expiry_date": None,
        "academic_year": year,
        "department": department,
        "category": category,
        "title": title,
    }


def update_document_metadata(document_id: int, fields: dict[str, Any]) -> None:
    allowed = {
        "document_type",
        "publication_date",
        "effective_date",
        "expiry_date",
        "extraction_method",
        "processing_status",
        "document_status",
        "supersedes_document_id",
        "academic_year",
        "department",
        "category",
        "title",
        "updated_at",
    }
    sets = []
    params: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = ?")
        params.append(value)
    if not sets:
        return
    if "updated_at" not in fields:
        sets.append("updated_at = ?")
        params.append(now_iso())
    params.append(document_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE documents SET {', '.join(sets)} WHERE id = ?", params)


def get_document_row(document_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()


def _would_create_cycle(conn, newer_id: int, older_id: int) -> bool:
    """True if setting newer supersedes older would create a cycle."""
    seen = {newer_id}
    current = older_id
    while current is not None:
        if current in seen:
            return True
        seen.add(current)
        row = conn.execute(
            "SELECT supersedes_document_id FROM documents WHERE id = ?",
            (current,),
        ).fetchone()
        if not row:
            break
        current = row["supersedes_document_id"]
    return False


def set_supersession(newer_id: int, older_id: int | None) -> dict[str, Any]:
    """
    Establish or clear supersession: newer_id supersedes older_id.
    When older_id is None, clears the relationship on newer_id only
    (does not auto-reactivate previously superseded docs).
    """
    if older_id is not None and int(newer_id) == int(older_id):
        raise ValueError("A document cannot supersede itself")

    with get_conn() as conn:
        newer = conn.execute("SELECT * FROM documents WHERE id = ?", (newer_id,)).fetchone()
        if not newer:
            raise ValueError("Document not found")
        if older_id is not None:
            older = conn.execute("SELECT * FROM documents WHERE id = ?", (older_id,)).fetchone()
            if not older:
                raise ValueError("Predecessor document does not exist")
            if _would_create_cycle(conn, newer_id, older_id):
                raise ValueError("Circular supersession relationship is not allowed")

        ts = now_iso()
        conn.execute(
            """UPDATE documents SET supersedes_document_id = ?, updated_at = ?,
                   document_status = COALESCE(NULLIF(document_status, ''), 'active')
               WHERE id = ?""",
            (older_id, ts, newer_id),
        )
        if older_id is not None:
            conn.execute(
                """UPDATE documents SET document_status = 'superseded', updated_at = ?
                   WHERE id = ?""",
                (ts, older_id),
            )
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (newer_id,)).fetchone()
    return dict(row)


def list_active_document_ids() -> list[int]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id FROM documents
               WHERE COALESCE(document_status, 'active') = 'active'"""
        ).fetchall()
    return [int(r["id"]) for r in rows]


CATEGORY_QUERY_HINTS = {
    "examination": "Examinations",
    "exam": "Examinations",
    "fee": "Fees",
    "tuition": "Fees",
    "placement": "Placements",
    "internship": "Placements",
    "scholarship": "Scholarships",
    "hostel": "Hostel",
    "library": "Library",
    "admission": "Admissions",
    "calendar": "Academic Calendar",
}


def infer_query_category_boost(question: str) -> str | None:
    q = (question or "").lower()
    for hint, category in CATEGORY_QUERY_HINTS.items():
        if hint in q:
            return category
    return None
