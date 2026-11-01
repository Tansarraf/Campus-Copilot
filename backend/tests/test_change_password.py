"""Authenticated password-change endpoint tests (isolated temp database)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


class ChangePasswordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls._tmpdir.name, "test_change_password.db")
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

        from app.auth import hash_password
        from app.database import get_conn, init_db, now_iso
        from app.main import app

        init_db()
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO users (
                       username, password_hash, full_name, first_name, last_name,
                       email, email_verified, account_status, role, department, created_at
                   ) VALUES (?, ?, ?, ?, ?, NULL, 0, 'active', 'admin', 'Administration', ?)""",
                ("admin", hash_password("admin123"), "Campus Admin", "Campus", "Admin", now_iso()),
            )
            cur_a = conn.execute(
                """INSERT INTO users (
                       username, password_hash, full_name, first_name, last_name,
                       email, email_verified, account_status, role, department, created_at
                   ) VALUES (?, ?, ?, ?, ?, NULL, 0, 'active', 'student', ?, ?)""",
                (
                    "20240000001",
                    hash_password("StudentPass1"),
                    "Ada Lovelace",
                    "Ada",
                    "Lovelace",
                    "B.Tech Computer Science",
                    now_iso(),
                ),
            )
            conn.execute(
                """INSERT INTO student_profiles (
                       user_id, enrollment_number, course, academic_year,
                       current_semester, is_demo, created_at
                   ) VALUES (?, ?, ?, ?, ?, 1, ?)""",
                (cur_a.lastrowid, "20240000001", "B.Tech Computer Science", "2024-25", 3, now_iso()),
            )
            cur_b = conn.execute(
                """INSERT INTO users (
                       username, password_hash, full_name, first_name, last_name,
                       email, email_verified, account_status, role, department, created_at
                   ) VALUES (?, ?, ?, ?, ?, NULL, 0, 'active', 'student', ?, ?)""",
                (
                    "20240000002",
                    hash_password("OtherPass2"),
                    "Grace Hopper",
                    "Grace",
                    "Hopper",
                    "B.Tech CSE",
                    now_iso(),
                ),
            )
            conn.execute(
                """INSERT INTO student_profiles (
                       user_id, enrollment_number, course, academic_year,
                       current_semester, is_demo, created_at
                   ) VALUES (?, ?, ?, ?, ?, 1, ?)""",
                (cur_b.lastrowid, "20240000002", "B.Tech CSE", "2024-25", 2, now_iso()),
            )

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def _login_admin(self, password="admin123"):
        return self.client.post(
            "/auth/admin/login",
            json={"username": "admin", "password": password},
        )

    def _login_student(self, enrollment, password):
        return self.client.post(
            "/auth/student/login",
            json={"enrollment_number": enrollment, "password": password},
        )

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_unauthenticated_is_401(self):
        res = self.client.post(
            "/auth/change-password",
            json={
                "current_password": "StudentPass1",
                "new_password": "NewPass99",
                "confirm_password": "NewPass99",
            },
        )
        self.assertEqual(res.status_code, 401)

    def test_incorrect_current_password(self):
        token = self._login_student("20240000002", "OtherPass2").json()["access_token"]
        res = self.client.post(
            "/auth/change-password",
            headers=self._auth(token),
            json={
                "current_password": "WrongPass1",
                "new_password": "NewPass99",
                "confirm_password": "NewPass99",
            },
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Incorrect current password", res.json()["detail"])
        still = self._login_student("20240000002", "OtherPass2")
        self.assertEqual(still.status_code, 200)

    def test_mismatched_confirmation(self):
        token = self._login_student("20240000002", "OtherPass2").json()["access_token"]
        res = self.client.post(
            "/auth/change-password",
            headers=self._auth(token),
            json={
                "current_password": "OtherPass2",
                "new_password": "NewPass99",
                "confirm_password": "NewPass98",
            },
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("do not match", res.json()["detail"])

    def test_weak_password_rejected(self):
        token = self._login_student("20240000002", "OtherPass2").json()["access_token"]
        res = self.client.post(
            "/auth/change-password",
            headers=self._auth(token),
            json={
                "current_password": "OtherPass2",
                "new_password": "short",
                "confirm_password": "short",
            },
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("at least 8", res.json()["detail"])

        res2 = self.client.post(
            "/auth/change-password",
            headers=self._auth(token),
            json={
                "current_password": "OtherPass2",
                "new_password": "noumbers",
                "confirm_password": "noumbers",
            },
        )
        self.assertEqual(res2.status_code, 400)
        self.assertIn("letter and one number", res2.json()["detail"])

    def test_same_as_current_rejected(self):
        token = self._login_student("20240000002", "OtherPass2").json()["access_token"]
        res = self.client.post(
            "/auth/change-password",
            headers=self._auth(token),
            json={
                "current_password": "OtherPass2",
                "new_password": "OtherPass2",
                "confirm_password": "OtherPass2",
            },
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("differ from current password", res.json()["detail"])

    def test_legacy_alias_rejects_mismatch_without_mutating(self):
        token = self._login_student("20240000002", "OtherPass2").json()["access_token"]
        res = self.client.post(
            "/auth/password/change",
            headers=self._auth(token),
            json={
                "current_password": "OtherPass2",
                "new_password": "GraceNew3",
                "confirm_password": "GraceNew4",
            },
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(self._login_student("20240000002", "OtherPass2").status_code, 200)

    def test_success_old_password_fails_and_other_users_unaffected(self):
        student_token = self._login_student("20240000001", "StudentPass1").json()["access_token"]
        res = self.client.post(
            "/auth/change-password",
            headers=self._auth(student_token),
            json={
                "current_password": "StudentPass1",
                "new_password": "AdaNewPass1",
                "confirm_password": "AdaNewPass1",
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["message"], "Password changed successfully.")
        self.assertNotIn("password_hash", res.json())
        self.assertEqual(self._login_student("20240000001", "StudentPass1").status_code, 401)
        new_login = self._login_student("20240000001", "AdaNewPass1")
        self.assertEqual(new_login.status_code, 200)
        student_insights = self.client.get(
            "/admin/insights",
            headers=self._auth(new_login.json()["access_token"]),
        )
        self.assertEqual(student_insights.status_code, 403)

        other = self._login_student("20240000002", "OtherPass2")
        self.assertEqual(other.status_code, 200)

        admin_token = self._login_admin("admin123").json()["access_token"]
        alias = self.client.post(
            "/auth/password/change",
            headers=self._auth(admin_token),
            json={
                "current_password": "admin123",
                "new_password": "AdminNew9",
                "confirm_password": "AdminNew9",
            },
        )
        self.assertEqual(alias.status_code, 200)
        self.assertEqual(self._login_admin("admin123").status_code, 401)
        admin_login = self._login_admin("AdminNew9")
        self.assertEqual(admin_login.status_code, 200)
        insights = self.client.get(
            "/admin/insights",
            headers=self._auth(admin_login.json()["access_token"]),
        )
        self.assertEqual(insights.status_code, 200)
        self.assertEqual(self._login_student("20240000002", "OtherPass2").status_code, 200)


if __name__ == "__main__":
    unittest.main()
