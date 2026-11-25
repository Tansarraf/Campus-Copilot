"""Smart Notifications: document/calendar fan-out, APIs, isolation, dedupe."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


class SmartNotificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls._tmpdir.name, "notif_test.db")
        cls.docs_dir = os.path.join(cls._tmpdir.name, "uploaded_documents")
        os.environ["DATABASE_PATH"] = cls.db_path
        os.environ["DOCUMENTS_DIR"] = cls.docs_dir
        os.environ["GEMINI_API_KEY"] = "your_gemini_api_key_here"
        os.environ["USE_MOCK_LLM"] = "true"
        os.environ["JWT_SECRET"] = "test-secret-notifications"

        import importlib
        import app.config as config
        import app.database as database
        import app.auth as auth
        import app.notification_service as notification_service
        import app.calendar_service as calendar_service
        import app.routers.auth_router as auth_router
        import app.routers.documents_router as documents_router
        import app.routers.notifications_router as notifications_router
        import app.routers.calendar_router as calendar_router
        import app.main as main

        importlib.reload(config)
        importlib.reload(database)
        database.DATABASE_PATH = cls.db_path
        config.DATABASE_PATH = cls.db_path
        config.DOCUMENTS_DIR = cls.docs_dir
        importlib.reload(auth)
        importlib.reload(notification_service)
        importlib.reload(calendar_service)
        importlib.reload(auth_router)
        importlib.reload(documents_router)
        importlib.reload(notifications_router)
        importlib.reload(calendar_router)
        importlib.reload(main)

        from app.auth import hash_password
        from app.database import get_conn, init_db, now_iso

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
            for enrollment, name, email in (
                ("20240000011", "Alice One", "alice@example.com"),
                ("20240000022", "Bob Two", "bob@example.com"),
            ):
                cur = conn.execute(
                    """INSERT INTO users (
                           username, password_hash, full_name, first_name, last_name,
                           email, email_verified, account_status, role, department, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, 0, 'active', 'student', 'CSE', ?)""",
                    (
                        enrollment,
                        hash_password("pass111111"),
                        name,
                        name.split()[0],
                        name.split()[1],
                        email,
                        now_iso(),
                    ),
                )
                conn.execute(
                    """INSERT INTO student_profiles (
                           user_id, enrollment_number, course, academic_year,
                           current_semester, is_demo, created_at
                       ) VALUES (?, ?, ?, ?, ?, 1, ?)""",
                    (cur.lastrowid, enrollment, "B.Tech CSE", "2024-25", 3, now_iso()),
                )

        cls.client = TestClient(main.app)
        cls.admin = cls.client.post(
            "/auth/admin/login", json={"username": "admin", "password": "admin123"}
        ).json()["access_token"]
        cls.alice = cls.client.post(
            "/auth/student/login",
            json={"enrollment_number": "20240000011", "password": "pass111111"},
        ).json()["access_token"]
        cls.bob = cls.client.post(
            "/auth/student/login",
            json={"enrollment_number": "20240000022", "password": "pass111111"},
        ).json()["access_token"]
        cls.notification_service = notification_service
        cls.database = database

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def setUp(self):
        # Keep tests independent (seeded deadline reminders may exist from startup).
        from app.database import get_conn

        with get_conn() as conn:
            conn.execute("DELETE FROM notifications")
        # Avoid lazy reminder scans muddying unread counts during API tests.
        self._reminder_patch = mock.patch.object(
            self.notification_service, "process_deadline_reminders", return_value=0
        )
        self._reminder_patch.start()
        self.addCleanup(self._reminder_patch.stop)

    def _auth(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    def test_student_apis_and_isolation(self):
        # Admin cannot use student notification endpoints.
        r = self.client.get("/notifications", headers=self._auth(self.admin))
        self.assertEqual(r.status_code, 403)

        empty = self.client.get("/notifications", headers=self._auth(self.alice))
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json()["total"], 0)

        # Fan-out a synthetic notification only to students.
        n = self.notification_service.fan_out_to_students(
            title="Hello",
            message="World",
            notification_type="document_new",
            dedupe_key="test_iso_1",
            related_document_id=None,
        )
        self.assertEqual(n, 2)

        alice = self.client.get("/notifications", headers=self._auth(self.alice)).json()
        bob = self.client.get("/notifications", headers=self._auth(self.bob)).json()
        self.assertEqual(alice["unread_count"], 1)
        self.assertEqual(bob["unread_count"], 1)
        alice_id = alice["items"][0]["id"]
        bob_id = bob["items"][0]["id"]
        self.assertNotEqual(alice_id, bob_id)

        # Alice cannot mark Bob's notification.
        denied = self.client.post(
            f"/notifications/{bob_id}/read", headers=self._auth(self.alice)
        )
        self.assertEqual(denied.status_code, 404)

        ok = self.client.post(
            f"/notifications/{alice_id}/read", headers=self._auth(self.alice)
        )
        self.assertEqual(ok.status_code, 200)
        after = self.client.get(
            "/notifications/unread-count", headers=self._auth(self.alice)
        ).json()
        self.assertEqual(after["unread_count"], 0)
        bob_still = self.client.get(
            "/notifications/unread-count", headers=self._auth(self.bob)
        ).json()
        self.assertEqual(bob_still["unread_count"], 1)

        # Mark all as read for Bob.
        self.client.post("/notifications/read-all", headers=self._auth(self.bob))
        bob_zero = self.client.get(
            "/notifications/unread-count", headers=self._auth(self.bob)
        ).json()
        self.assertEqual(bob_zero["unread_count"], 0)

    def test_document_upload_notifies_and_dedupes(self):
        payload = {
            "title": "Fee Circular Smart Notify",
            "category": "Fees",
            "department": "Accounts",
            "academic_year": "2026-27",
        }
        files = {
            "file": (
                "fee_notify.txt",
                b"Tuition fee deadline 15 November 2026. Form FR-2026-99.",
                "text/plain",
            )
        }
        with mock.patch("app.routers.documents_router.index_document_chunks", return_value=1):
            up = self.client.post(
                "/documents/upload",
                headers=self._auth(self.admin),
                data=payload,
                files=files,
            )
        self.assertIn(up.status_code, (200, 201), up.text)
        doc_id = up.json()["id"]

        alice = self.client.get("/notifications", headers=self._auth(self.alice)).json()
        titles = [i["title"] for i in alice["items"]]
        self.assertTrue(any("Fee Circular Smart Notify" in t for t in titles))
        match = next(i for i in alice["items"] if i["related_document_id"] == doc_id)
        self.assertEqual(match["notification_type"], "document_new")

        # Restart-style re-notify must not duplicate.
        from app.database import get_conn as gc

        with gc() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        again = self.notification_service.notify_document_published(dict(row))
        self.assertEqual(again, 0)

    def test_supersede_notifies(self):
        with mock.patch("app.routers.documents_router.index_document_chunks", return_value=1):
            old = self.client.post(
                "/documents/upload",
                headers=self._auth(self.admin),
                data={
                    "title": "Old Hostel Rules",
                    "category": "Hostel",
                    "department": "",
                    "academic_year": "2025-26",
                },
                files={"file": ("old_hostel.txt", b"Gate closes at 9 PM.", "text/plain")},
            )
            new = self.client.post(
                "/documents/upload",
                headers=self._auth(self.admin),
                data={
                    "title": "New Hostel Rules",
                    "category": "Hostel",
                    "department": "",
                    "academic_year": "2026-27",
                },
                files={"file": ("new_hostel.txt", b"Gate closes at 10 PM.", "text/plain")},
            )
        self.assertIn(old.status_code, (200, 201), old.text)
        self.assertIn(new.status_code, (200, 201), new.text)
        old_id = old.json()["id"]
        new_id = new.json()["id"]
        super_r = self.client.post(
            f"/documents/{new_id}/supersede",
            headers=self._auth(self.admin),
            json={"supersedes_document_id": old_id},
        )
        self.assertEqual(super_r.status_code, 200)
        alice = self.client.get("/notifications", headers=self._auth(self.alice)).json()
        types = [i["notification_type"] for i in alice["items"] if i["related_document_id"] == new_id]
        self.assertIn("document_superseded", types)

    def test_calendar_publish_update_cancel_and_deadline(self):
        created = self.client.post(
            "/admin/calendar/events",
            headers=self._auth(self.admin),
            json={
                "title": "Fee Payment Deadline Notify",
                "description": "Pay odd semester fees",
                "category": "Fee Deadlines",
                "start_datetime": "2026-12-01T23:59:00+05:30",
                "publication_status": "published",
                "is_official": True,
            },
        )
        self.assertIn(created.status_code, (200, 201), created.text)
        event_id = created.json()["id"]

        alice = self.client.get("/notifications", headers=self._auth(self.alice)).json()
        self.assertTrue(
            any(
                i["related_event_id"] == event_id and i["notification_type"] == "calendar_new"
                for i in alice["items"]
            )
        )

        updated = self.client.patch(
            f"/admin/calendar/events/{event_id}",
            headers=self._auth(self.admin),
            json={"start_datetime": "2026-12-05T23:59:00+05:30"},
        )
        self.assertEqual(updated.status_code, 200)
        alice2 = self.client.get("/notifications", headers=self._auth(self.alice)).json()
        self.assertTrue(
            any(
                i["related_event_id"] == event_id and i["notification_type"] == "calendar_updated"
                for i in alice2["items"]
            )
        )

        # Deadline reminder for "today = event_date - 3 days" (call real implementation).
        self._reminder_patch.stop()
        event_day = date(2026, 12, 5)
        today = event_day - timedelta(days=3)
        first = self.notification_service.process_deadline_reminders(today=today)
        self.assertGreaterEqual(first, 2)  # alice + bob
        second = self.notification_service.process_deadline_reminders(today=today)
        self.assertEqual(second, 0)  # idempotent
        self._reminder_patch.start()

        deleted = self.client.delete(
            f"/admin/calendar/events/{event_id}",
            headers=self._auth(self.admin),
        )
        self.assertEqual(deleted.status_code, 204)
        alice3 = self.client.get("/notifications", headers=self._auth(self.alice)).json()
        self.assertTrue(
            any(i["notification_type"] == "calendar_cancelled" for i in alice3["items"])
        )

    def test_draft_event_does_not_notify(self):
        before = self.client.get(
            "/notifications/unread-count", headers=self._auth(self.alice)
        ).json()["unread_count"]
        draft = self.client.post(
            "/admin/calendar/events",
            headers=self._auth(self.admin),
            json={
                "title": "Secret Draft Event",
                "category": "Workshops",
                "start_datetime": "2026-12-20T10:00:00+05:30",
                "publication_status": "draft",
            },
        )
        self.assertIn(draft.status_code, (200, 201), draft.text)
        after = self.client.get(
            "/notifications/unread-count", headers=self._auth(self.alice)
        ).json()["unread_count"]
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
