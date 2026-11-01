"""Ownership-safe single-conversation deletion and analytics preservation."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


class DeleteConversationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls._tmpdir.name, "delete_conv.db")
        os.environ["DATABASE_PATH"] = cls.db_path
        os.environ["GEMINI_API_KEY"] = "your_gemini_api_key_here"
        os.environ["USE_MOCK_LLM"] = "true"
        os.environ["JWT_SECRET"] = "test-secret-delete-conv"

        import importlib
        import app.config as config
        import app.database as database
        import app.auth as auth
        import app.routers.auth_router as auth_router
        import app.routers.conversations_router as conversations_router
        import app.main as main

        importlib.reload(config)
        importlib.reload(database)
        database.DATABASE_PATH = cls.db_path
        config.DATABASE_PATH = cls.db_path
        importlib.reload(auth)
        importlib.reload(auth_router)
        importlib.reload(conversations_router)
        importlib.reload(main)

        from app.auth import hash_password
        from app.database import get_conn, init_db, now_iso

        init_db()
        with get_conn() as conn:
            for enrollment, name, password in (
                ("20240000011", "Alice One", "pass111111"),
                ("20240000022", "Bob Two", "pass222222"),
            ):
                first, last = name.split(" ", 1)
                cur = conn.execute(
                    """INSERT INTO users (
                           username, password_hash, full_name, first_name, last_name,
                           email, email_verified, account_status, role, department, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, 1, 'active', 'student', 'CSE', ?)""",
                    (
                        enrollment,
                        hash_password(password),
                        name,
                        first,
                        last,
                        f"{first.lower()}@example.com",
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
            # Seed an evaluation run that must survive conversation deletes.
            conn.execute(
                """INSERT INTO evaluation_runs (
                       run_id, created_at, benchmark_pack, benchmark_version,
                       corpus_identity, corpus_fingerprint, document_count, chunk_count,
                       mock_mode, embedding_provider, embedding_model, embedding_dim,
                       generation_provider, generation_model, top_k, confidence_threshold,
                       retrieval_only, summary_json, status
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "eval-preserve-1",
                    now_iso(),
                    "synthetic_v1",
                    "1",
                    "test-corpus",
                    "fp-test",
                    1,
                    1,
                    1,
                    "mock",
                    "mock-hash-v1",
                    128,
                    "mock",
                    "mock-extractive-template",
                    5,
                    0.45,
                    1,
                    "{}",
                    "completed",
                ),
            )
            conn.execute(
                """INSERT INTO evaluation_question_results (
                       run_id, question_id, result_json
                   ) VALUES (?, ?, ?)""",
                ("eval-preserve-1", "q1", '{"status":"answered"}'),
            )

        cls.client = TestClient(main.app)
        cls.alice = cls._login("20240000011", "pass111111")
        cls.bob = cls._login("20240000022", "pass222222")

    @classmethod
    def _login(cls, enrollment, password):
        res = cls.client.post(
            "/auth/student/login",
            json={"enrollment_number": enrollment, "password": password},
        )
        assert res.status_code == 200, res.text
        return res.json()["access_token"]

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls._tmpdir.cleanup()

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def _create_with_messages(self, token, title, messages):
        created = self.client.post(
            "/conversations",
            headers=self._auth(token),
            json={"title": title},
        )
        self.assertEqual(created.status_code, 201, created.text)
        cid = created.json()["id"]
        for content in messages:
            msg = self.client.post(
                f"/conversations/{cid}/messages",
                headers=self._auth(token),
                json={"role": "user", "content": content},
            )
            self.assertEqual(msg.status_code, 201, msg.text)
        return cid

    def test_auth_required_for_deletion(self):
        cid = self._create_with_messages(self.alice, "Needs auth", ["hello"])
        res = self.client.delete(f"/conversations/{cid}")
        self.assertEqual(res.status_code, 401)
        still = self.client.get(f"/conversations/{cid}", headers=self._auth(self.alice))
        self.assertEqual(still.status_code, 200)

    def test_student_deletes_own_conversation_and_messages(self):
        keep = self._create_with_messages(self.alice, "Keep me", ["keep question"])
        delete_id = self._create_with_messages(
            self.alice, "Delete me", ["delete question one", "delete question two"]
        )

        # Attach a query_log row referenced by a message — must survive deletion.
        from app.database import get_conn, now_iso

        with get_conn() as conn:
            user = conn.execute(
                "SELECT id FROM users WHERE username = ?", ("20240000011",)
            ).fetchone()
            cur = conn.execute(
                """INSERT INTO query_logs
                   (user_id, query_text, answer_text, top_similarity, retrieved_chunk_ids,
                    latency_ms, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user["id"], "analytics query", "answer", 0.9, "[]", 10.0, now_iso()),
            )
            qid = cur.lastrowid
            conn.execute(
                """UPDATE conversation_messages SET query_log_id = ?
                   WHERE conversation_id = ? AND role = 'user'""",
                (qid, delete_id),
            )

        deleted = self.client.delete(
            f"/conversations/{delete_id}", headers=self._auth(self.alice)
        )
        self.assertEqual(deleted.status_code, 204)

        gone = self.client.get(
            f"/conversations/{delete_id}", headers=self._auth(self.alice)
        )
        self.assertEqual(gone.status_code, 404)

        kept = self.client.get(f"/conversations/{keep}", headers=self._auth(self.alice))
        self.assertEqual(kept.status_code, 200)
        self.assertEqual(len(kept.json()["messages"]), 1)

        with get_conn() as conn:
            msgs = conn.execute(
                "SELECT COUNT(*) AS n FROM conversation_messages WHERE conversation_id = ?",
                (delete_id,),
            ).fetchone()["n"]
            conv = conn.execute(
                "SELECT COUNT(*) AS n FROM conversations WHERE id = ?",
                (delete_id,),
            ).fetchone()["n"]
            logs = conn.execute(
                "SELECT COUNT(*) AS n FROM query_logs WHERE id = ?", (qid,)
            ).fetchone()["n"]
            runs = conn.execute(
                "SELECT COUNT(*) AS n FROM evaluation_runs WHERE run_id = ?",
                ("eval-preserve-1",),
            ).fetchone()["n"]
            qrows = conn.execute(
                "SELECT COUNT(*) AS n FROM evaluation_question_results WHERE run_id = ?",
                ("eval-preserve-1",),
            ).fetchone()["n"]
        self.assertEqual(msgs, 0)
        self.assertEqual(conv, 0)
        self.assertEqual(logs, 1)
        self.assertEqual(runs, 1)
        self.assertEqual(qrows, 1)

    def test_cannot_delete_other_students_conversation(self):
        bob_id = self._create_with_messages(self.bob, "Bob private", ["bob secret"])
        alice_try = self.client.delete(
            f"/conversations/{bob_id}", headers=self._auth(self.alice)
        )
        self.assertEqual(alice_try.status_code, 404)

        # Cannot bypass ownership via forged query parameters.
        bypass = self.client.delete(
            f"/conversations/{bob_id}?user_id=1&owner_id=1",
            headers=self._auth(self.alice),
        )
        self.assertEqual(bypass.status_code, 404)

        still = self.client.get(f"/conversations/{bob_id}", headers=self._auth(self.bob))
        self.assertEqual(still.status_code, 200)
        self.assertEqual(len(still.json()["messages"]), 1)

        from app.database import get_conn

        with get_conn() as conn:
            n = conn.execute(
                "SELECT COUNT(*) AS n FROM conversation_messages WHERE conversation_id = ?",
                (bob_id,),
            ).fetchone()["n"]
        self.assertEqual(n, 1)

    def test_nonexistent_conversation_delete(self):
        res = self.client.delete("/conversations/999999", headers=self._auth(self.alice))
        self.assertEqual(res.status_code, 404)


if __name__ == "__main__":
    unittest.main()
