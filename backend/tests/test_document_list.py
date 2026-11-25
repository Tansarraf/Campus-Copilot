"""Document listing: SQL pagination, category filter, student visibility."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


class DocumentListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls._tmpdir.name, "list_test.db")
        cls.docs_dir = os.path.join(cls._tmpdir.name, "uploaded_documents")
        os.environ["DATABASE_PATH"] = cls.db_path
        os.environ["DOCUMENTS_DIR"] = cls.docs_dir
        os.environ["GEMINI_API_KEY"] = "your_gemini_api_key_here"
        os.environ["USE_MOCK_LLM"] = "true"
        os.environ["JWT_SECRET"] = "test-secret-list"

        import importlib
        import app.config as config
        import app.database as database
        import app.auth as auth
        import app.routers.auth_router as auth_router
        import app.routers.documents_router as documents_router
        import app.main as main

        importlib.reload(config)
        importlib.reload(database)
        database.DATABASE_PATH = cls.db_path
        config.DATABASE_PATH = cls.db_path
        config.DOCUMENTS_DIR = cls.docs_dir
        importlib.reload(auth)
        importlib.reload(auth_router)
        importlib.reload(documents_router)
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
            cur = conn.execute(
                """INSERT INTO users (
                       username, password_hash, full_name, first_name, last_name,
                       email, email_verified, account_status, role, department, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, 0, 'active', 'student', 'CSE', ?)""",
                (
                    "20240000031",
                    hash_password("pass333333"),
                    "Cara Three",
                    "Cara",
                    "Three",
                    "cara@example.com",
                    now_iso(),
                ),
            )
            conn.execute(
                """INSERT INTO student_profiles (
                       user_id, enrollment_number, course, academic_year,
                       current_semester, is_demo, created_at
                   ) VALUES (?, ?, ?, ?, ?, 1, ?)""",
                (cur.lastrowid, "20240000031", "B.Tech CSE", "2024-25", 3, now_iso()),
            )

        cls.client = TestClient(main.app)
        cls.admin = cls.client.post(
            "/auth/admin/login", json={"username": "admin", "password": "admin123"}
        ).json()["access_token"]
        cls.student = cls.client.post(
            "/auth/student/login",
            json={"enrollment_number": "20240000031", "password": "pass333333"},
        ).json()["access_token"]

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls._tmpdir.cleanup()

    def _admin(self):
        return {"Authorization": f"Bearer {self.admin}"}

    def _student(self):
        return {"Authorization": f"Bearer {self.student}"}

    def _upload(self, title, category, text=None):
        body = (text or f"{title} body for listing tests.\n") * 5
        res = self.client.post(
            "/documents/upload",
            headers=self._admin(),
            files={"file": ("notice.txt", body.encode("utf-8"), "text/plain")},
            data={"title": title, "category": category},
        )
        self.assertEqual(res.status_code, 201, res.text)
        return res.json()

    def test_unauthenticated_list_rejected(self):
        self.assertEqual(self.client.get("/documents").status_code, 401)
        self.assertEqual(self.client.get("/documents/categories").status_code, 401)

    def test_pagination_and_category_filter(self):
        fees = [self._upload(f"Fee Notice {i}", "Fees") for i in range(12)]
        hostel = [self._upload(f"Hostel Rule {i}", "Hostel") for i in range(3)]
        hidden = self._upload("Internal Draft", "Policies")
        from app.database import get_conn

        with get_conn() as conn:
            conn.execute(
                "UPDATE documents SET processing_status = ? WHERE id = ?",
                ("embedding_failed", hidden["id"]),
            )
            conn.execute(
                """INSERT INTO documents (
                       filename, title, category, file_type, uploaded_at, processing_status, document_status
                   ) VALUES (?, ?, ?, ?, datetime('now'), 'ready', 'active')""",
                ("blank.txt", "Blank Category Doc", "", "txt"),
            )

        page1 = self.client.get(
            "/documents?page=1&page_size=10", headers=self._admin()
        )
        self.assertEqual(page1.status_code, 200, page1.text)
        body = page1.json()
        self.assertEqual(body["page"], 1)
        self.assertEqual(body["page_size"], 10)
        self.assertGreaterEqual(body["total"], 16)
        self.assertEqual(len(body["items"]), 10)
        self.assertGreaterEqual(body["total_pages"], 2)
        ids1 = {d["id"] for d in body["items"]}

        page2 = self.client.get(
            "/documents?page=2&page_size=10", headers=self._admin()
        ).json()
        ids2 = {d["id"] for d in page2["items"]}
        self.assertTrue(ids1.isdisjoint(ids2))
        self.assertEqual(page2["page"], 2)

        clamped = self.client.get(
            "/documents?page=99&page_size=10", headers=self._admin()
        ).json()
        self.assertEqual(clamped["page"], clamped["total_pages"])
        self.assertTrue(clamped["items"])

        fees_page = self.client.get(
            "/documents?category=Fees&page=1&page_size=10", headers=self._admin()
        ).json()
        self.assertEqual(fees_page["total"], 12)
        self.assertEqual(fees_page["total_pages"], 2)
        self.assertEqual(len(fees_page["items"]), 10)
        self.assertTrue(all(d["category"] == "Fees" for d in fees_page["items"]))
        fee_ids = {d["id"] for d in fees_page["items"]} | {
            d["id"] for d in self.client.get(
                "/documents?category=Fees&page=2&page_size=10", headers=self._admin()
            ).json()["items"]
        }
        self.assertTrue({f["id"] for f in fees}.issubset(fee_ids))

        fees_p2 = self.client.get(
            "/documents?category=Fees&page=2&page_size=10", headers=self._admin()
        ).json()
        self.assertEqual(len(fees_p2["items"]), 2)

        hostel_page = self.client.get(
            "/documents?category=Hostel&page=1&page_size=10", headers=self._admin()
        ).json()
        self.assertEqual(hostel_page["total"], 3)
        self.assertEqual(hostel_page["total_pages"], 1)
        self.assertEqual(len(hostel_page["items"]), 3)
        self.assertEqual({d["id"] for d in hostel_page["items"]}, {h["id"] for h in hostel})

        empty = self.client.get(
            "/documents?category=DoesNotExist&page=1&page_size=10",
            headers=self._admin(),
        ).json()
        self.assertEqual(empty["total"], 0)
        self.assertEqual(empty["page"], 1)
        self.assertEqual(empty["items"], [])

        uncat = self.client.get(
            "/documents?category=__uncategorized__&page=1&page_size=10",
            headers=self._admin(),
        ).json()
        self.assertGreaterEqual(uncat["total"], 1)
        self.assertTrue(all(not (d["category"] or "").strip() for d in uncat["items"]))

        cats = self.client.get("/documents/categories", headers=self._admin()).json()
        self.assertIn("Fees", cats["categories"])
        self.assertIn("Hostel", cats["categories"])
        self.assertTrue(cats["has_uncategorized"])

        student_list = self.client.get(
            "/documents?page=1&page_size=100", headers=self._student()
        ).json()
        student_ids = {d["id"] for d in student_list["items"]}
        self.assertNotIn(hidden["id"], student_ids)
        self.assertIn(hostel[0]["id"], student_ids)

        student_cats = self.client.get(
            "/documents/categories", headers=self._student()
        ).json()
        self.assertIn("Fees", student_cats["categories"])
        self.assertNotIn("Policies", student_cats["categories"])

        bad_page = self.client.get("/documents?page=0", headers=self._admin())
        self.assertEqual(bad_page.status_code, 422)
        bad_size = self.client.get("/documents?page_size=101", headers=self._admin())
        self.assertEqual(bad_size.status_code, 422)

        last_fee = fees[-1]
        self.client.delete(f"/documents/{last_fee['id']}", headers=self._admin())
        after = self.client.get(
            "/documents?category=Fees&page=2&page_size=10", headers=self._admin()
        ).json()
        self.assertEqual(after["total"], 11)
        self.assertEqual(after["total_pages"], 2)
        self.assertEqual(len(after["items"]), 1)


if __name__ == "__main__":
    unittest.main()
