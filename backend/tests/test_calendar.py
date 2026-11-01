"""Shared academic calendar: admin CRUD + identical visibility for all students."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


class CalendarSharedVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls._tmpdir.name, "test_calendar.db")
        os.environ["DATABASE_PATH"] = cls.db_path
        os.environ["GEMINI_API_KEY"] = "your_gemini_api_key_here"
        os.environ["USE_MOCK_LLM"] = "true"
        os.environ["JWT_SECRET"] = "test-secret-calendar"

        import importlib
        import app.config as config
        import app.database as database

        importlib.reload(config)
        importlib.reload(database)
        database.DATABASE_PATH = cls.db_path
        config.DATABASE_PATH = cls.db_path

        from app.auth import hash_password
        from app.database import get_conn, init_db, now_iso
        from app.main import app

        init_db()
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO users (
                       username, password_hash, full_name, first_name, last_name,
                       email, email_verified, account_status, role, department, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, 1, 'active', 'admin', 'Administration', ?)""",
                (
                    "admin",
                    hash_password("admin123"),
                    "Campus Admin",
                    "Campus",
                    "Admin",
                    "admin@example.com",
                    now_iso(),
                ),
            )
            for enroll, first, last in (
                ("20240000001", "Ada", "Lovelace"),
                ("20240000002", "Alan", "Turing"),
            ):
                cur = conn.execute(
                    """INSERT INTO users (
                           username, password_hash, full_name, first_name, last_name,
                           email, email_verified, account_status, role, department, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, 0, 'active', 'student', 'CSE', ?)""",
                    (
                        enroll,
                        hash_password("StudentPass1"),
                        f"{first} {last}",
                        first,
                        last,
                        f"{first.lower()}@example.com",
                        now_iso(),
                    ),
                )
                uid = cur.lastrowid
                conn.execute(
                    """INSERT INTO student_profiles (
                           user_id, enrollment_number, course, academic_year,
                           current_semester, is_demo, created_at
                       ) VALUES (?, ?, ?, ?, ?, 1, ?)""",
                    (uid, enroll, "B.Tech CSE", "2024-25", 3, now_iso()),
                )

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls._tmpdir.cleanup()

    def _admin_token(self) -> str:
        r = self.client.post("/auth/admin/login", json={"username": "admin", "password": "admin123"})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["access_token"]

    def _student_token(self, enrollment: str) -> str:
        r = self.client.post(
            "/auth/student/login",
            json={"enrollment_number": enrollment, "password": "StudentPass1"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["access_token"]

    def test_schema_and_demo_seed(self):
        from app.database import get_conn

        with get_conn() as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("academic_events", tables)
            n = conn.execute(
                "SELECT COUNT(*) AS n FROM academic_events WHERE seed_key IS NOT NULL"
            ).fetchone()["n"]
        self.assertGreaterEqual(n, 6)

        # Idempotent reseed
        from app.calendar_seed import seed_demo_november_events
        from app.database import get_conn

        with get_conn() as conn:
            inserted = seed_demo_november_events(conn)
            n2 = conn.execute(
                "SELECT COUNT(*) AS n FROM academic_events WHERE seed_key IS NOT NULL"
            ).fetchone()["n"]
        self.assertEqual(inserted, 0)
        self.assertEqual(n2, n)

    def test_students_see_same_published_demo_events(self):
        t1 = self._student_token("20240000001")
        t2 = self._student_token("20240000002")
        e1 = self.client.get("/calendar/events", headers={"Authorization": f"Bearer {t1}"})
        e2 = self.client.get("/calendar/events", headers={"Authorization": f"Bearer {t2}"})
        self.assertEqual(e1.status_code, 200)
        self.assertEqual(e2.status_code, 200)
        ids1 = [x["id"] for x in e1.json()]
        ids2 = [x["id"] for x in e2.json()]
        self.assertEqual(ids1, ids2)
        self.assertTrue(any(x.get("is_demo") for x in e1.json()))

    def test_shared_admin_create_edit_delete_workflow(self):
        admin = self._admin_token()
        ah = {"Authorization": f"Bearer {admin}"}

        # Student cannot create
        st = self._student_token("20240000001")
        denied = self.client.post(
            "/admin/calendar/events",
            headers={"Authorization": f"Bearer {st}"},
            json={
                "title": "Should fail",
                "category": "Examinations",
                "start_datetime": "2026-11-10T09:00:00",
            },
        )
        self.assertIn(denied.status_code, (401, 403))

        created = self.client.post(
            "/admin/calendar/events",
            headers=ah,
            json={
                "title": "Shared Nov 10 Event",
                "description": "Visible to every student",
                "category": "General University Events",
                "start_datetime": "2026-11-10T10:00:00+05:30",
                "end_datetime": "2026-11-10T12:00:00+05:30",
                "location": "Main Hall",
                "is_official": True,
                "publication_status": "published",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        event_id = created.json()["id"]
        self.assertFalse(created.json()["is_demo"])
        self.assertTrue(created.json()["is_official"])

        # Existing students A and B
        for enroll in ("20240000001", "20240000002"):
            tok = self._student_token(enroll)
            events = self.client.get(
                "/calendar/events", headers={"Authorization": f"Bearer {tok}"}
            ).json()
            match = [e for e in events if e["id"] == event_id]
            self.assertEqual(len(match), 1)
            self.assertEqual(match[0]["title"], "Shared Nov 10 Event")

        # Newly registered student after event creation
        from app.auth import hash_password
        from app.database import get_conn, now_iso

        with get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO users (
                       username, password_hash, full_name, first_name, last_name,
                       email, email_verified, account_status, role, department, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, 0, 'active', 'student', 'CSE', ?)""",
                (
                    "20240000099",
                    hash_password("StudentPass1"),
                    "New Student",
                    "New",
                    "Student",
                    "new@example.com",
                    now_iso(),
                ),
            )
            uid = cur.lastrowid
            conn.execute(
                """INSERT INTO student_profiles (
                       user_id, enrollment_number, course, academic_year,
                       current_semester, is_demo, created_at
                   ) VALUES (?, ?, ?, ?, ?, 0, ?)""",
                (uid, "20240000099", "B.Tech CSE", "2024-25", 1, now_iso()),
            )

        tok_new = self._student_token("20240000099")
        events_new = self.client.get(
            "/calendar/events", headers={"Authorization": f"Bearer {tok_new}"}
        ).json()
        self.assertTrue(any(e["id"] == event_id for e in events_new))

        # Edit
        patched = self.client.patch(
            f"/admin/calendar/events/{event_id}",
            headers=ah,
            json={"title": "Shared Nov 10 Event (Updated)", "location": "Hall B"},
        )
        self.assertEqual(patched.status_code, 200, patched.text)
        self.assertEqual(patched.json()["title"], "Shared Nov 10 Event (Updated)")

        for enroll in ("20240000001", "20240000002", "20240000099"):
            tok = self._student_token(enroll)
            events = self.client.get(
                "/calendar/events", headers={"Authorization": f"Bearer {tok}"}
            ).json()
            match = next(e for e in events if e["id"] == event_id)
            self.assertEqual(match["title"], "Shared Nov 10 Event (Updated)")
            self.assertEqual(match["location"], "Hall B")

        # Draft hidden from students
        self.client.patch(
            f"/admin/calendar/events/{event_id}",
            headers=ah,
            json={"publication_status": "draft"},
        )
        hidden = self.client.get(
            "/calendar/events", headers={"Authorization": f"Bearer {tok_new}"}
        ).json()
        self.assertFalse(any(e["id"] == event_id for e in hidden))

        # Republish then delete
        self.client.patch(
            f"/admin/calendar/events/{event_id}",
            headers=ah,
            json={"publication_status": "published"},
        )
        deleted = self.client.delete(f"/admin/calendar/events/{event_id}", headers=ah)
        self.assertEqual(deleted.status_code, 204)
        gone = self.client.get(
            "/calendar/events", headers={"Authorization": f"Bearer {tok_new}"}
        ).json()
        self.assertFalse(any(e["id"] == event_id for e in gone))

    def test_invalid_date_range_rejected(self):
        admin = self._admin_token()
        r = self.client.post(
            "/admin/calendar/events",
            headers={"Authorization": f"Bearer {admin}"},
            json={
                "title": "Bad range",
                "category": "Holidays",
                "start_datetime": "2026-11-20T10:00:00",
                "end_datetime": "2026-11-19T10:00:00",
            },
        )
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
