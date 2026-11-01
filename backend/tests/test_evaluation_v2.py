"""Tests for Evaluation Framework v2 (deterministic; no Gemini calls)."""
from __future__ import annotations

import json
import os
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


class MetricsUnitTests(unittest.TestCase):
    def test_precision_recall_hit_mrr_doc_level(self):
        from app.evaluation.metrics import (
            hit_rate_at_k,
            precision_at_k,
            recall_at_k,
            reciprocal_rank,
        )

        retrieved = ["a", "b", "c", "a"]
        gold = {"a", "c"}
        self.assertAlmostEqual(precision_at_k(retrieved, gold, 3), 2 / 3)
        self.assertAlmostEqual(recall_at_k(retrieved, gold, 3), 1.0)
        self.assertAlmostEqual(hit_rate_at_k(retrieved, gold, 1), 1.0)
        self.assertAlmostEqual(hit_rate_at_k(["x", "y"], gold, 2), 0.0)
        self.assertAlmostEqual(reciprocal_rank(["x", "c"], gold), 0.5)

    def test_recall_undefined_without_gold(self):
        from app.evaluation.metrics import hit_rate_at_k, recall_at_k, reciprocal_rank

        self.assertIsNone(recall_at_k(["a"], set(), 1))
        self.assertIsNone(hit_rate_at_k(["a"], set(), 1))
        self.assertIsNone(reciprocal_rank(["a"], set()))

    def test_multiple_relevant_evidence(self):
        from app.evaluation.metrics import precision_at_k, recall_at_k

        retrieved = ["d1:c1", "d2:c2", "other"]
        gold = {"d1:c1", "d2:c2", "d3:c3"}
        self.assertAlmostEqual(precision_at_k(retrieved, gold, 2), 1.0)
        self.assertAlmostEqual(recall_at_k(retrieved, gold, 2), 2 / 3)
        self.assertAlmostEqual(recall_at_k(retrieved, gold, 3), 2 / 3)

    def test_citation_precision_coverage_and_missing(self):
        from app.evaluation.metrics import citation_coverage, citation_precision

        gold = {"fee_payment_circular", "hostel_rules_handbook"}
        cited = {"fee_payment_circular", "receipt"}
        self.assertAlmostEqual(citation_precision(cited, gold), 0.5)
        self.assertAlmostEqual(citation_coverage(cited, gold), 0.5)
        self.assertIsNone(citation_precision(set(), gold))
        self.assertIsNone(citation_coverage(set(), set()))

    def test_answer_contains_expected(self):
        from app.evaluation.metrics import answer_contains_expected

        self.assertTrue(answer_contains_expected("The fee is Rs. 1,85,000 per semester.", "Rs. 1,85,000"))
        self.assertFalse(answer_contains_expected("No idea", "Rs. 1,85,000"))
        self.assertIsNone(answer_contains_expected("anything", None))


class BenchmarkSchemaTests(unittest.TestCase):
    def test_synthetic_pack_loads_and_preserves_legacy_31(self):
        from app.evaluation.benchmark import load_benchmark_pack

        pack = load_benchmark_pack("synthetic_v1")
        self.assertEqual(pack["pack"], "synthetic_v1")
        self.assertEqual(pack["corpus_identity"], "synthetic_v1")
        legacy = [q for q in pack["questions"] if q.get("legacy_query")]
        self.assertEqual(len(legacy), 31)

        legacy_path = BACKEND_ROOT / "scripts" / "benchmark_queries.json"
        with open(legacy_path, encoding="utf-8") as f:
            old = json.load(f)
        old_queries = {item["query"] for item in old}
        preserved = {q["legacy_query"] for q in legacy}
        self.assertEqual(old_queries, preserved)

    def test_university_pack_separated(self):
        from app.evaluation.benchmark import list_packs, pack_dir

        self.assertIn("synthetic_v1", list_packs())
        self.assertNotIn("university_v1", list_packs())  # no benchmark.json yet
        readme = pack_dir("university_v1") / "README.md"
        self.assertTrue(readme.is_file())
        self.assertFalse((pack_dir("university_v1") / "benchmark.json").is_file())

    def test_malformed_benchmark_rejected(self):
        from app.evaluation.benchmark import BenchmarkValidationError, validate_benchmark_pack

        with self.assertRaises(BenchmarkValidationError):
            validate_benchmark_pack({"pack": "x", "version": "1", "corpus_identity": "x", "questions": []})
        bad = {
            "pack": "x",
            "version": "1",
            "corpus_identity": "x",
            "questions": [{
                "question_id": "q1",
                "question": "?",
                "category": "Fees",
                "expected_answer": "yes",
                "expected_document_keys": [],
                "expected_chunk_keys": [],
                "answerability": "answerable",
                "difficulty": "easy",
                "evaluation_notes": "",
            }],
        }
        with self.assertRaises(BenchmarkValidationError):
            validate_benchmark_pack(bad)

    def test_answerability_counts(self):
        from app.evaluation.benchmark import load_benchmark_pack
        from collections import Counter

        pack = load_benchmark_pack("synthetic_v1")
        counts = Counter(q["answerability"] for q in pack["questions"])
        self.assertGreaterEqual(counts["unanswerable"], 10)
        self.assertGreaterEqual(counts["partial"], 2)
        self.assertGreaterEqual(counts["answerable"], 31)


class _EvalTempDbCase(unittest.TestCase):
    """Shared temp DB seeded with synthetic filenames + receipt."""

    @classmethod
    def setUpClass(cls):
        cls._prev_env = {
            k: os.environ.get(k)
            for k in ("DATABASE_PATH", "GEMINI_API_KEY", "USE_MOCK_LLM", "JWT_SECRET")
        }
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls._tmpdir.name, "eval_v2.db")
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
            embedding_to_blob,
            get_conn,
            init_db,
            now_iso,
            upsert_embedding_index_meta,
        )
        from app.embeddings import MOCK_DIM
        from app.evaluation.corpus import SYNTHETIC_V1_DOCUMENT_KEYS

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

            # Seven synthetic docs + receipt
            seed_chunks = {
                "academic_calendar_2026_27.md": [
                    ("Odd Semester 2026", "Classes begin on August 3, 2026. Tuition Fee Structure unrelated."),
                    ("Even Semester 2027", "Classes begin on January 5, 2027."),
                ],
                "fee_payment_circular.pdf": [
                    (None, "Fee Payment Circular Tuition Fee Structure B.Tech Rs. 1,85,000 Payment Deadlines"),
                    (None, "Late Fee Penalty and Refund Policy text"),
                ],
                "hostel_rules_handbook.docx": [
                    ("Hostel Timings", "Gate closes at 10:30 PM. Mess Fees and Services later."),
                    ("Mess Fees and Services", "Mess fees are Rs. 28,000 per semester."),
                ],
                "scholarship_notice.md": [
                    ("Merit Scholarship", "Top 5% receive merit scholarship."),
                ],
                "placement_guidelines.txt": [
                    ("Eligibility Criteria", "CGPA of 6.0 required."),
                ],
                "examination_regulations.pdf": [
                    (None, "Attendance Requirement 75%. Grading Scale O grade. Revaluation Malpractice"),
                ],
                "library_circular.txt": [
                    ("Borrowing Limits", "Undergraduate students may borrow up to 4 books."),
                    ("Fines", "A fine of Rs. 2 per day per book."),
                ],
                "Receipt-2775-3790.pdf": [
                    (None, "Receipt Invoice number ZZZ unpaid coffee"),
                ],
            }
            # Ensure all SYNTHETIC keys present
            for fname in SYNTHETIC_V1_DOCUMENT_KEYS.values():
                assert fname in seed_chunks

            seed = 1
            for filename, chunks in seed_chunks.items():
                cur = conn.execute(
                    """INSERT INTO documents (
                           filename, title, category, department, academic_year,
                           file_type, uploaded_by, uploaded_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        filename,
                        filename,
                        "General",
                        None,
                        "2026-27",
                        filename.rsplit(".", 1)[-1],
                        admin_id,
                        now_iso(),
                    ),
                )
                doc_id = cur.lastrowid
                for idx, (section, text) in enumerate(chunks):
                    emb = _vec(MOCK_DIM, seed)
                    seed += 1
                    conn.execute(
                        """INSERT INTO chunks (
                               document_id, chunk_index, section_label, page_number,
                               text, embedding, embedding_dim
                           ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            doc_id,
                            idx,
                            section,
                            None,
                            text,
                            embedding_to_blob(emb),
                            MOCK_DIM,
                        ),
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
        for k, v in getattr(cls, "_prev_env", {}).items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        import importlib
        import app.config as config
        import app.database as database

        importlib.reload(config)
        importlib.reload(database)


class CorpusAndKeysIntegrationTests(_EvalTempDbCase):
    def test_receipt_excluded_not_deleted(self):
        from app.database import get_conn
        from app.evaluation.corpus import resolve_corpus

        corpus = resolve_corpus("synthetic_v1")
        self.assertEqual(len(corpus.document_ids), 7)
        self.assertIn("Receipt-2775-3790.pdf", corpus.excluded_present)
        self.assertFalse(corpus.is_real_university_corpus)
        with get_conn() as conn:
            row = conn.execute(
                "SELECT id FROM documents WHERE filename = ?",
                ("Receipt-2775-3790.pdf",),
            ).fetchone()
            self.assertIsNotNone(row)
            n = conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"]
            self.assertEqual(n, 8)

    def test_fingerprint_stable(self):
        from app.evaluation.corpus import resolve_corpus

        a = resolve_corpus("synthetic_v1")
        b = resolve_corpus("synthetic_v1")
        self.assertEqual(a.fingerprint, b.fingerprint)
        self.assertEqual(len(a.fingerprint), 64)

    def test_stable_document_and_chunk_keys(self):
        from app.evaluation.keys import resolve_chunk_key, resolve_document_keys

        docs, errors = resolve_document_keys(["fee_payment_circular", "academic_calendar"])
        self.assertEqual(errors, [])
        self.assertIn("fee_payment_circular", docs)

        chunk, err = resolve_chunk_key("fee_payment_circular:tuition_structure")
        self.assertIsNone(err)
        self.assertIsNotNone(chunk)
        self.assertFalse(chunk.needs_reannotation)

        chunk2, err2 = resolve_chunk_key("academic_calendar:odd_semester_2026")
        self.assertIsNone(err2)
        self.assertEqual(chunk2.section_label, "Odd Semester 2026")

    def test_missing_evidence_transparent(self):
        from app.evaluation.keys import resolve_keys_for_question

        report = resolve_keys_for_question(
            ["fee_payment_circular"],
            ["fee_payment_circular:does_not_exist"],
        )
        self.assertTrue(report.errors)
        self.assertIn("needs re-annotation", report.errors[0])

    def test_university_corpus_empty_reserved(self):
        from app.evaluation.corpus import resolve_corpus

        c = resolve_corpus("university_v1")
        self.assertTrue(c.is_real_university_corpus)
        self.assertEqual(c.document_ids, [])
        self.assertEqual(c.chunk_count, 0)


MINI_PACK = {
    "pack": "synthetic_v1",
    "version": "2.0.0-test",
    "corpus_identity": "synthetic_v1",
    "questions": [
        {
            "question_id": "fees-tuition-test-001",
            "question": "What is the B.Tech tuition fee?",
            "category": "Fees",
            "expected_answer": "Rs. 1,85,000",
            "expected_document_keys": ["fee_payment_circular"],
            "expected_chunk_keys": ["fee_payment_circular:tuition_structure"],
            "answerability": "answerable",
            "difficulty": "easy",
            "evaluation_notes": "unit",
        },
        {
            "question_id": "unans-test-001",
            "question": "What is the campus drone policy?",
            "category": "Facilities",
            "expected_answer": None,
            "expected_document_keys": [],
            "expected_chunk_keys": [],
            "answerability": "unanswerable",
            "difficulty": "easy",
            "evaluation_notes": "unit",
        },
    ],
}


class PersistenceAndRunnerTests(_EvalTempDbCase):
    def test_persistence_does_not_overwrite(self):
        from app.database import get_conn
        from app.evaluation.persistence import save_evaluation_run

        meta = {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "benchmark_pack": "synthetic_v1",
            "benchmark_version": "2.0.0",
            "corpus_identity": "synthetic_v1",
            "corpus_fingerprint": "abc",
            "document_count": 7,
            "chunk_count": 1,
            "mock_mode": True,
            "embedding_provider": "mock",
            "embedding_model": "mock-hash",
            "embedding_dim": 128,
            "generation_provider": "mock",
            "generation_model": "mock",
            "top_k": 5,
            "confidence_threshold": 0.3,
            "retrieval_only": True,
        }
        import uuid

        summary = {"aggregates": {}}
        per_q = [{"question_id": "q1", "skipped": False}]
        run_id = f"eval_test_persist_{uuid.uuid4().hex[:10]}"
        paths = save_evaluation_run(
            run_id=run_id,
            meta=meta,
            summary=summary,
            per_question=per_q,
        )
        self.assertTrue(Path(paths["json_path"]).is_file())
        with self.assertRaises(FileExistsError):
            save_evaluation_run(
                run_id=run_id,
                meta=meta,
                summary=summary,
                per_question=per_q,
            )
        with get_conn() as conn:
            n = conn.execute(
                "SELECT COUNT(*) AS n FROM evaluation_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()["n"]
            self.assertEqual(n, 1)

    def test_mock_real_labeling_and_abstention_vs_api_failure(self):
        from app.evaluation.runner import normalize_is_abstention, run_evaluation
        from app.generation import NOT_INDEXED_MESSAGE

        self.assertTrue(normalize_is_abstention(NOT_INDEXED_MESSAGE))
        self.assertFalse(normalize_is_abstention("The fee is Rs. 1,85,000"))

        with patch("app.evaluation.runner.load_benchmark_pack", return_value=MINI_PACK):
            with patch("app.evaluation.runner.similarity_search") as mock_search:
                mock_search.side_effect = RuntimeError("boom")
                result = run_evaluation(
                    benchmark_pack="synthetic_v1",
                    k_values=(1,),
                    retrieval_only=True,
                    persist=False,
                )
        self.assertTrue(result["meta"]["mock_mode"])
        self.assertEqual(result["meta"]["generation_provider"], "mock")
        self.assertGreater(result["summary"]["num_api_failures"], 0)
        decisions = {r.get("system_decision") for r in result["per_question"]}
        self.assertIn("api_failure", decisions)
        self.assertNotIn("abstained", decisions)

    def test_runner_retrieval_only_persists_mock_labeled_result(self):
        from app.database import get_conn
        from app.evaluation.runner import run_evaluation

        with patch("app.evaluation.runner.load_benchmark_pack", return_value=MINI_PACK):
            result = run_evaluation(
                benchmark_pack="synthetic_v1",
                k_values=(1, 3),
                retrieval_only=True,
                persist=True,
                progress=lambda _m: None,
            )
        self.assertTrue(result["meta"]["mock_mode"])
        self.assertIn("genuine_gemini_generation_quality", result["summary"]["unavailable_metrics"])
        self.assertIn("json_path", result["persistence"])
        self.assertTrue(Path(result["persistence"]["json_path"]).is_file())
        with get_conn() as conn:
            row = conn.execute(
                "SELECT mock_mode, corpus_identity FROM evaluation_runs WHERE run_id = ?",
                (result["run_id"],),
            ).fetchone()
            self.assertEqual(row["mock_mode"], 1)
            self.assertEqual(row["corpus_identity"], "synthetic_v1")
        # Answerable question should contribute retrieval metrics; unanswerable should not
        ans = next(r for r in result["per_question"] if r["question_id"] == "fees-tuition-test-001")
        self.assertFalse(ans.get("skipped"))
        self.assertIsNotNone(ans["metrics"]["doc_precision@1"])
        unans = next(r for r in result["per_question"] if r["question_id"] == "unans-test-001")
        self.assertIsNone(unans["metrics"]["doc_precision@1"])


if __name__ == "__main__":
    unittest.main()
