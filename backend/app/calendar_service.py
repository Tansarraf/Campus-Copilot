"""Centralized academic calendar event CRUD (shared across all students)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.database import get_conn, now_iso

EVENT_CATEGORIES = (
    "Examinations",
    "Registration Deadlines",
    "Fee Deadlines",
    "Placement Drives",
    "Workshops",
    "Holidays",
    "General University Events",
)

PUBLICATION_STATUSES = ("draft", "published", "archived")


def _parse_dt(value: str | None) -> datetime | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"Invalid datetime: {value}") from exc


def validate_event_payload(
    *,
    title: str,
    category: str,
    start_datetime: str,
    end_datetime: str | None,
    publication_status: str,
) -> None:
    if not (title or "").strip():
        raise ValueError("title is required")
    if category not in EVENT_CATEGORIES:
        raise ValueError(f"category must be one of: {', '.join(EVENT_CATEGORIES)}")
    if publication_status not in PUBLICATION_STATUSES:
        raise ValueError(f"publication_status must be one of: {', '.join(PUBLICATION_STATUSES)}")
    start = _parse_dt(start_datetime)
    if start is None:
        raise ValueError("start_datetime is required")
    end = _parse_dt(end_datetime)
    if end is not None and end < start:
        raise ValueError("end_datetime must be on or after start_datetime")


def row_to_event(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "category": row["category"],
        "start_datetime": row["start_datetime"],
        "end_datetime": row["end_datetime"],
        "location": row["location"],
        "is_official": bool(row["is_official"]),
        "publication_status": row["publication_status"],
        "source_document_id": row["source_document_id"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "seed_key": row["seed_key"],
        "is_demo": bool(row["seed_key"]),
    }


def list_events(
    *,
    published_only: bool = True,
    category: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if published_only:
        clauses.append("publication_status = 'published'")
    elif not include_archived:
        clauses.append("publication_status IN ('draft', 'published')")
    if category:
        clauses.append("category = ?")
        params.append(category)
    if from_date:
        clauses.append("date(start_datetime) >= date(?)")
        params.append(from_date)
    if to_date:
        clauses.append("date(start_datetime) <= date(?)")
        params.append(to_date)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT * FROM academic_events {where}
                ORDER BY start_datetime ASC, id ASC""",
            params,
        ).fetchall()
    return [row_to_event(r) for r in rows]


def get_event(event_id: int, *, published_only: bool = False) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM academic_events WHERE id = ?", (event_id,)
        ).fetchone()
    if not row:
        return None
    if published_only and row["publication_status"] != "published":
        return None
    return row_to_event(row)


def create_event(payload: dict[str, Any], *, admin_id: int) -> dict[str, Any]:
    validate_event_payload(
        title=payload["title"],
        category=payload["category"],
        start_datetime=payload["start_datetime"],
        end_datetime=payload.get("end_datetime"),
        publication_status=payload.get("publication_status") or "published",
    )
    source_id = payload.get("source_document_id")
    if source_id is not None:
        with get_conn() as conn:
            exists = conn.execute(
                "SELECT id FROM documents WHERE id = ?", (int(source_id),)
            ).fetchone()
            if not exists:
                raise ValueError("source_document_id does not exist")
    ts = now_iso()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO academic_events (
                   title, description, category, start_datetime, end_datetime,
                   location, is_official, publication_status, source_document_id,
                   created_by, created_at, updated_at, seed_key
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
            (
                payload["title"].strip(),
                (payload.get("description") or None),
                payload["category"],
                payload["start_datetime"],
                payload.get("end_datetime"),
                payload.get("location"),
                1 if payload.get("is_official", True) else 0,
                payload.get("publication_status") or "published",
                source_id,
                admin_id,
                ts,
                ts,
            ),
        )
        event_id = cur.lastrowid
    return get_event(event_id)  # type: ignore[return-value]


def update_event(event_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    existing = get_event(event_id)
    if not existing:
        return None
    merged = {**existing, **{k: v for k, v in payload.items() if v is not None or k in payload}}
    # Allow explicit null for optional fields when key present
    for opt in ("description", "end_datetime", "location", "source_document_id"):
        if opt in payload:
            merged[opt] = payload[opt]
    validate_event_payload(
        title=merged["title"],
        category=merged["category"],
        start_datetime=merged["start_datetime"],
        end_datetime=merged.get("end_datetime"),
        publication_status=merged.get("publication_status") or "published",
    )
    if merged.get("source_document_id") is not None:
        with get_conn() as conn:
            exists = conn.execute(
                "SELECT id FROM documents WHERE id = ?",
                (int(merged["source_document_id"]),),
            ).fetchone()
            if not exists:
                raise ValueError("source_document_id does not exist")
    ts = now_iso()
    with get_conn() as conn:
        conn.execute(
            """UPDATE academic_events SET
                   title = ?, description = ?, category = ?,
                   start_datetime = ?, end_datetime = ?, location = ?,
                   is_official = ?, publication_status = ?,
                   source_document_id = ?, updated_at = ?
               WHERE id = ?""",
            (
                merged["title"].strip(),
                merged.get("description"),
                merged["category"],
                merged["start_datetime"],
                merged.get("end_datetime"),
                merged.get("location"),
                1 if merged.get("is_official") else 0,
                merged.get("publication_status") or "published",
                merged.get("source_document_id"),
                ts,
                event_id,
            ),
        )
    return get_event(event_id)


def delete_event(event_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM academic_events WHERE id = ?", (event_id,))
        return cur.rowcount > 0
