"""Conversation persistence and ownership isolation tests."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


class ConversationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls._tmpdir.name, "conv_test.db")
        os.environ["DATABASE_PATH"] = cls.db_path
        os.environ["GEMINI_API_KEY"] = "your_gemini_api_key_here"
        os.environ["USE_MOCK_LLM"] = "true"
        os.environ["JWT_SECRET"] = "test-secret-not-for-production"

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

    def test_create_list_get_and_search(self):
        created = self.client.post(
            "/conversations",
            headers=self._auth(self.alice),
            json={"title": "Hostel fees"},
        )
        self.assertEqual(created.status_code, 201, created.text)
        cid = created.json()["id"]

        msg = self.client.post(
            f"/conversations/{cid}/messages",
            headers=self._auth(self.alice),
            json={"role": "user", "content": "What is the hostel fee structure?"},
        )
        self.assertEqual(msg.status_code, 201, msg.text)

        listed = self.client.get("/conversations", headers=self._auth(self.alice))
        self.assertEqual(listed.status_code, 200)
        self.assertTrue(any(c["id"] == cid for c in listed.json()))

        search = self.client.get(
            "/conversations?q=hostel",
            headers=self._auth(self.alice),
        )
        self.assertEqual(search.status_code, 200)
        self.assertTrue(any(c["id"] == cid for c in search.json()))

        detail = self.client.get(f"/conversations/{cid}", headers=self._auth(self.alice))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(len(detail.json()["messages"]), 1)
        self.assertIn("hostel fee", detail.json()["title"].lower())

    def test_student_cannot_access_other_conversation(self):
        created = self.client.post(
            "/conversations",
            headers=self._auth(self.alice),
            json={"title": "Private Alice chat"},
        )
        cid = created.json()["id"]

        denied = self.client.get(f"/conversations/{cid}", headers=self._auth(self.bob))
        self.assertEqual(denied.status_code, 404)

        denied_del = self.client.delete(f"/conversations/{cid}", headers=self._auth(self.bob))
        self.assertEqual(denied_del.status_code, 404)

        # Alice still has it
        ok = self.client.get(f"/conversations/{cid}", headers=self._auth(self.alice))
        self.assertEqual(ok.status_code, 200)

    def test_clear_history_only_own(self):
        a = self.client.post("/conversations", headers=self._auth(self.alice), json={"title": "A"}).json()["id"]
        b = self.client.post("/conversations", headers=self._auth(self.bob), json={"title": "B"}).json()["id"]

        cleared = self.client.delete("/conversations", headers=self._auth(self.alice))
        self.assertEqual(cleared.status_code, 204)

        alice_list = self.client.get("/conversations", headers=self._auth(self.alice))
        self.assertEqual(alice_list.json(), [])

        bob_get = self.client.get(f"/conversations/{b}", headers=self._auth(self.bob))
        self.assertEqual(bob_get.status_code, 200)

        # Alice cannot resurrect cleared id
        gone = self.client.get(f"/conversations/{a}", headers=self._auth(self.alice))
        self.assertEqual(gone.status_code, 404)

    def test_unauthenticated_rejected(self):
        self.assertEqual(self.client.get("/conversations").status_code, 401)


if __name__ == "__main__":
    unittest.main()
