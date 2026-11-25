"""Hybrid retrieval: FTS5 keyword index, RRF fusion, mode switches."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


def _unit_vec(seed: int, dim: int = 128) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=dim).astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-8)


class HybridRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls._tmpdir.name, "hybrid.db")
        os.environ["DATABASE_PATH"] = cls.db_path
        os.environ["GEMINI_API_KEY"] = "your_gemini_api_key_here"
        os.environ["USE_MOCK_LLM"] = "true"
        os.environ["JWT_SECRET"] = "test-secret-hybrid"
        os.environ["RETRIEVAL_MODE"] = "hybrid"
        os.environ["CONFIDENCE_THRESHOLD"] = "0.45"
        os.environ["TOP_K"] = "3"

        import importlib
        import app.config as config
        import app.database as database
        import app.embeddings as embeddings
        import app.embedding_validation as embedding_validation
        import app.fts_index as fts_index
        import app.retrieval as retrieval

        importlib.reload(config)
        importlib.reload(database)
        importlib.reload(embeddings)
        importlib.reload(embedding_validation)
        importlib.reload(fts_index)
        importlib.reload(retrieval)

        database.DATABASE_PATH = cls.db_path
        config.DATABASE_PATH = cls.db_path
        from app.database import get_conn, init_db, embedding_to_blob, now_iso, upsert_embedding_index_meta
        from app.embeddings import MOCK_DIM
        from app.embedding_validation import MOCK_MODEL_NAME, MOCK_PROVIDER

        init_db()
        dim = MOCK_DIM
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO documents (
                       filename, title, category, file_type, uploaded_at, processing_status, document_status
                   ) VALUES (?, ?, ?, ?, ?, 'ready', 'active')""",
                ("fee_payment_circular.pdf", "Fee Circular", "Fees", "pdf", now_iso()),
            )
            fee_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                """INSERT INTO documents (
                       filename, title, category, file_type, uploaded_at, processing_status, document_status
                   ) VALUES (?, ?, ?, ?, ?, 'ready', 'active')""",
                ("hostel_rules_handbook.docx", "Hostel Rules", "Hostel", "docx", now_iso()),
            )
            hostel_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Exact keyword-heavy fee chunk vs paraphrased hostel chunk.
            fee_text = (
                "Form FR-2026-01 fee payment circular. Tuition deadline 15 November 2026. "
                "Course CSE-301 late fee INR 500."
            )
            hostel_text = (
                "Hostel weekday gate closing time is 10 PM. Visitors allowed on weekends only."
            )
            for doc_id, text, seed, idx in (
                (fee_id, fee_text, 1, 0),
                (hostel_id, hostel_text, 2, 0),
                (fee_id, "General campus notice without the unique form code.", 3, 1),
            ):
                conn.execute(
                    """INSERT INTO chunks (
                           document_id, chunk_index, section_label, page_number, text, embedding, embedding_dim
                       ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        doc_id,
                        idx,
                        None,
                        1,
                        text,
                        embedding_to_blob(_unit_vec(seed, dim)),
                        dim,
                    ),
                )
            upsert_embedding_index_meta(
                conn,
                provider=MOCK_PROVIDER,
                model_name=MOCK_MODEL_NAME,
                vector_dim=dim,
                mode="mock",
            )
            fts_index.ensure_chunks_fts(conn)

        cls.fee_id = fee_id
        cls.hostel_id = hostel_id
        cls.dim = dim
        cls.retrieval = retrieval
        cls.config = config
        cls.fts_index = fts_index
        cls.database = database

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def test_fts_backfill_and_exact_keyword(self):
        from app.database import get_conn

        with get_conn() as conn:
            n = conn.execute("SELECT COUNT(*) AS n FROM chunks_fts").fetchone()["n"]
            self.assertEqual(n, 3)
            ids = self.fts_index.keyword_search_chunk_ids(conn, "FR-2026-01", limit=5)
        self.assertTrue(ids)
        with get_conn() as conn:
            row = conn.execute("SELECT text FROM chunks WHERE id = ?", (ids[0],)).fetchone()
        self.assertIn("FR-2026-01", row["text"])

    def test_rrf_dedupes_and_preserves_metadata(self):
        a = [
            {
                "chunk_id": 1,
                "document_id": 10,
                "score": 0.9,
                "vector_score": 0.9,
                "keyword_rank": None,
                "title": "A",
                "text": "x",
                "filename": "a.pdf",
                "category": "Fees",
                "department": None,
                "section_label": None,
                "page_number": 1,
                "chunk_index": 0,
                "document_status": "active",
            }
        ]
        b = [
            {
                "chunk_id": 1,
                "document_id": 10,
                "score": 0.5,
                "vector_score": 0.8,
                "keyword_rank": 1,
                "title": "A",
                "text": "x",
                "filename": "a.pdf",
                "category": "Fees",
                "department": None,
                "section_label": None,
                "page_number": 1,
                "chunk_index": 0,
                "document_status": "active",
            },
            {
                "chunk_id": 2,
                "document_id": 11,
                "score": 0.4,
                "vector_score": 0.4,
                "keyword_rank": 2,
                "title": "B",
                "text": "y",
                "filename": "b.pdf",
                "category": "Hostel",
                "department": None,
                "section_label": None,
                "page_number": 2,
                "chunk_index": 0,
                "document_status": "active",
            },
        ]
        fused = self.retrieval.reciprocal_rank_fusion([a, b], rrf_k=60, top_k=5)
        self.assertEqual(len(fused), 2)
        self.assertEqual(fused[0]["chunk_id"], 1)
        self.assertEqual(fused[0]["page_number"], 1)
        self.assertIsNotNone(fused[0]["vector_score"])
        self.assertEqual(fused[0]["keyword_rank"], 1)

    def test_modes_vector_keyword_hybrid(self):
        fee_q = "What is form FR-2026-01 tuition deadline?"
        # Force vector rankings with deterministic fake similarities via embed_text mock
        # pointing query near hostel embedding so keyword should rescue the fee form.
        hostel_like = _unit_vec(2, self.dim)

        def fake_embed(text, task_type="retrieval_document"):
            return hostel_like

        with mock.patch.object(self.retrieval, "embed_text", side_effect=fake_embed):
            vector_hits, _ = self.retrieval.similarity_search(
                fee_q, top_k=2, retrieval_mode="vector"
            )
            keyword_hits, _ = self.retrieval.similarity_search(
                fee_q, top_k=2, retrieval_mode="keyword"
            )
            hybrid_hits, _ = self.retrieval.similarity_search(
                fee_q, top_k=2, retrieval_mode="hybrid"
            )

        self.assertTrue(keyword_hits)
        self.assertIn("FR-2026-01", keyword_hits[0]["text"])
        # Vector alone prefers hostel-like embedding → not the form chunk first.
        self.assertTrue(vector_hits)
        self.assertNotIn("FR-2026-01", vector_hits[0]["text"])
        # Hybrid should surface the keyword form hit near the top.
        hybrid_texts = " ".join(h["text"] for h in hybrid_hits)
        self.assertIn("FR-2026-01", hybrid_texts)

    def test_delete_removes_fts_row(self):
        from app.database import get_conn, embedding_to_blob, now_iso
        from app.document_deletion import permanently_delete_document

        with get_conn() as conn:
            conn.execute(
                """INSERT INTO documents (
                       filename, title, category, file_type, uploaded_at, processing_status, document_status
                   ) VALUES (?, ?, ?, ?, ?, 'ready', 'active')""",
                ("temp_delete.pdf", "Temp", "General", "pdf", now_iso()),
            )
            doc_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                """INSERT INTO chunks (
                       document_id, chunk_index, section_label, page_number, text, embedding, embedding_dim
                   ) VALUES (?, 0, NULL, 1, ?, ?, ?)""",
                (
                    doc_id,
                    "UNIQUE_DELETE_TOKEN_XYZ tuition",
                    embedding_to_blob(_unit_vec(99, self.dim)),
                    self.dim,
                ),
            )
            before = self.fts_index.keyword_search_chunk_ids(
                conn, "UNIQUE_DELETE_TOKEN_XYZ", limit=5
            )
        self.assertTrue(before)
        permanently_delete_document(doc_id)
        with get_conn() as conn:
            after = self.fts_index.keyword_search_chunk_ids(
                conn, "UNIQUE_DELETE_TOKEN_XYZ", limit=5
            )
        self.assertEqual(after, [])

    def test_empty_query_keyword_safe(self):
        from app.database import get_conn

        with get_conn() as conn:
            self.assertEqual(self.fts_index.keyword_search_chunk_ids(conn, "   ", limit=5), [])
            self.assertEqual(self.fts_index.keyword_search_chunk_ids(conn, "???", limit=5), [])


if __name__ == "__main__":
    unittest.main()
