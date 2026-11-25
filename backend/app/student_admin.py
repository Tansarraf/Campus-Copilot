"""Admin-provisioned student accounts and one-time password setup codes.

No email is sent. The plaintext setup code is returned once to the admin
so they can hand it to the student. Only a SHA-256 hash is stored.
"""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

from app.auth import hash_password
from app.database import get_conn, now_iso

SETUP_TTL_HOURS = 72
SETUP_DELIVERY_NOTE = (
    "No email was sent. Give this one-time setup code to the student in person "
    "or through a channel you already trust. It expires in 72 hours and works only once."
)


def _split_name(full_name: str) -> tuple[str, str]:
    parts = [p for p in (full_name or "").split() if p]
    if len(parts) < 2:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Full name must include a first and last name.",
        )
    return parts[0], " ".join(parts[1:])


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _issue_setup_token(conn, *, user_id: int, purpose: str, admin_id: int | None) -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=SETUP_TTL_HOURS)).isoformat()
    conn.execute(
        """UPDATE account_setup_tokens
           SET used_at = ?
           WHERE user_id = ? AND used_at IS NULL""",
        (now_iso(), user_id),
    )
    conn.execute(
        """INSERT INTO account_setup_tokens
           (user_id, token_hash, purpose, expires_at, used_at, created_at, created_by)
           VALUES (?, ?, ?, ?, NULL, ?, ?)""",
        (user_id, _hash_token(raw), purpose, expires, now_iso(), admin_id),
    )
    return raw, expires


def _audit(conn, *, admin_id: int, action: str, target_user_id: int, detail: str) -> None:
    conn.execute(
        """INSERT INTO admin_audit_log
           (admin_user_id, action, target_user_id, detail, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (admin_id, action, target_user_id, detail[:240], now_iso()),
    )


def _row_to_student(row) -> dict:
    return {
        "id": int(row["id"]),
        "full_name": row["full_name"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "email": row["email"],
        "enrollment_number": row["enrollment_number"],
        "course": row["course"],
        "department": row["department"],
        "academic_year": row["academic_year"],
        "current_semester": int(row["current_semester"]),
        "account_status": row["account_status"] or "active",
        "created_at": row["created_at"],
    }


def _load_student(conn, user_id: int) -> dict | None:
    row = conn.execute(
        """SELECT u.id, u.full_name, u.first_name, u.last_name, u.email, u.department,
                  u.account_status, u.created_at, u.role,
                  sp.enrollment_number, sp.course, sp.academic_year, sp.current_semester
           FROM users u
           JOIN student_profiles sp ON sp.user_id = u.id
           WHERE u.id = ? AND u.role = 'student'""",
        (user_id,),
    ).fetchone()
    return _row_to_student(row) if row else None


def _student_counts(conn) -> tuple[int, int]:
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN COALESCE(account_status, 'active') = 'active' THEN 1 ELSE 0 END) AS active
           FROM users WHERE role = 'student'"""
    ).fetchone()
    return int(row["total"] or 0), int(row["active"] or 0)


def list_students(
    *,
    q: str | None,
    course: str | None,
    academic_year: str | None,
    account_status: str | None,
    page: int,
    page_size: int,
) -> dict:
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    clauses = ["u.role = 'student'"]
    params: list = []
    if q and q.strip():
        like = f"%{q.strip()}%"
        clauses.append(
            "(u.full_name LIKE ? OR u.email LIKE ? OR sp.enrollment_number LIKE ?)"
        )
        params.extend([like, like, like])
    if course and course.strip():
        clauses.append("(sp.course = ? OR u.department = ?)")
        params.extend([course.strip(), course.strip()])
    if academic_year and academic_year.strip():
        clauses.append("sp.academic_year = ?")
        params.append(academic_year.strip())
    if account_status and account_status.strip():
        clauses.append("COALESCE(u.account_status, 'active') = ?")
        params.append(account_status.strip())
    where = " AND ".join(clauses)
    with get_conn() as conn:
        total = conn.execute(
            f"""SELECT COUNT(*) AS n
                FROM users u JOIN student_profiles sp ON sp.user_id = u.id
                WHERE {where}""",
            params,
        ).fetchone()["n"]
        rows = conn.execute(
            f"""SELECT u.id, u.full_name, u.first_name, u.last_name, u.email, u.department,
                       u.account_status, u.created_at,
                       sp.enrollment_number, sp.course, sp.academic_year, sp.current_semester
                FROM users u JOIN student_profiles sp ON sp.user_id = u.id
                WHERE {where}
                ORDER BY u.created_at DESC, u.id DESC
                LIMIT ? OFFSET ?""",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
        student_count, active_count = _student_counts(conn)
    pages = max(1, (int(total) + page_size - 1) // page_size)
    return {
        "items": [_row_to_student(r) for r in rows],
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "total_pages": pages,
        "active_count": active_count,
        "student_count": student_count,
    }


def filter_options() -> dict:
    with get_conn() as conn:
        courses = [
            r[0]
            for r in conn.execute(
                """SELECT DISTINCT course FROM student_profiles
                   WHERE course IS NOT NULL AND course != '' ORDER BY course"""
            ).fetchall()
        ]
        years = [
            r[0]
            for r in conn.execute(
                """SELECT DISTINCT academic_year FROM student_profiles
                   WHERE academic_year IS NOT NULL AND academic_year != ''
                   ORDER BY academic_year DESC"""
            ).fetchall()
        ]
    return {
        "courses": courses,
        "academic_years": years,
        "statuses": ["active", "pending_activation", "disabled"],
    }


def create_student(payload: dict, *, admin_id: int) -> dict:
    first, last = _split_name(payload["full_name"])
    enrollment = payload["enrollment_number"]
    email = payload["email"]
    course = payload["course"].strip()
    year = payload["academic_year"].strip()
    semester = int(payload["current_semester"])
    # Unknown password until the student completes setup.
    placeholder = hash_password(secrets.token_urlsafe(48))
    try:
        with get_conn() as conn:
            email_hit = conn.execute(
                "SELECT id FROM users WHERE email = ?", (email,)
            ).fetchone()
            if email_hit:
                raise HTTPException(status.HTTP_409_CONFLICT, "Email address is already in use.")
            enroll_hit = conn.execute(
                """SELECT user_id FROM student_profiles WHERE enrollment_number = ?
                   UNION SELECT id FROM users WHERE username = ?""",
                (enrollment, enrollment),
            ).fetchone()
            if enroll_hit:
                raise HTTPException(status.HTTP_409_CONFLICT, "Enrollment number is already in use.")
            cur = conn.execute(
                """INSERT INTO users (
                       username, password_hash, full_name, first_name, last_name,
                       email, email_verified, account_status, role, department, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, 0, 'pending_activation', 'student', ?, ?)""",
                (
                    enrollment,
                    placeholder,
                    f"{first} {last}".strip(),
                    first,
                    last,
                    email,
                    course,
                    now_iso(),
                ),
            )
            user_id = int(cur.lastrowid)
            conn.execute(
                """INSERT INTO student_profiles (
                       user_id, enrollment_number, course, academic_year,
                       current_semester, is_demo, created_at
                   ) VALUES (?, ?, ?, ?, ?, 0, ?)""",
                (user_id, enrollment, course, year, semester, now_iso()),
            )
            raw, expires = _issue_setup_token(
                conn, user_id=user_id, purpose="activation", admin_id=admin_id
            )
            _audit(
                conn,
                admin_id=admin_id,
                action="student_created",
                target_user_id=user_id,
                detail=f"enrollment={enrollment}",
            )
            student = _load_student(conn, user_id)
    except sqlite3.IntegrityError as exc:
        message = str(exc).lower()
        if "email" in message:
            raise HTTPException(status.HTTP_409_CONFLICT, "Email address is already in use.") from exc
        raise HTTPException(status.HTTP_409_CONFLICT, "Enrollment number is already in use.") from exc
    return {
        "student": student,
        "setup": {
            "token": raw,
            "expires_at": expires,
            "purpose": "activation",
            "delivery": SETUP_DELIVERY_NOTE,
        },
    }


def update_student(user_id: int, payload: dict, *, admin_id: int) -> dict:
    incoming = {k: v for k, v in payload.items() if v is not None}
    if not incoming:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields to update.")
    with get_conn() as conn:
        existing = _load_student(conn, user_id)
        if existing is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found.")
        user_sets = []
        user_params: list = []
        profile_sets = []
        profile_params: list = []
        if "full_name" in incoming:
            first, last = _split_name(incoming["full_name"])
            user_sets.extend(["first_name = ?", "last_name = ?", "full_name = ?"])
            user_params.extend([first, last, f"{first} {last}"])
        if "email" in incoming:
            clash = conn.execute(
                "SELECT id FROM users WHERE email = ? AND id != ?",
                (incoming["email"], user_id),
            ).fetchone()
            if clash:
                raise HTTPException(status.HTTP_409_CONFLICT, "Email address is already in use.")
            user_sets.extend(["email = ?", "email_verified = 0"])
            user_params.append(incoming["email"])
        if "course" in incoming:
            profile_sets.append("course = ?")
            profile_params.append(incoming["course"])
            user_sets.append("department = ?")
            user_params.append(incoming["course"])
        if "academic_year" in incoming:
            profile_sets.append("academic_year = ?")
            profile_params.append(incoming["academic_year"])
        if "current_semester" in incoming:
            profile_sets.append("current_semester = ?")
            profile_params.append(int(incoming["current_semester"]))
        if user_sets:
            user_params.append(user_id)
            conn.execute(
                f"UPDATE users SET {', '.join(user_sets)} WHERE id = ? AND role = 'student'",
                user_params,
            )
        if profile_sets:
            profile_params.append(user_id)
            conn.execute(
                f"UPDATE student_profiles SET {', '.join(profile_sets)} WHERE user_id = ?",
                profile_params,
            )
        _audit(
            conn,
            admin_id=admin_id,
            action="student_updated",
            target_user_id=user_id,
            detail=",".join(sorted(incoming)),
        )
        return _load_student(conn, user_id)


def set_student_status(user_id: int, account_status: str, *, admin_id: int) -> dict:
    with get_conn() as conn:
        existing = _load_student(conn, user_id)
        if existing is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found.")
        if account_status == "active" and existing["account_status"] == "pending_activation":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "This student must finish password setup before the account can be activated.",
            )
        conn.execute(
            "UPDATE users SET account_status = ? WHERE id = ? AND role = 'student'",
            (account_status, user_id),
        )
        _audit(
            conn,
            admin_id=admin_id,
            action="student_status",
            target_user_id=user_id,
            detail=account_status,
        )
        return _load_student(conn, user_id)


def reset_student_password(user_id: int, *, admin_id: int) -> dict:
    with get_conn() as conn:
        existing = _load_student(conn, user_id)
        if existing is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found.")
        conn.execute(
            """UPDATE users
               SET password_hash = ?, account_status = 'pending_activation'
               WHERE id = ? AND role = 'student'""",
            (hash_password(secrets.token_urlsafe(48)), user_id),
        )
        raw, expires = _issue_setup_token(
            conn, user_id=user_id, purpose="reset", admin_id=admin_id
        )
        _audit(
            conn,
            admin_id=admin_id,
            action="student_password_reset",
            target_user_id=user_id,
            detail="setup code issued",
        )
        student = _load_student(conn, user_id)
    return {
        "student": student,
        "setup": {
            "token": raw,
            "expires_at": expires,
            "purpose": "reset",
            "delivery": SETUP_DELIVERY_NOTE,
        },
    }


def complete_password_setup(*, token: str, new_password: str) -> None:
    token = (token or "").strip()
    if not token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Setup code is required.")
    digest = _hash_token(token)
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        row = conn.execute(
            """SELECT id, user_id, expires_at, used_at
               FROM account_setup_tokens WHERE token_hash = ?""",
            (digest,),
        ).fetchone()
        if row is None or row["used_at"] is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This setup code is invalid or already used.")
        try:
            expires = datetime.fromisoformat(row["expires_at"])
        except ValueError:
            expires = now
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < now:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This setup code has expired.")
        user = conn.execute(
            "SELECT id, role FROM users WHERE id = ?", (row["user_id"],)
        ).fetchone()
        if user is None or user["role"] != "student":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This setup code is invalid or already used.")
        conn.execute(
            """UPDATE users
               SET password_hash = ?, account_status = 'active'
               WHERE id = ?""",
            (hash_password(new_password), user["id"]),
        )
        conn.execute(
            "UPDATE account_setup_tokens SET used_at = ? WHERE id = ?",
            (now_iso(), row["id"]),
        )
