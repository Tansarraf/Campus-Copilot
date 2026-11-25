"""Document upload, persistence, and authenticated original-file serving."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


def _doc_items(payload):
    if isinstance(payload, list):
        return payload
    return list((payload or {}).get("items") or [])


class DocumentUploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls._tmpdir.name, "upload_test.db")
        cls.docs_dir = os.path.join(cls._tmpdir.name, "uploaded_documents")
        os.environ["DATABASE_PATH"] = cls.db_path
        os.environ["DOCUMENTS_DIR"] = cls.docs_dir
        os.environ["GEMINI_API_KEY"] = "your_gemini_api_key_here"
        os.environ["USE_MOCK_LLM"] = "true"
        os.environ["JWT_SECRET"] = "test-secret-upload"

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
                    "20240000011",
                    hash_password("pass111111"),
                    "Alice One",
                    "Alice",
                    "One",
                    "alice@example.com",
                    now_iso(),
                ),
            )
            conn.execute(
                """INSERT INTO student_profiles (
                       user_id, enrollment_number, course, academic_year,
                       current_semester, is_demo, created_at
                   ) VALUES (?, ?, ?, ?, ?, 1, ?)""",
                (cur.lastrowid, "20240000011", "B.Tech CSE", "2024-25", 3, now_iso()),
            )

        cls.client = TestClient(main.app)
        cls.admin = cls.client.post(
            "/auth/admin/login", json={"username": "admin", "password": "admin123"}
        ).json()["access_token"]
        cls.student = cls.client.post(
            "/auth/student/login",
            json={"enrollment_number": "20240000011", "password": "pass111111"},
        ).json()["access_token"]

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls._tmpdir.cleanup()

    def _admin(self):
        return {"Authorization": f"Bearer {self.admin}"}

    def _student(self):
        return {"Authorization": f"Bearer {self.student}"}

    def _txt_bytes(self, text="Fee payment deadline is 15 November 2026.\n" * 5):
        return ("notice.txt", text.encode("utf-8"), "text/plain")

    def test_successful_upload_persists_file_chunks_and_list(self):
        files = {"file": self._txt_bytes()}
        data = {
            "title": "Fee Notice",
            "category": "Fees",
            "department": "Accounts",
            "academic_year": "2026-27",
        }
        res = self.client.post(
            "/documents/upload", headers=self._admin(), files=files, data=data
        )
        self.assertEqual(res.status_code, 201, res.text)
        body = res.json()
        self.assertEqual(body["title"], "Fee Notice")
        self.assertGreaterEqual(body["chunk_count"], 1)
        self.assertEqual(body["processing_status"], "ready")
        self.assertTrue(body["has_original_file"])

        from app.database import get_conn

        with get_conn() as conn:
            row = conn.execute(
                "SELECT storage_path FROM documents WHERE id = ?", (body["id"],)
            ).fetchone()
            chunks = conn.execute(
                "SELECT COUNT(*) AS n FROM chunks WHERE document_id = ?",
                (body["id"],),
            ).fetchone()["n"]
        self.assertTrue(row["storage_path"])
        stored = Path(self.docs_dir) / row["storage_path"]
        self.assertTrue(stored.is_file())
        self.assertGreaterEqual(chunks, 1)

        listed = self.client.get("/documents", headers=self._student())
        self.assertEqual(listed.status_code, 200)
        self.assertTrue(any(d["id"] == body["id"] for d in _doc_items(listed.json())))

        file_res = self.client.get(
            f"/documents/{body['id']}/file", headers=self._student()
        )
        self.assertEqual(file_res.status_code, 200)
        self.assertIn("text/plain", file_res.headers.get("content-type", ""))
        self.assertIn(b"Fee payment", file_res.content)

        admin_file = self.client.get(
            f"/documents/{body['id']}/file?disposition=attachment",
            headers=self._admin(),
        )
        self.assertEqual(admin_file.status_code, 200)

    def test_missing_file_and_metadata_validation(self):
        bad = self.client.post(
            "/documents/upload",
            headers=self._admin(),
            data={"title": "No File", "category": "Fees"},
        )
        self.assertEqual(bad.status_code, 422)

        files = {"file": self._txt_bytes()}
        no_title = self.client.post(
            "/documents/upload",
            headers=self._admin(),
            files=files,
            data={"title": "  ", "category": "Fees"},
        )
        self.assertEqual(no_title.status_code, 400)

    def test_unauthenticated_file_access_rejected(self):
        files = {"file": self._txt_bytes("Library hours extend to 10pm.\n" * 4)}
        created = self.client.post(
            "/documents/upload",
            headers=self._admin(),
            files=files,
            data={"title": "Library", "category": "Library"},
        ).json()
        denied = self.client.get(f"/documents/{created['id']}/file")
        self.assertEqual(denied.status_code, 401)

    def test_invalid_document_id_and_path_traversal_blocked(self):
        missing = self.client.get("/documents/999999/file", headers=self._admin())
        self.assertEqual(missing.status_code, 404)

        from app.document_storage import resolve_stored_file

        self.assertIsNone(resolve_stored_file("../secrets.txt"))
        self.assertIsNone(resolve_stored_file("/etc/passwd"))

    def test_embedding_failure_surfaces_error(self):
        files = {"file": self._txt_bytes("Placement drive on campus next week.\n" * 4)}
        with mock.patch(
            "app.routers.documents_router.index_document_chunks",
            side_effect=RuntimeError("embed boom"),
        ):
            res = self.client.post(
                "/documents/upload",
                headers=self._admin(),
                files=files,
                data={"title": "Placement", "category": "Placements"},
            )
        self.assertEqual(res.status_code, 503, res.text)
        self.assertIn("embed", res.json()["detail"].lower())

    def test_extraction_failure_does_not_claim_success(self):
        files = {"file": ("empty.txt", b"   \n\n", "text/plain")}
        res = self.client.post(
            "/documents/upload",
            headers=self._admin(),
            files=files,
            data={"title": "Empty", "category": "General Notices"},
        )
        self.assertEqual(res.status_code, 422, res.text)

    def test_student_cannot_upload(self):
        files = {"file": self._txt_bytes()}
        res = self.client.post(
            "/documents/upload",
            headers=self._student(),
            files=files,
            data={"title": "Nope", "category": "Fees"},
        )
        self.assertIn(res.status_code, (401, 403))

    def test_student_cannot_access_restricted_document(self):
        files = {"file": self._txt_bytes("Internal draft policy text.\n" * 4)}
        created = self.client.post(
            "/documents/upload",
            headers=self._admin(),
            files=files,
            data={"title": "Internal Draft", "category": "Policies"},
        ).json()
        from app.database import get_conn

        with get_conn() as conn:
            conn.execute(
                "UPDATE documents SET processing_status = ? WHERE id = ?",
                ("embedding_failed", created["id"]),
            )
        denied = self.client.get(
            f"/documents/{created['id']}/file", headers=self._student()
        )
        self.assertEqual(denied.status_code, 403)
        listed = _doc_items(self.client.get("/documents", headers=self._student()).json())
        self.assertFalse(any(d["id"] == created["id"] for d in listed))
        admin_ok = self.client.get(
            f"/documents/{created['id']}/file", headers=self._admin()
        )
        self.assertEqual(admin_ok.status_code, 200)

    def test_supersession_still_works_after_upload_changes(self):
        a = self.client.post(
            "/documents/upload",
            headers=self._admin(),
            files={"file": self._txt_bytes("Old exam circular text.\n" * 4)},
            data={"title": "Old Exam", "category": "Examinations"},
        ).json()["id"]
        b = self.client.post(
            "/documents/upload",
            headers=self._admin(),
            files={"file": self._txt_bytes("New exam circular text.\n" * 4)},
            data={"title": "New Exam", "category": "Examinations"},
        ).json()["id"]
        ok = self.client.post(
            f"/documents/{b}/supersede",
            headers=self._admin(),
            json={"supersedes_document_id": a},
        )
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(ok.json()["supersedes_document_id"], a)


if __name__ == "__main__":
    unittest.main()
