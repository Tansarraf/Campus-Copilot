"""
Ensures an administrator account exists so a fresh local database can be used.

Student accounts are administrator-provisioned and are NOT created here.
See scripts/provision_students_TEMPLATE.py for a safe import pattern.

Run from backend/:

  set INITIAL_ADMIN_PASSWORD=...   # never commit this value
  python scripts/seed_users.py

This script is never invoked by FastAPI startup or Docker Compose.

Existing users are left unchanged (no password overwrite).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.auth import hash_password
from app.database import get_conn, init_db, now_iso

ADMIN_USERNAME = os.getenv("CAMPUS_ADMIN_USERNAME", "admin")
ADMIN_FULL_NAME = os.getenv("CAMPUS_ADMIN_FULL_NAME", "Campus Admin")


def _require_initial_admin_password() -> str:
    password = os.getenv("INITIAL_ADMIN_PASSWORD", "")
    if not password.strip():
        print(
            "INITIAL_ADMIN_PASSWORD is required to create the first administrator. "
            "Set it in the environment (not in git) and rerun. "
            "Existing accounts are never modified."
        )
        sys.exit(2)
    return password


def main():
    init_db()
    first, _, last = ADMIN_FULL_NAME.partition(" ")
    last = last or ""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (ADMIN_USERNAME,),
        ).fetchone()
        if existing:
            print(f"skip (already exists): {ADMIN_USERNAME} (admin)")
            return

        password = _require_initial_admin_password()
        conn.execute(
            """INSERT INTO users (
                   username, password_hash, full_name, first_name, last_name,
                   email, email_verified, account_status, role, department, created_at
               ) VALUES (?, ?, ?, ?, ?, NULL, 0, 'active', 'admin', 'Administration', ?)""",
            (
                ADMIN_USERNAME,
                hash_password(password),
                ADMIN_FULL_NAME,
                first,
                last,
                now_iso(),
            ),
        )
        print(f"created admin: {ADMIN_USERNAME}")


if __name__ == "__main__":
    main()
