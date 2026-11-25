"""Admin student provisioning, directory, status, and one-time password setup."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


class StudentAdminTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls._tmpdir.name, "users.db")
        os.environ["DATABASE_PATH"] = cls.db_path
        os.environ["GEMINI_API_KEY"] = "your_gemini_api_key_here"
        os.environ["USE_MOCK_LLM"] = "true"
        os.environ["JWT_SECRET"] = "test-secret-users"

        import importlib
        import app.config as config
        import app.database as database
        import app.auth as auth
        import app.student_admin as student_admin
        import app.routers.auth_router as auth_router
        import app.routers.students_admin_router as students_admin_router
        import app.main as main

        importlib.reload(config)
        importlib.reload(database)
        database.DATABASE_PATH = cls.db_path
        config.DATABASE_PATH = cls.db_path
        importlib.reload(auth)
        importlib.reload(student_admin)
        importlib.reload(auth_router)
        importlib.reload(students_admin_router)
        importlib.reload(main)

        from app.auth import hash_password
        from app.database import get_conn, init_db, now_iso

        init_db()
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO users (
                       username, password_hash, full_name, first_name, last_name,
                       email, email_verified, account_status, role, department, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, 1, 'active', 'admin', 'Administration', ?)""",
                ("admin", hash_password("admin123"), "Campus Admin", "Campus", "Admin", "admin@example.com", now_iso()),
            )
            cur = conn.execute(
                """INSERT INTO users (
                       username, password_hash, full_name, first_name, last_name,
                       email, email_verified, account_status, role, department, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, 0, 'active', 'student', 'CSE', ?)""",
                ("20240000011", hash_password("pass111111"), "Alice One", "Alice", "One", "alice@example.com", now_iso()),
            )
            conn.execute(
                """INSERT INTO student_profiles (
                       user_id, enrollment_number, course, academic_year,
                       current_semester, is_demo, created_at
                   ) VALUES (?, ?, ?, ?, ?, 1, ?)""",
                (cur.lastrowid, "20240000011", "B.Tech CSE", "2024-25", 3, now_iso()),
            )

        cls.client = TestClient(main.app)
        cls.admin = cls.client.post(
            "/auth/admin/login", json={"username": "admin", "password": "admin123"}
        ).json()["access_token"]
        cls.alice = cls.client.post(
            "/auth/student/login",
            json={"enrollment_number": "20240000011", "password": "pass111111"},
        ).json()["access_token"]

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def _admin(self):
        return {"Authorization": f"Bearer {self.admin}"}

    def _student(self):
        return {"Authorization": f"Bearer {self.alice}"}

    def _payload(self, **overrides):
        body = {
            "full_name": "New Student",
            "enrollment_number": "20241111111",
            "email": "new.student@example.com",
            "course": "B.Tech CSE",
            "academic_year": "2026-27",
            "current_semester": 1,
        }
        body.update(overrides)
        return body

    def test_admin_creates_student_and_directory(self):
        created = self.client.post("/admin/students", headers=self._admin(), json=self._payload())
        self.assertEqual(created.status_code, 201, created.text)
        body = created.json()
        self.assertEqual(body["student"]["account_status"], "pending_activation")
        self.assertNotIn("password", body["student"])
        self.assertTrue(body["setup"]["token"])
        self.assertIn("No email", body["setup"]["delivery"])

        listed = self.client.get("/admin/students?q=20241111111", headers=self._admin())
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["total"], 1)
        self.assertGreaterEqual(listed.json()["student_count"], 2)

        blocked = self.client.post(
            "/auth/student/login",
            json={"enrollment_number": "20241111111", "password": "pass111111"},
        )
        self.assertIn(blocked.status_code, (401, 403))

        setup = self.client.post(
            "/auth/setup-password",
            json={
                "token": body["setup"]["token"],
                "new_password": "Freshpass1",
                "confirm_password": "Freshpass1",
            },
        )
        self.assertEqual(setup.status_code, 200, setup.text)
        again = self.client.post(
            "/auth/setup-password",
            json={
                "token": body["setup"]["token"],
                "new_password": "Freshpass1",
                "confirm_password": "Freshpass1",
            },
        )
        self.assertEqual(again.status_code, 400)

        login = self.client.post(
            "/auth/student/login",
            json={"enrollment_number": "20241111111", "password": "Freshpass1"},
        )
        self.assertEqual(login.status_code, 200, login.text)

    def test_duplicates_and_validation(self):
        self.client.post("/admin/students", headers=self._admin(), json=self._payload(
            enrollment_number="20242222222", email="dup@example.com", full_name="Dup Student"
        ))
        dup_enroll = self.client.post("/admin/students", headers=self._admin(), json=self._payload(
            enrollment_number="20242222222", email="other@example.com", full_name="Other Student"
        ))
        self.assertEqual(dup_enroll.status_code, 409)
        dup_email = self.client.post("/admin/students", headers=self._admin(), json=self._payload(
            enrollment_number="20243333333", email="dup@example.com", full_name="Other Student"
        ))
        self.assertEqual(dup_email.status_code, 409)
        bad = self.client.post("/admin/students", headers=self._admin(), json=self._payload(
            enrollment_number="123", email="short@example.com"
        ))
        self.assertEqual(bad.status_code, 422)
        missing = self.client.post("/admin/students", headers=self._admin(), json={"full_name": "Only Name"})
        self.assertEqual(missing.status_code, 422)

    def test_student_cannot_manage_users(self):
        denied = self.client.get("/admin/students", headers=self._student())
        self.assertEqual(denied.status_code, 403)
        denied_create = self.client.post("/admin/students", headers=self._student(), json=self._payload())
        self.assertEqual(denied_create.status_code, 403)

    def test_search_filter_pagination_and_edit(self):
        for i in range(3):
            self.client.post("/admin/students", headers=self._admin(), json=self._payload(
                full_name=f"Filter Student{i}",
                enrollment_number=f"2024555555{i}",
                email=f"filter{i}@example.com",
                course="MBA",
                academic_year="2025-26",
            ))
        searched = self.client.get("/admin/students?q=Filter&course=MBA&academic_year=2025-26", headers=self._admin())
        self.assertEqual(searched.status_code, 200)
        self.assertGreaterEqual(searched.json()["total"], 3)
        page = self.client.get("/admin/students?page=1&page_size=1&course=MBA", headers=self._admin())
        self.assertEqual(len(page.json()["items"]), 1)
        self.assertGreaterEqual(page.json()["total_pages"], 3)
        student_id = page.json()["items"][0]["id"]
        edited = self.client.patch(
            f"/admin/students/{student_id}",
            headers=self._admin(),
            json={"course": "MBA Finance", "current_semester": 2},
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()["course"], "MBA Finance")
        self.assertEqual(edited.json()["current_semester"], 2)

    def test_deactivate_blocks_login_and_existing_token(self):
        created = self.client.post("/admin/students", headers=self._admin(), json=self._payload(
            full_name="Disable Student",
            enrollment_number="20246666666",
            email="disable@example.com",
        ))
        token = created.json()["setup"]["token"]
        user_id = created.json()["student"]["id"]
        self.client.post("/auth/setup-password", json={
            "token": token, "new_password": "Disable1a", "confirm_password": "Disable1a",
        })
        session = self.client.post("/auth/student/login", json={
            "enrollment_number": "20246666666", "password": "Disable1a",
        }).json()["access_token"]
        self.assertEqual(
            self.client.get("/auth/me", headers={"Authorization": f"Bearer {session}"}).status_code,
            200,
        )
        off = self.client.post(
            f"/admin/students/{user_id}/status",
            headers=self._admin(),
            json={"account_status": "disabled"},
        )
        self.assertEqual(off.status_code, 200)
        self.assertEqual(
            self.client.get("/auth/me", headers={"Authorization": f"Bearer {session}"}).status_code,
            403,
        )
        relogin = self.client.post("/auth/student/login", json={
            "enrollment_number": "20246666666", "password": "Disable1a",
        })
        self.assertEqual(relogin.status_code, 403)
        still = self.client.post("/auth/student/login", json={
            "enrollment_number": "20240000011", "password": "pass111111",
        })
        self.assertEqual(still.status_code, 200)
        admin_still = self.client.post("/auth/admin/login", json={"username": "admin", "password": "admin123"})
        self.assertEqual(admin_still.status_code, 200)

    def test_password_reset_invalidates_old_password(self):
        created = self.client.post("/admin/students", headers=self._admin(), json=self._payload(
            full_name="Reset Student",
            enrollment_number="20247777777",
            email="reset@example.com",
        ))
        user_id = created.json()["student"]["id"]
        self.client.post("/auth/setup-password", json={
            "token": created.json()["setup"]["token"],
            "new_password": "Resetpass1",
            "confirm_password": "Resetpass1",
        })
        reset = self.client.post(f"/admin/students/{user_id}/password-reset", headers=self._admin())
        self.assertEqual(reset.status_code, 200, reset.text)
        old = self.client.post("/auth/student/login", json={
            "enrollment_number": "20247777777", "password": "Resetpass1",
        })
        self.assertNotEqual(old.status_code, 200)
        done = self.client.post("/auth/setup-password", json={
            "token": reset.json()["setup"]["token"],
            "new_password": "Resetpass2",
            "confirm_password": "Resetpass2",
        })
        self.assertEqual(done.status_code, 200, done.text)
        fresh = self.client.post("/auth/student/login", json={
            "enrollment_number": "20247777777", "password": "Resetpass2",
        })
        self.assertEqual(fresh.status_code, 200, fresh.text)


if __name__ == "__main__":
    unittest.main()
