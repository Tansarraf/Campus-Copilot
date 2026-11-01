"""Unit tests for hardened re-embedding (mocked embedder; no Gemini key)."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


def _vec(dim: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=dim).astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-8)


class ReembedInfrastructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls._tmpdir.name, "reembed_test.db")
        os.environ["DATABASE_PATH"] = cls.db_path
        os.environ["GEMINI_API_KEY"] = "your_gemini_api_key_here"
        os.environ["USE_MOCK_LLM"] = "true"
        os.environ["JWT_SECRET"] = "test-secret-not-for-production"

        import importlib
        import app.config as config
        import app.database as database

        importlib.reload(config)
        importlib.reload(database)
        database.DATABASE_PATH = cls.db_path
        config.DATABASE_PATH = cls.db_path

        from app.database import (
            get_conn,
            init_db,
            now_iso,
            embedding_to_blob,
            upsert_embedding_index_meta,
        )
        from app.embeddings import MOCK_DIM, _mock_embedding

        init_db()
        with get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO users (
                       username, password_hash, full_name, role, department, created_at,
                       first_name, last_name, email_verified, account_status
                   ) VALUES ('admin', 'x', 'Admin', 'admin', 'Administration', ?,
                             'A', 'Dmin', 1, 'active')""",
                (now_iso(),),
            )
            admin_id = cur.lastrowid
            cur = conn.execute(
                """INSERT INTO documents (
                       filename, title, category, department, academic_year,
                       file_type, uploaded_by, uploaded_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("fees.md", "Fee Circular", "Fees", None, "2026-27", "md", admin_id, now_iso()),
            )
            cls.doc_id = cur.lastrowid
            cur2 = conn.execute(
                """INSERT INTO documents (
                       filename, title, category, department, academic_year,
                       file_type, uploaded_by, uploaded_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("hostel.md", "Hostel Rules", "Hostel", None, "2026-27", "md", admin_id, now_iso()),
            )
            cls.doc_id_2 = cur2.lastrowid

            texts = [
                (cls.doc_id, 0, "Section A", "Fee payment deadline is 15 August."),
                (cls.doc_id, 1, "Section B", "Late fee is INR 500 per week."),
                (cls.doc_id_2, 0, "Intro", "Hostel gates close at 10 PM."),
            ]
            for document_id, idx, section, text in texts:
                vec = _mock_embedding(text)
                conn.execute(
                    """INSERT INTO chunks (
                           document_id, chunk_index, section_label, page_number,
                           text, embedding, embedding_dim
                       ) VALUES (?, ?, ?, NULL, ?, ?, ?)""",
                    (document_id, idx, section, text, embedding_to_blob(vec), MOCK_DIM),
                )
            upsert_embedding_index_meta(
                conn,
                provider="mock",
                model_name="mock-hash-v1",
                vector_dim=MOCK_DIM,
                mode="mock",
            )

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def _restore_mock_index(self):
        from app.database import get_conn, embedding_to_blob, upsert_embedding_index_meta
        from app.embeddings import MOCK_DIM, _mock_embedding

        with get_conn() as conn:
            rows = conn.execute("SELECT id, text FROM chunks").fetchall()
            for r in rows:
                conn.execute(
                    "UPDATE chunks SET embedding = ?, embedding_dim = ? WHERE id = ?",
                    (embedding_to_blob(_mock_embedding(r["text"])), MOCK_DIM, r["id"]),
                )
            upsert_embedding_index_meta(
                conn,
                provider="mock",
                model_name="mock-hash-v1",
                vector_dim=MOCK_DIM,
                mode="mock",
            )

    def test_dry_run_does_not_change_embeddings(self):
        from app.reembed import open_db, run_reembed, snapshot_chunk_identity

        conn = open_db(self.db_path)
        before = snapshot_chunk_identity(conn)
        conn.close()

        result = run_reembed(
            db_path=self.db_path,
            dry_run=True,
            embed_fn=lambda texts: [_vec(256, i + 1) for i, _ in enumerate(texts)],
            create_backup=False,
            allow_index_replacement=True,
            progress=lambda _m: None,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.chunks_updated, 0)

        conn = open_db(self.db_path)
        after = snapshot_chunk_identity(conn)
        conn.close()
        for b, a in zip(before, after):
            self.assertEqual(b["embedding"], a["embedding"])

    def test_partial_write_rejected(self):
        from app.reembed import run_reembed, open_db, snapshot_chunk_identity

        conn = open_db(self.db_path)
        before = snapshot_chunk_identity(conn)
        conn.close()

        result = run_reembed(
            db_path=self.db_path,
            document_id=self.doc_id,
            dry_run=False,
            progress=lambda _m: None,
        )
        self.assertFalse(result.ok)
        self.assertTrue(any("full-corpus" in e for e in result.errors))
        self.assertEqual(result.chunks_updated, 0)

        conn = open_db(self.db_path)
        after = snapshot_chunk_identity(conn)
        conn.close()
        for b, a in zip(before, after):
            self.assertEqual(b["embedding"], a["embedding"])

    def test_document_id_dry_run_allowed(self):
        from app.reembed import run_reembed

        result = run_reembed(
            db_path=self.db_path,
            document_id=self.doc_id,
            dry_run=True,
            progress=lambda _m: None,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.chunks_validated, 2)
        self.assertEqual(result.chunks_updated, 0)

    def test_missing_document_id_structured_error(self):
        from app.reembed import run_reembed

        result = run_reembed(
            db_path=self.db_path,
            document_id=999999,
            dry_run=True,
            progress=lambda _m: None,
        )
        self.assertFalse(result.ok)
        self.assertTrue(any("does not exist" in e for e in result.errors))
        self.assertEqual(result.chunks_updated, 0)

    def test_mock_cannot_overwrite_real_without_opt_in(self):
        from app.database import get_conn, embedding_to_blob, upsert_embedding_index_meta
        from app.reembed import run_reembed, open_db, snapshot_chunk_identity

        with get_conn() as conn:
            for r in conn.execute("SELECT id FROM chunks").fetchall():
                conn.execute(
                    "UPDATE chunks SET embedding = ?, embedding_dim = ? WHERE id = ?",
                    (embedding_to_blob(_vec(768, r["id"])), 768, r["id"]),
                )
            upsert_embedding_index_meta(
                conn,
                provider="gemini",
                model_name="models/text-embedding-004",
                vector_dim=768,
                mode="real",
            )

        conn = open_db(self.db_path)
        before = snapshot_chunk_identity(conn)
        conn.close()

        denied = run_reembed(
            db_path=self.db_path,
            dry_run=False,
            allow_index_replacement=False,
            create_backup=False,
            progress=lambda _m: None,
        )
        self.assertFalse(denied.ok)
        self.assertTrue(any("allow-index-replacement" in e for e in denied.errors))

        conn = open_db(self.db_path)
        after = snapshot_chunk_identity(conn)
        conn.close()
        for b, a in zip(before, after):
            self.assertEqual(b["embedding"], a["embedding"])
            self.assertEqual(a["embedding_dim"], 768)

        self._restore_mock_index()

    def test_real_cannot_overwrite_mock_without_opt_in(self):
        from app.embedding_validation import EmbeddingIdentity
        from app.reembed import run_reembed

        with patch(
            "app.reembed.configured_embedding_identity",
            return_value=EmbeddingIdentity(
                provider="gemini",
                model_name="models/text-embedding-004",
                mode="real",
            ),
        ):
            denied = run_reembed(
                db_path=self.db_path,
                dry_run=False,
                allow_index_replacement=False,
                create_backup=False,
                embed_fn=lambda texts: [_vec(768, i) for i, _ in enumerate(texts)],
                progress=lambda _m: None,
            )
        self.assertFalse(denied.ok)
        self.assertTrue(any("allow-index-replacement" in e for e in denied.errors))
        self.assertEqual(denied.chunks_updated, 0)

    def test_explicit_index_replacement_and_full_corpus_meta(self):
        from app.database import get_conn, get_embedding_index_meta
        from app.reembed import run_reembed, open_db, snapshot_chunk_identity
        from app.embedding_validation import EmbeddingIdentity

        conn = open_db(self.db_path)
        before_docs = [
            dict(r) for r in conn.execute("SELECT * FROM documents ORDER BY id")
        ]
        before_chunks = snapshot_chunk_identity(conn)
        conn.close()

        with patch(
            "app.reembed.configured_embedding_identity",
            return_value=EmbeddingIdentity(
                provider="gemini",
                model_name="models/text-embedding-004",
                mode="real",
            ),
        ):
            result = run_reembed(
                db_path=self.db_path,
                dry_run=False,
                allow_index_replacement=True,
                create_backup=True,
                embed_fn=lambda texts: [_vec(64, 10 + i) for i, _ in enumerate(texts)],
                progress=lambda _m: None,
            )
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.chunks_updated, 3)
        self.assertIsNotNone(result.backup_path)
        self.assertTrue(Path(result.backup_path).is_file())

        # Backup must be queryable.
        bconn = sqlite3.connect(result.backup_path)
        self.assertEqual(bconn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0], 3)
        bconn.close()

        with get_conn() as conn:
            meta = get_embedding_index_meta(conn)
            after_docs = [
                dict(r) for r in conn.execute("SELECT * FROM documents ORDER BY id")
            ]
            after_chunks = [
                dict(r) for r in conn.execute("SELECT * FROM chunks ORDER BY id")
            ]

        self.assertEqual(meta["provider"], "gemini")
        self.assertEqual(meta["model_name"], "models/text-embedding-004")
        self.assertEqual(meta["mode"], "real")
        self.assertEqual(meta["vector_dim"], 64)
        self.assertEqual([d["id"] for d in before_docs], [d["id"] for d in after_docs])
        for b, a in zip(before_docs, after_docs):
            self.assertEqual(b["filename"], a["filename"])
            self.assertEqual(b["title"], a["title"])
        self.assertEqual(
            [c["id"] for c in before_chunks], [c["id"] for c in after_chunks]
        )
        for b, a in zip(before_chunks, after_chunks):
            self.assertEqual(b["text"], a["text"])
            self.assertEqual(a["embedding_dim"], 64)

        self._restore_mock_index()

    def test_same_mode_reembed_without_opt_in(self):
        from app.reembed import run_reembed
        from app.database import get_embedding_index_meta, get_conn

        result = run_reembed(
            db_path=self.db_path,
            dry_run=False,
            allow_index_replacement=False,
            create_backup=False,
            progress=lambda _m: None,
        )
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(result.chunks_updated, 3)
        with get_conn() as conn:
            meta = get_embedding_index_meta(conn)
        self.assertEqual(meta["mode"], "mock")
        self.assertEqual(meta["provider"], "mock")
        self._restore_mock_index()

    def test_invalid_embeddings_rejected(self):
        from app.reembed import run_reembed, open_db, snapshot_chunk_identity

        conn = open_db(self.db_path)
        before = snapshot_chunk_identity(conn)
        conn.close()

        result = run_reembed(
            db_path=self.db_path,
            dry_run=False,
            embed_fn=lambda texts: [_vec(16, 1)] + [np.array([np.nan, 1.0], dtype=np.float32)]
            + [_vec(16, 3)] * (len(texts) - 2),
            create_backup=False,
            progress=lambda _m: None,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.chunks_updated, 0)
        conn = open_db(self.db_path)
        after = snapshot_chunk_identity(conn)
        conn.close()
        for b, a in zip(before, after):
            self.assertEqual(b["embedding"], a["embedding"])

    def test_provider_failure_no_partial_write(self):
        from app.reembed import run_reembed, open_db, snapshot_chunk_identity

        conn = open_db(self.db_path)
        before = snapshot_chunk_identity(conn)
        conn.close()

        def boom(texts):
            raise RuntimeError("simulated Gemini outage")

        result = run_reembed(
            db_path=self.db_path,
            dry_run=False,
            embed_fn=boom,
            create_backup=False,
            progress=lambda _m: None,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.chunks_updated, 0)
        conn = open_db(self.db_path)
        after = snapshot_chunk_identity(conn)
        conn.close()
        for b, a in zip(before, after):
            self.assertEqual(b["embedding"], a["embedding"])

    def test_transaction_rollback_on_update_failure(self):
        from app.reembed import (
            apply_embedding_updates,
            generate_replacement_embeddings,
            load_chunks_for_reembed,
            open_db,
            snapshot_chunk_identity,
            ChunkRef,
        )

        conn = open_db(self.db_path)
        before = snapshot_chunk_identity(conn)
        chunks = load_chunks_for_reembed(conn)
        prepared = generate_replacement_embeddings(
            chunks, embed_fn=lambda texts: [_vec(48, i) for i, _ in enumerate(texts)]
        )
        bad = [
            (
                ChunkRef(
                    chunk_id=999999,
                    document_id=chunks[0].document_id,
                    text=chunks[0].text,
                    embedding_dim=chunks[0].embedding_dim,
                    embedding_blob=chunks[0].embedding_blob,
                ),
                prepared[0][1],
            )
        ] + prepared[1:]
        conn.execute("BEGIN IMMEDIATE")
        with self.assertRaises(RuntimeError):
            apply_embedding_updates(conn, bad)
        conn.rollback()
        after = snapshot_chunk_identity(conn)
        conn.close()
        for b, a in zip(before, after):
            self.assertEqual(b["embedding"], a["embedding"])

    def test_backup_creation_and_failure_blocks_write(self):
        from app.reembed import create_database_backup, run_reembed, open_db, snapshot_chunk_identity

        conn = open_db(self.db_path)
        before = snapshot_chunk_identity(conn)
        n = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        conn.close()

        backup = create_database_backup(self.db_path)
        self.assertTrue(backup.is_file())
        v = sqlite3.connect(str(backup))
        self.assertEqual(v.execute("SELECT COUNT(*) FROM chunks").fetchone()[0], n)
        v.close()

        with patch("app.reembed.create_database_backup", side_effect=RuntimeError("backup boom")):
            result = run_reembed(
                db_path=self.db_path,
                dry_run=False,
                create_backup=True,
                progress=lambda _m: None,
            )
        self.assertFalse(result.ok)
        self.assertTrue(any("Backup failed" in e for e in result.errors))
        self.assertEqual(result.chunks_updated, 0)

        conn = open_db(self.db_path)
        after = snapshot_chunk_identity(conn)
        conn.close()
        for b, a in zip(before, after):
            self.assertEqual(b["embedding"], a["embedding"])

    def test_empty_corpus_no_misleading_meta(self):
        from app.database import (
            get_conn,
            get_embedding_index_meta,
            embedding_to_blob,
        )
        from app.embeddings import MOCK_DIM, _mock_embedding
        from app.reembed import run_reembed

        with get_conn() as conn:
            saved = [
                dict(r)
                for r in conn.execute(
                    """SELECT document_id, chunk_index, section_label, page_number, text
                       FROM chunks ORDER BY id"""
                ).fetchall()
            ]
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM embedding_index_meta")

        result = run_reembed(
            db_path=self.db_path,
            dry_run=False,
            create_backup=False,
            progress=lambda _m: None,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.chunks_updated, 0)
        with get_conn() as conn:
            self.assertIsNone(get_embedding_index_meta(conn))
            for row in saved:
                vec = _mock_embedding(row["text"])
                conn.execute(
                    """INSERT INTO chunks (
                           document_id, chunk_index, section_label, page_number,
                           text, embedding, embedding_dim
                       ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row["document_id"],
                        row["chunk_index"],
                        row["section_label"],
                        row["page_number"],
                        row["text"],
                        embedding_to_blob(vec),
                        MOCK_DIM,
                    ),
                )
        self._restore_mock_index()

    def test_mixed_dimensions_detected_during_retrieval(self):
        from app.database import get_conn, embedding_to_blob
        from app.embedding_validation import EmbeddingCompatibilityError
        from app.retrieval import similarity_search

        with get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM chunks WHERE document_id = ? LIMIT 1",
                (self.doc_id_2,),
            ).fetchone()
            conn.execute(
                "UPDATE chunks SET embedding = ?, embedding_dim = ? WHERE id = ?",
                (embedding_to_blob(_vec(64, 99)), 64, row["id"]),
            )

        with self.assertRaises(EmbeddingCompatibilityError):
            similarity_search("hostel gates")
        self._restore_mock_index()

    def test_same_dimension_different_model_rejected(self):
        from app.database import get_conn, upsert_embedding_index_meta
        from app.embedding_validation import EmbeddingCompatibilityError
        from app.embeddings import MOCK_DIM
        from app.retrieval import similarity_search

        with get_conn() as conn:
            upsert_embedding_index_meta(
                conn,
                provider="gemini",
                model_name="models/embedding-001",
                vector_dim=MOCK_DIM,
                mode="real",
            )

        with self.assertRaises(EmbeddingCompatibilityError) as ctx:
            similarity_search("fee deadline")
        self.assertIn("does not match the stored index", str(ctx.exception))
        self._restore_mock_index()

    def test_query_dim_mismatch_detected(self):
        from app.embedding_validation import EmbeddingCompatibilityError
        from app.retrieval import similarity_search

        with patch("app.retrieval.embed_text", return_value=_vec(768, 1)):
            with self.assertRaises(EmbeddingCompatibilityError):
                similarity_search("fee deadline")

    def test_ingestion_into_incompatible_index_rejected(self):
        from app.database import get_conn, embedding_to_blob, upsert_embedding_index_meta
        from app.embedding_validation import EmbeddingCompatibilityError
        from app.retrieval import index_document_chunks

        with get_conn() as conn:
            for r in conn.execute("SELECT id FROM chunks").fetchall():
                conn.execute(
                    "UPDATE chunks SET embedding = ?, embedding_dim = ? WHERE id = ?",
                    (embedding_to_blob(_vec(768, r["id"])), 768, r["id"]),
                )
            upsert_embedding_index_meta(
                conn,
                provider="gemini",
                model_name="models/text-embedding-004",
                vector_dim=768,
                mode="real",
            )

        with self.assertRaises(EmbeddingCompatibilityError):
            index_document_chunks(
                self.doc_id,
                [{"chunk_index": 99, "section_label": "x", "page_number": None, "text": "new"}],
            )
        self._restore_mock_index()

    def test_cli_missing_document_nonzero(self):
        import importlib.util

        path = BACKEND_ROOT / "scripts" / "reembed_documents.py"
        spec = importlib.util.spec_from_file_location("reembed_documents_cli", path)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        code = mod.main(["--dry-run", "--db", self.db_path, "--document-id", "999999"])
        self.assertEqual(code, 1)

    def test_ids_and_metadata_preserved_on_success(self):
        from app.reembed import open_db, run_reembed, snapshot_chunk_identity

        conn = open_db(self.db_path)
        before = snapshot_chunk_identity(conn)
        docs_before = [dict(r) for r in conn.execute("SELECT * FROM documents ORDER BY id")]
        conn.close()

        result = run_reembed(
            db_path=self.db_path,
            dry_run=False,
            create_backup=False,
            progress=lambda _m: None,
        )
        self.assertTrue(result.ok, result.errors)

        conn = open_db(self.db_path)
        after = snapshot_chunk_identity(conn)
        docs_after = [dict(r) for r in conn.execute("SELECT * FROM documents ORDER BY id")]
        conn.close()
        self.assertEqual([c["id"] for c in before], [c["id"] for c in after])
        for b, a in zip(before, after):
            self.assertEqual(b["text"], a["text"])
            self.assertEqual(b["section_label"], a["section_label"])
        for b, a in zip(docs_before, docs_after):
            self.assertEqual(b["id"], a["id"])
            self.assertEqual(b["filename"], a["filename"])
            self.assertEqual(b["uploaded_at"], a["uploaded_at"])
        self._restore_mock_index()


if __name__ == "__main__":
    unittest.main()
