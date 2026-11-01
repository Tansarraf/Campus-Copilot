"""Tests for student schema migration and authentication foundation."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


class AuthFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls._tmpdir.name, "test_campus.db")
        os.environ["DATABASE_PATH"] = cls.db_path
        os.environ["GEMINI_API_KEY"] = "your_gemini_api_key_here"
        os.environ["USE_MOCK_LLM"] = "true"
        os.environ["JWT_SECRET"] = "test-secret-not-for-production"

        # Reload config + app against the temp database.
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
            # Legacy-style student user WITHOUT profile (pre-portal demo leftover).
            conn.execute(
                """INSERT INTO users (
                       username, password_hash, full_name, first_name, last_name,
                       email, email_verified, account_status, role, department, created_at
                   ) VALUES (?, ?, ?, ?, ?, NULL, 0, 'active', 'student', 'CSE', ?)""",
                (
                    "legacy_student",
                    hash_password("student123"),
                    "Legacy Student",
                    "Legacy",
                    "Student",
                    now_iso(),
                ),
            )
            cur = conn.execute(
                """INSERT INTO users (
                       username, password_hash, full_name, first_name, last_name,
                       email, email_verified, account_status, role, department, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, 0, 'active', 'student', 'B.Tech CSE', ?)""",
                (
                    "20240000001",
                    hash_password("StudentPass1"),
                    "Ada Lovelace",
                    "Ada",
                    "Lovelace",
                    "ada@example.com",
                    now_iso(),
                ),
            )
            user_id = cur.lastrowid
            conn.execute(
                """INSERT INTO student_profiles (
                       user_id, enrollment_number, course, academic_year,
                       current_semester, is_demo, created_at
                   ) VALUES (?, ?, ?, ?, ?, 1, ?)""",
                (user_id, "20240000001", "B.Tech Computer Science", "2024-25", 3, now_iso()),
            )

        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls._tmpdir.cleanup()

    def test_schema_has_student_profiles_and_user_columns(self):
        from app.database import get_conn

        with get_conn() as conn:
            user_cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
        for col in ("first_name", "last_name", "email", "email_verified", "account_status"):
            self.assertIn(col, user_cols)
        self.assertIn("student_profiles", tables)

    def test_enrollment_validation(self):
        from app.student_validation import is_valid_enrollment_number, normalize_enrollment_number

        self.assertTrue(is_valid_enrollment_number("01234567890"))
        self.assertFalse(is_valid_enrollment_number("123"))
        self.assertFalse(is_valid_enrollment_number("abcdefghijk"))
        self.assertEqual(normalize_enrollment_number("01234567890"), "01234567890")
        with self.assertRaises(ValueError):
            normalize_enrollment_number("12345")

    def test_register_disabled(self):
        res = self.client.post(
            "/auth/register",
            json={
                "username": "newuser",
                "password": "pass",
                "full_name": "New User",
            },
        )
        self.assertEqual(res.status_code, 403)

    def test_admin_login_ok_and_rejects_student_credentials(self):
        ok = self.client.post(
            "/auth/admin/login",
            json={"username": "admin", "password": "admin123"},
        )
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["role"], "admin")

        denied = self.client.post(
            "/auth/admin/login",
            json={"username": "legacy_student", "password": "student123"},
        )
        self.assertEqual(denied.status_code, 403)

    def test_student_login_by_enrollment(self):
        res = self.client.post(
            "/auth/student/login",
            json={"enrollment_number": "20240000001", "password": "StudentPass1"},
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["role"], "student")
        self.assertEqual(body["enrollment_number"], "20240000001")
        self.assertEqual(body["first_name"], "Ada")

        bad = self.client.post(
            "/auth/student/login",
            json={"enrollment_number": "20240000001", "password": "wrong"},
        )
        self.assertEqual(bad.status_code, 401)

        invalid = self.client.post(
            "/auth/student/login",
            json={"enrollment_number": "123", "password": "StudentPass1"},
        )
        self.assertEqual(invalid.status_code, 422)

    def test_me_uses_token_identity(self):
        login = self.client.post(
            "/auth/student/login",
            json={"enrollment_number": "20240000001", "password": "StudentPass1"},
        )
        token = login.json()["access_token"]
        me = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me.status_code, 200)
        profile = me.json()
        self.assertEqual(profile["enrollment_number"], "20240000001")
        self.assertEqual(profile["course"], "B.Tech Computer Science")
        self.assertTrue(profile["is_demo"])
        self.assertEqual(profile["role"], "student")

    def test_student_cannot_reach_admin_insights(self):
        login = self.client.post(
            "/auth/student/login",
            json={"enrollment_number": "20240000001", "password": "StudentPass1"},
        )
        token = login.json()["access_token"]
        res = self.client.get(
            "/admin/insights",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(res.status_code, 403)

    def test_password_forgot_is_still_a_stub(self):
        self.assertEqual(self.client.post("/auth/password/forgot").status_code, 501)

    def test_change_password_requires_auth(self):
        res = self.client.post(
            "/auth/change-password",
            json={
                "current_password": "admin123",
                "new_password": "NewPass99",
                "confirm_password": "NewPass99",
            },
        )
        self.assertEqual(res.status_code, 401)

    def test_migration_preserves_legacy_users_table(self):
        """Simulate a legacy DB and ensure migrate_schema upgrades without drop."""
        import sqlite3
        from app.database import migrate_schema

        legacy_path = os.path.join(self._tmpdir.name, "legacy.db")
        conn = sqlite3.connect(legacy_path)
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL,
                department TEXT,
                created_at TEXT NOT NULL
            );
            INSERT INTO users VALUES (1, 'admin', 'hash', 'Campus Admin', 'admin', 'Admin', 't');
            """
        )
        migrate_schema(conn)
        conn.commit()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
        self.assertIn("first_name", cols)
        self.assertIn("account_status", cols)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("student_profiles", tables)
        row = conn.execute("SELECT first_name, last_name, account_status FROM users WHERE id=1").fetchone()
        self.assertEqual(row["first_name"], "Campus")
        self.assertEqual(row["last_name"], "Admin")
        self.assertEqual(row["account_status"], "active")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)
        conn.close()


if __name__ == "__main__":
    unittest.main()
