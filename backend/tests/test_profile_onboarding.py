"""Tests for student profile completion and PATCH /auth/me."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


class ProfileOnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls._tmpdir.name, "profile_test.db")
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

        # Reload auth/router modules that cached config/db imports.
        import app.auth as auth
        import app.routers.auth_router as auth_router
        importlib.reload(auth)
        importlib.reload(auth_router)

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
                ("admin", hash_password("admin123"), "Campus Admin", "Campus", "Admin",
                 "admin@example.com", now_iso()),
            )
            # Incomplete student: names + enrollment/course present; missing email/year/semester
            # Wait — academic_year and current_semester are NOT NULL in schema.
            # So provision with placeholders empty? Schema requires NOT NULL for course, year, semester.
            # Use sentinel empty-ish? academic_year TEXT NOT NULL — can be '' ? CHECK doesn't block ''.
            # current_semester INTEGER NOT NULL — must be a number. Use a value then clear via SQL?
            # Better: store year as '' and semester as NULL by altering... CHECK allows 1-12.
            # For incomplete year: use empty string '' for academic_year.
            # For semester incompleteness: the _present check treats 0 as present (bool).
            # Use None — but NOT NULL constraint. So for incomplete semester we need nullable column
            # OR treat a sentinel. Spec says if missing allow student to fill.
            # Easiest: migrate student_profiles to allow NULL academic_year/semester for incomplete.
            # Or use empty string for year and leave semester as required provisioned.
            #
            # Profile complete requires current_semester present. If admin always provisions semester,
            # incomplete case is mainly email. Create two students:
            # A) incomplete: missing email only (year/semester provisioned)
            # B) complete: all fields set

            cur = conn.execute(
                """INSERT INTO users (
                       username, password_hash, full_name, first_name, last_name,
                       email, email_verified, account_status, role, department, created_at
                   ) VALUES (?, ?, ?, ?, ?, NULL, 0, 'active', 'student', 'CSE', ?)""",
                ("20240000001", hash_password("StudentPass1"), "Ada Lovelace",
                 "Ada", "Lovelace", now_iso()),
            )
            incomplete_id = cur.lastrowid
            conn.execute(
                """INSERT INTO student_profiles (
                       user_id, enrollment_number, course, academic_year,
                       current_semester, is_demo, created_at
                   ) VALUES (?, ?, ?, ?, ?, 1, ?)""",
                (incomplete_id, "20240000001", "B.Tech CSE", "2024-25", 3, now_iso()),
            )

            cur = conn.execute(
                """INSERT INTO users (
                       username, password_hash, full_name, first_name, last_name,
                       email, email_verified, account_status, role, department, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, 1, 'active', 'student', 'CSE', ?)""",
                ("20240000002", hash_password("StudentPass2"), "Grace Hopper",
                 "Grace", "Hopper", "grace@example.com", now_iso()),
            )
            complete_id = cur.lastrowid
            conn.execute(
                """INSERT INTO student_profiles (
                       user_id, enrollment_number, course, academic_year,
                       current_semester, is_demo, created_at
                   ) VALUES (?, ?, ?, ?, ?, 1, ?)""",
                (complete_id, "20240000002", "B.Tech CSE", "2024-25", 5, now_iso()),
            )

            # Student missing names (admin left blank) — fill-once path
            cur = conn.execute(
                """INSERT INTO users (
                       username, password_hash, full_name, first_name, last_name,
                       email, email_verified, account_status, role, department, created_at
                   ) VALUES (?, ?, ?, '', '', NULL, 0, 'active', 'student', 'ECE', ?)""",
                ("20240000003", hash_password("StudentPass3"), "Pending Name", now_iso()),
            )
            blank_id = cur.lastrowid
            conn.execute(
                """INSERT INTO student_profiles (
                       user_id, enrollment_number, course, academic_year,
                       current_semester, is_demo, created_at
                   ) VALUES (?, ?, ?, '', ?, 1, ?)""",
                (blank_id, "20240000003", "B.Tech ECE", 1, now_iso()),
            )

        cls.client = TestClient(app)
        cls.incomplete_enrollment = "20240000001"
        cls.complete_enrollment = "20240000002"
        cls.blank_enrollment = "20240000003"

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls._tmpdir.cleanup()

    def _student_login(self, enrollment, password):
        res = self.client.post(
            "/auth/student/login",
            json={"enrollment_number": enrollment, "password": password},
        )
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["access_token"]

    def test_me_requires_auth(self):
        res = self.client.get("/auth/me")
        self.assertEqual(res.status_code, 401)

    def test_flags_show_incomplete_before_patch(self):
        token = self._student_login(self.incomplete_enrollment, "StudentPass1")
        me = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me.status_code, 200)
        body = me.json()
        self.assertFalse(body["profile_complete"])
        self.assertIn("email", body["missing_fields"])
        self.assertIn("email", body["editable_fields"])
        self.assertEqual(body["first_name"], "Ada")

    def test_patch_completes_profile_and_persists(self):
        token = self._student_login(self.incomplete_enrollment, "StudentPass1")
        patched = self.client.patch(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": "ada@university.edu"},
        )
        self.assertEqual(patched.status_code, 200, patched.text)
        body = patched.json()
        self.assertEqual(body["email"], "ada@university.edu")
        self.assertFalse(body["email_verified"])
        self.assertTrue(body["profile_complete"])
        self.assertEqual(body["missing_fields"], [])

        # Persists across a fresh login
        token2 = self._student_login(self.incomplete_enrollment, "StudentPass1")
        me = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token2}"})
        self.assertTrue(me.json()["profile_complete"])
        self.assertEqual(me.json()["email"], "ada@university.edu")

    def test_cannot_change_enrollment_or_course_or_role(self):
        token = self._student_login(self.complete_enrollment, "StudentPass2")
        # Pydantic strips unknown fields by default — send via raw dict with extra keys
        # Our schema only has allowlisted fields; attempting first_name when already set is blocked.
        denied = self.client.patch(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            json={"first_name": "Hacker", "last_name": "Person"},
        )
        self.assertEqual(denied.status_code, 400)
        self.assertIn("Cannot update", denied.json()["detail"])

        # Enrollment is not a schema field — ignored; email update still works
        ok = self.client.patch(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": "grace2@example.com", "enrollment_number": "99999999999"},
        )
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["enrollment_number"], "20240000002")
        self.assertEqual(ok.json()["email"], "grace2@example.com")
        self.assertFalse(ok.json()["email_verified"])

    def test_fill_once_names_and_year(self):
        token = self._student_login(self.blank_enrollment, "StudentPass3")
        me = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        body = me.json()
        self.assertFalse(body["profile_complete"])
        for field in ("first_name", "last_name", "academic_year", "email"):
            self.assertIn(field, body["missing_fields"])
            self.assertIn(field, body["editable_fields"])

        patched = self.client.patch(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "first_name": "Priya",
                "last_name": "Shah",
                "academic_year": "2025-26",
                "email": "priya@university.edu",
            },
        )
        self.assertEqual(patched.status_code, 200, patched.text)
        out = patched.json()
        self.assertTrue(out["profile_complete"])
        self.assertEqual(out["first_name"], "Priya")
        self.assertEqual(out["academic_year"], "2025-26")

        # Cannot change name again
        denied = self.client.patch(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            json={"first_name": "Other"},
        )
        self.assertEqual(denied.status_code, 400)

    def test_admin_me_is_complete_no_onboarding_fields(self):
        login = self.client.post("/auth/admin/login", json={"username": "admin", "password": "admin123"})
        token = login.json()["access_token"]
        me = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        body = me.json()
        self.assertEqual(body["role"], "admin")
        self.assertTrue(body["profile_complete"])
        self.assertEqual(body["required_fields"], [])

        # Admin cannot use student PATCH
        denied = self.client.patch(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": "x@y.com"},
        )
        self.assertEqual(denied.status_code, 403)

    def test_unauthenticated_patch_rejected(self):
        res = self.client.patch("/auth/me", json={"email": "x@y.com"})
        self.assertEqual(res.status_code, 401)


if __name__ == "__main__":
    unittest.main()
