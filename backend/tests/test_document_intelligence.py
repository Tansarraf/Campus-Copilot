"""OCR fallback helpers, metadata persistence, and supersession rules."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


class DocumentIntelligenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls._tmpdir.name, "test_docintel.db")
        os.environ["DATABASE_PATH"] = cls.db_path
        os.environ["GEMINI_API_KEY"] = "your_gemini_api_key_here"
        os.environ["USE_MOCK_LLM"] = "true"
        os.environ["JWT_SECRET"] = "test-secret-docintel"

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
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls._tmpdir.cleanup()

    def _admin_headers(self):
        r = self.client.post("/auth/admin/login", json={"username": "admin", "password": "admin123"})
        self.assertEqual(r.status_code, 200, r.text)
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    def test_document_columns_migrated(self):
        from app.database import get_conn

        with get_conn() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
        for col in (
            "document_type",
            "publication_date",
            "effective_date",
            "expiry_date",
            "extraction_method",
            "processing_status",
            "document_status",
            "supersedes_document_id",
            "updated_at",
        ):
            self.assertIn(col, cols)

    def test_text_pdf_does_not_require_ocr(self):
        from app.ingestion.ocr import text_is_sufficient
        from app.ingestion import loaders

        self.assertTrue(text_is_sufficient("A" * 50))
        self.assertFalse(text_is_sufficient("..."))

        # Ordinary text path: load_text never calls OCR.
        path = os.path.join(self._tmpdir.name, "notice.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# Fee Notice\n\nStudents must pay fees by 15 November 2026.\n")
        with mock.patch("app.ingestion.loaders.ocr_image_path") as ocr_img, mock.patch(
            "app.ingestion.loaders.ocr_pdf_pages"
        ) as ocr_pdf:
            units, meta = loaders.load_document(path)
            ocr_img.assert_not_called()
            ocr_pdf.assert_not_called()
        self.assertTrue(any("fees" in u["text"].lower() for u in units))
        self.assertEqual(meta["extraction_method"], "plain_text")

    def test_image_ocr_unavailable_graceful(self):
        from app.ingestion import loaders

        path = os.path.join(self._tmpdir.name, "blank.png")
        img = Image.new("RGB", (200, 80), color=(255, 255, 255))
        img.save(path)
        with mock.patch("app.ingestion.ocr.configure_tesseract", return_value=False):
            units, meta = loaders.load_document(path)
        self.assertEqual(meta["extraction_method"], "ocr_unavailable")
        self.assertEqual(units[0].get("extraction_method"), "ocr_unavailable")

    def test_upload_txt_persists_metadata(self):
        headers = self._admin_headers()
        path = os.path.join(self._tmpdir.name, "exam_circular.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("Examination circular dated 2026-11-01\nEnd semester exams begin soon.\n")
        with open(path, "rb") as f:
            r = self.client.post(
                "/documents/upload",
                headers=headers,
                files={"file": ("exam_circular.txt", f, "text/plain")},
                data={
                    "title": "Exam Circular",
                    "category": "Examinations",
                    "department": "Exams",
                    "academic_year": "2026-27",
                },
            )
        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        self.assertEqual(body["category"], "Examinations")
        self.assertEqual(body["document_status"], "active")
        self.assertIsNotNone(body["id"])
        self.assertTrue(body["chunk_count"] >= 1)
        self.assertEqual(body["extraction_method"], "plain_text")
        self.assertEqual(body["processing_status"], "ready")

    def test_supersession_rules(self):
        headers = self._admin_headers()
        # Create two docs
        ids = []
        for name in ("old_exam.txt", "new_exam.txt"):
            path = os.path.join(self._tmpdir.name, name)
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"Examination policy text for {name}\n" * 5)
            with open(path, "rb") as f:
                r = self.client.post(
                    "/documents/upload",
                    headers=headers,
                    files={"file": (name, f, "text/plain")},
                    data={"title": name, "category": "Examinations"},
                )
            self.assertEqual(r.status_code, 201, r.text)
            ids.append(r.json()["id"])
        older, newer = ids

        # Self supersession rejected
        bad = self.client.post(
            f"/documents/{newer}/supersede",
            headers=headers,
            json={"supersedes_document_id": newer},
        )
        self.assertEqual(bad.status_code, 400)

        ok = self.client.post(
            f"/documents/{newer}/supersede",
            headers=headers,
            json={"supersedes_document_id": older},
        )
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(ok.json()["supersedes_document_id"], older)

        from app.database import get_conn

        with get_conn() as conn:
            old_row = conn.execute("SELECT document_status FROM documents WHERE id = ?", (older,)).fetchone()
            new_row = conn.execute(
                "SELECT document_status, supersedes_document_id FROM documents WHERE id = ?",
                (newer,),
            ).fetchone()
        self.assertEqual(old_row["document_status"], "superseded")
        self.assertEqual(new_row["document_status"], "active")
        self.assertEqual(new_row["supersedes_document_id"], older)

        # Cycle: older supersedes newer should fail (newer already points at older)
        cycle = self.client.post(
            f"/documents/{older}/supersede",
            headers=headers,
            json={"supersedes_document_id": newer},
        )
        self.assertEqual(cycle.status_code, 400)

    def test_metadata_score_adjustment_penalizes_superseded(self):
        from app.retrieval import _metadata_score_adjustment

        class R(dict):
            def keys(self):
                return super().keys()

        active = R(document_status="active", category="Fees", academic_year="2026-27")
        superseded = R(document_status="superseded", category="Fees", academic_year="2026-27")
        q = "What is the current fee deadline?"
        self.assertGreater(
            _metadata_score_adjustment(q, active),
            _metadata_score_adjustment(q, superseded),
        )
        hist = "Show the previous superseded fee circular"
        # Historical wording removes superseded penalty; category hint may still apply.
        self.assertGreaterEqual(_metadata_score_adjustment(hist, superseded), 0.0)
        self.assertEqual(
            _metadata_score_adjustment(hist, superseded),
            _metadata_score_adjustment(hist, active),
        )


if __name__ == "__main__":
    unittest.main()
