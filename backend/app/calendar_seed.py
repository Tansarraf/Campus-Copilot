"""Idempotent demo November 2026 academic events (seed_key based)."""
from __future__ import annotations

import sqlite3

from app.database import now_iso

# Illustrative demo events only — not verified university announcements.
DEMO_EVENTS = [
    {
        "seed_key": "demo_nov2026_placement_workshop",
        "title": "Placement Preparation Workshop",
        "description": "Resume review and mock interviews for final-year students. Demo sample event.",
        "category": "Workshops",
        "start_datetime": "2026-11-05T10:00:00+05:30",
        "end_datetime": "2026-11-05T13:00:00+05:30",
        "location": "Auditorium A",
    },
    {
        "seed_key": "demo_nov2026_placement_drive",
        "title": "Campus Placement Drive — Demo Employers",
        "description": "Illustrative placement drive day for UI testing. Not an official announcement.",
        "category": "Placement Drives",
        "start_datetime": "2026-11-12T09:00:00+05:30",
        "end_datetime": "2026-11-12T17:00:00+05:30",
        "location": "Placement Cell / Seminar Hall",
    },
    {
        "seed_key": "demo_nov2026_exam_registration",
        "title": "Examination Registration Deadline",
        "description": "Last day to register for end-semester examinations (demo).",
        "category": "Registration Deadlines",
        "start_datetime": "2026-11-15T23:59:00+05:30",
        "end_datetime": None,
        "location": None,
    },
    {
        "seed_key": "demo_nov2026_fee_deadline",
        "title": "Odd Semester Fee Payment Deadline",
        "description": "Demo fee deadline for November 2026 calendar UI testing.",
        "category": "Fee Deadlines",
        "start_datetime": "2026-11-18T23:59:00+05:30",
        "end_datetime": None,
        "location": "Accounts Office / Online Portal",
    },
    {
        "seed_key": "demo_nov2026_exams_start",
        "title": "End-Semester Examinations Begin",
        "description": "Illustrative examination commencement date for demo calendar.",
        "category": "Examinations",
        "start_datetime": "2026-11-24T09:00:00+05:30",
        "end_datetime": "2026-11-24T12:00:00+05:30",
        "location": "Examination Halls",
    },
    {
        "seed_key": "demo_nov2026_holiday",
        "title": "University Holiday — Demo Observance",
        "description": "Sample holiday entry. Not an official university holiday notice.",
        "category": "Holidays",
        "start_datetime": "2026-11-26T00:00:00+05:30",
        "end_datetime": "2026-11-26T23:59:00+05:30",
        "location": "Campus closed",
    },
]


def seed_demo_november_events(conn: sqlite3.Connection) -> int:
    """
    Insert missing demo events by seed_key.
    Never updates existing rows (admin edits are preserved across restarts).
    """
    inserted = 0
    ts = now_iso()
    for ev in DEMO_EVENTS:
        existing = conn.execute(
            "SELECT id FROM academic_events WHERE seed_key = ?",
            (ev["seed_key"],),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            """INSERT INTO academic_events (
                   title, description, category, start_datetime, end_datetime,
                   location, is_official, publication_status, source_document_id,
                   created_by, created_at, updated_at, seed_key
               ) VALUES (?, ?, ?, ?, ?, ?, 0, 'published', NULL, NULL, ?, ?, ?)""",
            (
                ev["title"],
                ev["description"],
                ev["category"],
                ev["start_datetime"],
                ev["end_datetime"],
                ev["location"],
                ts,
                ts,
                ev["seed_key"],
            ),
        )
        inserted += 1
    return inserted
