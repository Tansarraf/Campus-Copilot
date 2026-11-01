"""
TEMPLATE — do not run with real college data in source control.

Example pattern for provisioning fictional/demo student accounts later:

1. Keep plaintext passwords out of git (use env vars or a local CSV ignored by git).
2. Hash passwords with app.auth.hash_password at import time.
3. Store enrollment_number as an 11-digit TEXT string (preserve leading zeros).
4. Set is_demo=1 for any fictional account so it is never presented as a real record.
5. Call init_db() first so migrations have run.

This file is intentionally a template. Copy it locally (e.g. provision_students_local.py)
and add that copy to .gitignore before filling in demo credentials.

Example (illustrative only — replace with your own controlled demo data):

    from app.auth import hash_password
    from app.database import get_conn, init_db, now_iso
    from app.student_validation import normalize_enrollment_number

    def provision_one(enrollment, password, first, last, course, year, semester, email):
        enrollment = normalize_enrollment_number(enrollment)
        init_db()
        with get_conn() as conn:
            cur = conn.execute(
                '''INSERT INTO users (
                       username, password_hash, full_name, first_name, last_name,
                       email, email_verified, account_status, role, department, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, 0, 'active', 'student', ?, ?)''',
                (
                    enrollment,  # username mirrors enrollment for uniqueness
                    hash_password(password),
                    f"{first} {last}".strip(),
                    first,
                    last,
                    email,
                    course,
                    now_iso(),
                ),
            )
            user_id = cur.lastrowid
            conn.execute(
                '''INSERT INTO student_profiles (
                       user_id, enrollment_number, course, academic_year,
                       current_semester, is_demo, created_at
                   ) VALUES (?, ?, ?, ?, ?, 1, ?)''',
                (user_id, enrollment, course, year, semester, now_iso()),
            )
"""
