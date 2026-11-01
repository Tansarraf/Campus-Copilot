"""Permanent document deletion: auth, SQLite cleanup, file removal, RAG, supersession."""
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


class DocumentDeletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls._tmpdir.name, "delete_test.db")
        cls.docs_dir = os.path.join(cls._tmpdir.name, "uploaded_documents")
        os.environ["DATABASE_PATH"] = cls.db_path
        os.environ["DOCUMENTS_DIR"] = cls.docs_dir
        os.environ["GEMINI_API_KEY"] = "your_gemini_api_key_here"
        os.environ["USE_MOCK_LLM"] = "true"
        os.environ["JWT_SECRET"] = "test-secret-delete"

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
                    "20240000021",
                    hash_password("pass222222"),
                    "Bob Two",
                    "Bob",
                    "Two",
                    "bob@example.com",
                    now_iso(),
                ),
            )
            conn.execute(
                """INSERT INTO student_profiles (
                       user_id, enrollment_number, course, academic_year,
                       current_semester, is_demo, created_at
                   ) VALUES (?, ?, ?, ?, ?, 1, ?)""",
                (cur.lastrowid, "20240000021", "B.Tech CSE", "2024-25", 3, now_iso()),
            )
            conn.execute(
                """INSERT INTO evaluation_runs (
                       run_id, created_at, benchmark_pack, benchmark_version,
                       corpus_identity, corpus_fingerprint, document_count, chunk_count,
                       mock_mode, top_k, retrieval_only, summary_json, status
                   ) VALUES (?, ?, ?, ?, ?, ?, 1, 2, 1, 4, 0, ?, ?)""",
                (
                    "eval-keep-me",
                    now_iso(),
                    "synthetic_v1",
                    "1",
                    "test",
                    "fp",
                    '{"ok": true}',
                    "completed",
                ),
            )

        cls.client = TestClient(main.app)
        cls.admin = cls.client.post(
            "/auth/admin/login", json={"username": "admin", "password": "admin123"}
        ).json()["access_token"]
        cls.student = cls.client.post(
            "/auth/student/login",
            json={"enrollment_number": "20240000021", "password": "pass222222"},
        ).json()["access_token"]

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls._tmpdir.cleanup()

    def _admin(self):
        return {"Authorization": f"Bearer {self.admin}"}

    def _student(self):
        return {"Authorization": f"Bearer {self.student}"}

    def _upload(self, title: str, text: str, category: str = "Fees"):
        files = {"file": (f"{title}.txt", text.encode("utf-8"), "text/plain")}
        res = self.client.post(
            "/documents/upload",
            headers=self._admin(),
            files=files,
            data={"title": title, "category": category},
        )
        self.assertEqual(res.status_code, 201, res.text)
        return res.json()

    def test_admin_permanent_delete_removes_db_chunks_file_and_rag(self):
        unique = "ZEBRA_QUOKKA_PERMANENT_DELETE_MARKER_9911"
        created = self._upload(
            "Delete Target Unique",
            f"{unique} fee rules apply only to this circular.\n" * 6,
        )
        keep = self._upload(
            "Keep Sibling Doc",
            "LIBRARY_HOURS_UNRELATED_CONTENT opens until midnight.\n" * 6,
            category="Library",
        )
        doc_id = created["id"]

        from app.database import get_conn
        from app.retrieval import similarity_search

        with get_conn() as conn:
            storage = conn.execute(
                "SELECT storage_path FROM documents WHERE id = ?", (doc_id,)
            ).fetchone()["storage_path"]
            chunks_before = conn.execute(
                "SELECT COUNT(*) AS n FROM chunks WHERE document_id = ?",
                (doc_id,),
            ).fetchone()["n"]
        self.assertTrue(storage)
        stored = Path(self.docs_dir) / storage
        self.assertTrue(stored.is_file())
        self.assertGreaterEqual(chunks_before, 1)

        hits, _ = similarity_search(unique, top_k=3)
        self.assertTrue(any(h["document_id"] == doc_id for h in hits))

        deleted = self.client.delete(f"/documents/{doc_id}", headers=self._admin())
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json()["status"], "deleted")

        with get_conn() as conn:
            self.assertIsNone(
                conn.execute(
                    "SELECT id FROM documents WHERE id = ?", (doc_id,)
                ).fetchone()
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM chunks WHERE document_id = ?",
                    (doc_id,),
                ).fetchone()["n"],
                0,
            )
            self.assertIsNotNone(
                conn.execute(
                    "SELECT id FROM documents WHERE id = ?", (keep["id"],)
                ).fetchone()
            )
            self.assertGreaterEqual(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM chunks WHERE document_id = ?",
                    (keep["id"],),
                ).fetchone()["n"],
                1,
            )
            self.assertIsNotNone(
                conn.execute(
                    "SELECT run_id FROM evaluation_runs WHERE run_id = ?",
                    ("eval-keep-me",),
                ).fetchone()
            )
        self.assertFalse(stored.exists())

        listed_admin = self.client.get("/documents", headers=self._admin()).json()
        self.assertFalse(any(d["id"] == doc_id for d in listed_admin))
        listed_student = self.client.get("/documents", headers=self._student()).json()
        self.assertFalse(any(d["id"] == doc_id for d in listed_student))

        file_gone = self.client.get(
            f"/documents/{doc_id}/file", headers=self._admin()
        )
        self.assertEqual(file_gone.status_code, 404)

        hits_after, _ = similarity_search(unique, top_k=5)
        self.assertFalse(any(h["document_id"] == doc_id for h in hits_after))
        keep_hits, _ = similarity_search("LIBRARY_HOURS_UNRELATED_CONTENT", top_k=3)
        self.assertTrue(any(h["document_id"] == keep["id"] for h in keep_hits))

        # Duplicate delete → not found
        again = self.client.delete(f"/documents/{doc_id}", headers=self._admin())
        self.assertEqual(again.status_code, 404)

    def test_student_and_unauthenticated_cannot_delete(self):
        created = self._upload(
            "Protected Doc",
            "Student must not delete this notice text.\n" * 5,
        )
        denied = self.client.delete(
            f"/documents/{created['id']}", headers=self._student()
        )
        self.assertIn(denied.status_code, (401, 403))
        unauth = self.client.delete(f"/documents/{created['id']}")
        self.assertEqual(unauth.status_code, 401)
        still = self.client.get("/documents", headers=self._admin()).json()
        self.assertTrue(any(d["id"] == created["id"] for d in still))

    def test_missing_document_returns_404(self):
        res = self.client.delete("/documents/999999", headers=self._admin())
        self.assertEqual(res.status_code, 404)

    def test_supersession_refs_cleared_without_deleting_siblings(self):
        older = self._upload(
            "Older Policy",
            "Older exam policy text for supersession.\n" * 5,
            category="Examinations",
        )
        newer = self._upload(
            "Newer Policy",
            "Newer exam policy text for supersession.\n" * 5,
            category="Examinations",
        )
        link = self.client.post(
            f"/documents/{newer['id']}/supersede",
            headers=self._admin(),
            json={"supersedes_document_id": older["id"]},
        )
        self.assertEqual(link.status_code, 200, link.text)

        # Delete the newer document: older must remain; no dangling supersedes pointer.
        gone = self.client.delete(
            f"/documents/{newer['id']}", headers=self._admin()
        )
        self.assertEqual(gone.status_code, 200, gone.text)

        from app.database import get_conn

        with get_conn() as conn:
            older_row = conn.execute(
                "SELECT id, supersedes_document_id, document_status FROM documents WHERE id = ?",
                (older["id"],),
            ).fetchone()
            self.assertIsNotNone(older_row)
            # Older may still be marked superseded historically; ensure it exists.
            pointing = conn.execute(
                "SELECT COUNT(*) AS n FROM documents WHERE supersedes_document_id = ?",
                (newer["id"],),
            ).fetchone()["n"]
            self.assertEqual(pointing, 0)

        # Rebuild: B supersedes A, delete A → B.supersedes_document_id cleared
        a = self._upload("Chain A", "Chain A unique text content.\n" * 5)
        b = self._upload("Chain B", "Chain B unique text content.\n" * 5)
        self.client.post(
            f"/documents/{b['id']}/supersede",
            headers=self._admin(),
            json={"supersedes_document_id": a["id"]},
        )
        self.assertEqual(
            self.client.delete(f"/documents/{a['id']}", headers=self._admin()).status_code,
            200,
        )
        with get_conn() as conn:
            b_row = conn.execute(
                "SELECT supersedes_document_id FROM documents WHERE id = ?",
                (b["id"],),
            ).fetchone()
            self.assertIsNotNone(b_row)
            self.assertIsNone(b_row["supersedes_document_id"])

    def test_file_cleanup_failure_keeps_document(self):
        created = self._upload(
            "File Fail Doc",
            "File cleanup failure should keep the database row.\n" * 5,
        )
        doc_id = created["id"]
        with mock.patch(
            "app.document_deletion.Path.unlink",
            side_effect=OSError("simulated lock"),
        ):
            # Patch instance unlink via Path.unlink used inside _unlink_original
            with mock.patch(
                "app.document_deletion._unlink_original",
                side_effect=__import__(
                    "app.document_deletion", fromlist=["DocumentFileCleanupError"]
                ).DocumentFileCleanupError("simulated lock"),
            ):
                res = self.client.delete(
                    f"/documents/{doc_id}", headers=self._admin()
                )
        self.assertEqual(res.status_code, 500, res.text)
        listed = self.client.get("/documents", headers=self._admin()).json()
        self.assertTrue(any(d["id"] == doc_id for d in listed))


if __name__ == "__main__":
    unittest.main()
