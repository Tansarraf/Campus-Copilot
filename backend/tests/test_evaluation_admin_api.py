"""Admin Evaluation Dashboard API tests (auth + real persisted data shape)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


class EvaluationAdminApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls._tmpdir.name, "eval_admin.db")
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

        from app.database import get_conn, init_db, now_iso
        from app.auth import hash_password
        from fastapi.testclient import TestClient
        import app.main as main

        importlib.reload(main)
        init_db()

        with get_conn() as conn:
            conn.execute(
                """INSERT INTO users (
                       username, password_hash, full_name, role, department, created_at,
                       first_name, last_name, email_verified, account_status
                   ) VALUES (?, ?, 'Admin User', 'admin', 'Administration', ?,
                             'A', 'Dmin', 1, 'active')""",
                ("admin", hash_password("admin123"), now_iso()),
            )
            conn.execute(
                """INSERT INTO users (
                       username, password_hash, full_name, role, department, created_at,
                       first_name, last_name, email_verified, account_status
                   ) VALUES (?, ?, 'Stu Dent', 'student', 'CSE', ?,
                             'Stu', 'Dent', 1, 'active')""",
                ("student1", hash_password("StudentPass1"), now_iso()),
            )
            conn.execute(
                """INSERT INTO student_profiles (
                       user_id, enrollment_number, course, academic_year,
                       current_semester, is_demo, created_at
                   ) VALUES (
                       (SELECT id FROM users WHERE username='student1'),
                       '20240000999', 'B.Tech CSE', '2024-25', 3, 1, ?
                   )""",
                (now_iso(),),
            )

            summary = {
                "num_questions": 2,
                "num_evaluated": 2,
                "num_skipped": 0,
                "num_api_failures": 0,
                "k_values": [1, 3, 5],
                "aggregates": {
                    "doc_precision@5": 0.2,
                    "doc_recall@5": 0.5,
                    "doc_hit_rate@5": 0.5,
                    "chunk_precision@5": 0.1,
                    "chunk_recall@5": 0.25,
                    "mrr_doc": 0.4,
                    "mrr_chunk": 0.2,
                    "citation_precision_doc": None,
                    "citation_coverage_doc": None,
                },
                "latency": {
                    "retrieval_p50_ms": 1.5,
                    "retrieval_p95_ms": 3.0,
                    "generation_p50_ms": None,
                    "generation_p95_ms": None,
                    "e2e_p50_ms": 1.5,
                    "e2e_p95_ms": 3.0,
                },
                "answerability": {
                    "answerable_total": 1,
                    "answerable_correct_answer": 0,
                    "answerable_false_abstention": 1,
                    "unanswerable_total": 1,
                    "unanswerable_correct_abstention": 1,
                    "unanswerable_false_answer": 0,
                    "partial_total": 0,
                    "classification_correct": 1,
                    "classification_total": 2,
                    "api_failures": 0,
                    "skipped": 0,
                },
                "unavailable_metrics": [
                    "llm_judge_faithfulness",
                    "genuine_gemini_generation_quality",
                ],
                "notes": [],
            }
            cls.run_id = "eval_test_admin_dashboard_001"
            conn.execute(
                """INSERT INTO evaluation_runs (
                       run_id, created_at, benchmark_pack, benchmark_version,
                       corpus_identity, corpus_fingerprint, document_count, chunk_count,
                       mock_mode, embedding_provider, embedding_model, embedding_dim,
                       generation_provider, generation_model, top_k, confidence_threshold,
                       retrieval_only, summary_json, status
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cls.run_id,
                    now_iso(),
                    "synthetic_v1",
                    "2.0.0",
                    "synthetic_v1",
                    "abc123fingerprint",
                    7,
                    36,
                    1,
                    "mock",
                    "mock-hash-v1",
                    128,
                    "mock",
                    "mock-extractive-template",
                    10,
                    0.45,
                    0,
                    json.dumps(summary),
                    "completed",
                ),
            )
            q1 = {
                "question_id": "fees-tuition-btech-001",
                "question": "What is the B.Tech tuition fee?",
                "category": "Fees",
                "difficulty": "easy",
                "answerability_label": "answerable",
                "expected_answer": "Rs. 1,85,000",
                "expected_document_keys": ["fee_payment_circular"],
                "expected_chunk_keys": ["fee_payment_circular:tuition_structure"],
                "skipped": False,
                "error": None,
                "system_decision": "abstained",
                "confident": False,
                "generated_answer": None,
                "retrieval_latency_ms": 1.2,
                "generation_latency_ms": None,
                "e2e_latency_ms": 1.2,
                "retrieved": [
                    {
                        "rank": 1,
                        "document_key": "hostel_rules_handbook",
                        "chunk_key": "hostel_rules_handbook:general",
                        "filename": "hostel_rules_handbook.docx",
                        "score": 0.2,
                    }
                ],
                "metrics": {
                    "doc_hit_rate@5": 0.0,
                    "doc_recall@5": 0.0,
                    "doc_precision@5": 0.0,
                    "mrr_doc": 0.0,
                },
            }
            q2 = {
                "question_id": "unans-wifi-001",
                "question": "What is the wifi password?",
                "category": "IT Services",
                "difficulty": "easy",
                "answerability_label": "unanswerable",
                "expected_answer": None,
                "expected_document_keys": [],
                "expected_chunk_keys": [],
                "skipped": False,
                "error": None,
                "system_decision": "abstained",
                "confident": False,
                "retrieved": [],
                "metrics": {
                    "doc_hit_rate@5": None,
                    "mrr_doc": None,
                },
                "retrieval_latency_ms": 1.0,
                "e2e_latency_ms": 1.0,
            }
            for q in (q1, q2):
                conn.execute(
                    """INSERT INTO evaluation_question_results (run_id, question_id, result_json)
                       VALUES (?, ?, ?)""",
                    (cls.run_id, q["question_id"], json.dumps(q)),
                )

            # Second run for comparison / history preservation
            cls.run_id_b = "eval_test_admin_dashboard_002"
            summary_b = json.loads(json.dumps(summary))
            summary_b["aggregates"]["doc_recall@5"] = 0.6
            conn.execute(
                """INSERT INTO evaluation_runs (
                       run_id, created_at, benchmark_pack, benchmark_version,
                       corpus_identity, corpus_fingerprint, document_count, chunk_count,
                       mock_mode, embedding_provider, embedding_model, embedding_dim,
                       generation_provider, generation_model, top_k, confidence_threshold,
                       retrieval_only, summary_json, status
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cls.run_id_b,
                    now_iso(),
                    "synthetic_v1",
                    "2.0.0",
                    "synthetic_v1",
                    "abc123fingerprint",
                    7,
                    36,
                    1,
                    "mock",
                    "mock-hash-v1",
                    128,
                    "mock",
                    "mock-extractive-template",
                    10,
                    0.45,
                    0,
                    json.dumps(summary_b),
                    "completed",
                ),
            )

        cls.client = TestClient(main.app)

        admin_login = cls.client.post(
            "/auth/admin/login",
            json={"username": "admin", "password": "admin123"},
        )
        cls.admin_token = admin_login.json()["access_token"]

        student_login = cls.client.post(
            "/auth/student/login",
            json={"enrollment_number": "20240000999", "password": "StudentPass1"},
        )
        cls.student_token = student_login.json()["access_token"]

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def _admin(self):
        return {"Authorization": f"Bearer {self.admin_token}"}

    def _student(self):
        return {"Authorization": f"Bearer {self.student_token}"}

    def test_unauthenticated_rejected(self):
        res = self.client.get("/admin/evaluations/summary")
        self.assertIn(res.status_code, (401, 403))

    def test_student_forbidden(self):
        for path in (
            "/admin/evaluations/summary",
            "/admin/evaluations/runs",
            f"/admin/evaluations/runs/{self.run_id}",
            f"/admin/evaluations/runs/{self.run_id}/questions",
            "/admin/evaluations/experiments",
        ):
            res = self.client.get(path, headers=self._student())
            self.assertEqual(res.status_code, 403, path)

    def test_admin_summary_and_null_metrics(self):
        res = self.client.get("/admin/evaluations/summary", headers=self._admin())
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["has_runs"])
        latest = body["latest"]
        self.assertTrue(latest["meta"]["mock_mode"])
        self.assertEqual(latest["meta"]["mode_label"], "Mock evaluation")
        aq = latest["display_metrics"]["answer_quality"]
        self.assertIsNone(aq["faithfulness"])
        self.assertIsNone(aq["answer_correctness"])
        self.assertIsNone(aq["citation_precision_doc"])
        self.assertIsNone(latest["display_metrics"]["performance"]["generation_p50_ms"])
        # Zero is allowed only when calculated — false abstention rate is 1.0 here
        self.assertEqual(aq["false_abstention_rate"], 1.0)

    def test_history_preserved_and_list(self):
        res = self.client.get("/admin/evaluations/runs", headers=self._admin())
        self.assertEqual(res.status_code, 200)
        ids = {r["run_id"] for r in res.json()["runs"]}
        self.assertIn(self.run_id, ids)
        self.assertIn(self.run_id_b, ids)

    def test_missing_run_404(self):
        res = self.client.get(
            "/admin/evaluations/runs/does-not-exist",
            headers=self._admin(),
        )
        self.assertEqual(res.status_code, 404)

    def test_questions_pagination_and_filter(self):
        res = self.client.get(
            f"/admin/evaluations/runs/{self.run_id}/questions?limit=1&offset=0&answerability=answerable",
            headers=self._admin(),
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(len(body["questions"]), 1)
        self.assertEqual(body["questions"][0]["answerability"], "answerable")

    def test_compare_compatible_mock_runs(self):
        res = self.client.get(
            f"/admin/evaluations/compare?run_a={self.run_id}&run_b={self.run_id_b}",
            headers=self._admin(),
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["compatible_modes"])
        recall = next(c for c in body["comparisons"] if c["metric"] == "doc_recall@5")
        self.assertTrue(recall["comparable"])
        self.assertAlmostEqual(recall["delta"], 0.1, places=4)

    def test_insights_still_admin_only(self):
        ok = self.client.get("/admin/insights", headers=self._admin())
        self.assertEqual(ok.status_code, 200)
        denied = self.client.get("/admin/insights", headers=self._student())
        self.assertEqual(denied.status_code, 403)


if __name__ == "__main__":
    unittest.main()
