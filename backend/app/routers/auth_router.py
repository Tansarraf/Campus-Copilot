"""
Authentication routes.

Login design for the upcoming public UI:
  - Student path: POST /auth/student/login  (enrollment_number + password)
  - Admin path:   POST /auth/admin/login    (username + password, role enforced)
  - Legacy:       POST /auth/login          (username + password; kept for current UI)
  - Profile:      GET  /auth/me             (identity from JWT only)

Public self-registration is disabled; accounts are administrator-provisioned.
Password-reset / email OTP are reserved (501) until mail + rate limits are configured.
"""
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import (
    build_profile_payload,
    compute_editable_fields,
    create_access_token,
    display_name,
    fetch_student_profile,
    get_current_user,
    hash_password,
    require_student,
    validate_password_strength,
    verify_password,
)
from app.database import get_conn
from app.schemas import (
    AdminLoginRequest,
    ChangePasswordRequest,
    ChangePasswordResponse,
    LoginRequest,
    ProfileResponse,
    ProfileUpdateRequest,
    RegisterRequest,
    StudentLoginRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Required before enabling forgot-password / OTP (not implemented in this phase):
#   SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
#   OTP_EXPIRY_MINUTES, OTP_MAX_ATTEMPTS, LOGIN_RATE_LIMIT_PER_MINUTE
#   PASSWORD_RESET_RATE_LIMIT_PER_HOUR
AUTH_SECURITY_CONFIG_NOTES = {
    "login_rate_limit": "Per-IP and per-identifier limits on /auth/*/login (e.g. 5/min).",
    "password_reset_rate_limit": "Per-email / per-enrollment caps on reset requests.",
    "otp_delivery": "Requires configured SMTP (or equivalent); never fake email delivery.",
    "otp_storage": "Store only hashed OTPs with short TTL; invalidate on success or expiry.",
}


def _token_response(user: dict, enrollment_number: str | None = None) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user),
        role=user["role"],
        full_name=display_name(user),
        first_name=user.get("first_name"),
        enrollment_number=enrollment_number,
    )


def _reject_if_inactive(user: dict) -> None:
    status_value = user.get("account_status") or "active"
    if status_value == "disabled":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is disabled")
    if status_value == "pending_activation":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is pending activation")


@router.post("/register", response_model=TokenResponse, deprecated=True)
def register(req: RegisterRequest):
    """Disabled: student accounts are provisioned by administrators."""
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Public registration is disabled. Student accounts are provisioned by an administrator.",
    )


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest):
    """
    Legacy username/password login used by the current frontend.
    Role is taken from the database record, never from the request body.
    Prefer /auth/admin/login or /auth/student/login for the new portal UI.
    """
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (req.username,)).fetchone()
    if row is None or not verify_password(req.password, row["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    user = dict(row)
    _reject_if_inactive(user)
    enrollment = None
    if user["role"] == "student":
        with get_conn() as conn:
            profile = conn.execute(
                "SELECT enrollment_number FROM student_profiles WHERE user_id = ?",
                (user["id"],),
            ).fetchone()
        enrollment = profile["enrollment_number"] if profile else None
    return _token_response(user, enrollment_number=enrollment)


@router.post("/admin/login", response_model=TokenResponse)
def admin_login(req: AdminLoginRequest):
    """Dedicated admin login. Rejects non-admin accounts even with valid passwords."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (req.username,)).fetchone()
    if row is None or not verify_password(req.password, row["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    user = dict(row)
    _reject_if_inactive(user)
    if user["role"] != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return _token_response(user)


@router.post("/student/login", response_model=TokenResponse)
def student_login(req: StudentLoginRequest):
    """
    Student login by enrollment number (11-digit string) + password.
    Role and academic fields come from the database, not the request.
    """
    with get_conn() as conn:
        row = conn.execute(
            """SELECT u.*, sp.enrollment_number
               FROM users u
               JOIN student_profiles sp ON sp.user_id = u.id
               WHERE sp.enrollment_number = ?""",
            (req.enrollment_number,),
        ).fetchone()
    if row is None or not verify_password(req.password, row["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid enrollment number or password")
    user = dict(row)
    _reject_if_inactive(user)
    if user["role"] != "student":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Student access required")
    return _token_response(user, enrollment_number=user.get("enrollment_number"))


@router.get("/me", response_model=ProfileResponse)
def me(user: dict = Depends(get_current_user)):
    """Return the authenticated user's authoritative profile (for greeting / profile page)."""
    return ProfileResponse(**build_profile_payload(user))


@router.patch("/me", response_model=ProfileResponse)
def update_me(req: ProfileUpdateRequest, user: dict = Depends(require_student)):
    """
    Persist student-editable profile fields only.

    Identity comes from the JWT. Enrollment number, role, account status, and
    administrator-provisioned course cannot be changed here. Email changes
    reset email_verified until a real verification flow exists.
    """
    profile = fetch_student_profile(user["id"])
    allowed = set(compute_editable_fields(user, profile))
    incoming = req.model_dump(exclude_unset=True)

    # Reject attempts to set fields that are not currently editable.
    blocked = [key for key in incoming if key not in allowed]
    if blocked:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Cannot update protected or already-provisioned fields: {', '.join(blocked)}",
        )

    if not incoming:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No editable fields provided")

    with get_conn() as conn:
        user_updates = []
        user_params: list = []

        if "email" in incoming:
            new_email = incoming["email"]
            if new_email:
                clash = conn.execute(
                    "SELECT id FROM users WHERE email = ? AND id != ?",
                    (new_email, user["id"]),
                ).fetchone()
                if clash:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email already in use")
            user_updates.append("email = ?")
            user_params.append(new_email)
            # Changing or setting email requires verification before recovery use.
            user_updates.append("email_verified = 0")

        if "first_name" in incoming:
            user_updates.append("first_name = ?")
            user_params.append(incoming["first_name"])
        if "last_name" in incoming:
            user_updates.append("last_name = ?")
            user_params.append(incoming["last_name"])

        if user_updates:
            # Keep full_name in sync for JWT / legacy display.
            row = conn.execute(
                "SELECT first_name, last_name, full_name FROM users WHERE id = ?",
                (user["id"],),
            ).fetchone()
            first = incoming.get("first_name", row["first_name"])
            last = incoming.get("last_name", row["last_name"])
            joined = f"{(first or '').strip()} {(last or '').strip()}".strip()
            if joined:
                user_updates.append("full_name = ?")
                user_params.append(joined)
            user_params.append(user["id"])
            conn.execute(
                f"UPDATE users SET {', '.join(user_updates)} WHERE id = ?",
                user_params,
            )

        profile_updates = []
        profile_params: list = []
        if "academic_year" in incoming:
            profile_updates.append("academic_year = ?")
            profile_params.append(incoming["academic_year"])
        if "current_semester" in incoming:
            profile_updates.append("current_semester = ?")
            profile_params.append(incoming["current_semester"])

        if profile_updates:
            if profile is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Student profile record is missing. Contact an administrator.",
                )
            profile_params.append(user["id"])
            conn.execute(
                f"UPDATE student_profiles SET {', '.join(profile_updates)} WHERE user_id = ?",
                profile_params,
            )

        refreshed = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()

    return ProfileResponse(**build_profile_payload(dict(refreshed)))


@router.post("/password/forgot", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def forgot_password():
    """Reserved for email-OTP recovery once SMTP and rate limits are configured."""
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        {
            "message": "Password recovery is not configured yet.",
            "required_protections": AUTH_SECURITY_CONFIG_NOTES,
        },
    )


def _change_password(req: ChangePasswordRequest, user: dict) -> ChangePasswordResponse:
    """
    Change the authenticated user's password only.

    The target account is taken from JWT `sub` / get_current_user — never from
    a client-supplied user id or username. Plaintext passwords are not logged.
    Existing JWTs remain valid until expiry: the current token design has no
    server-side revocation list or password-version claim, and adding one would
    require a schema/infra change.
    """
    current = req.current_password or ""
    new = req.new_password or ""
    confirm = req.confirm_password or ""

    if new != confirm:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "New passwords do not match.",
        )
    if new == current:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "New password must differ from current password.",
        )
    validate_password_strength(new)

    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE id = ?",
            (user["id"],),
        ).fetchone()
        if row is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
        if not verify_password(current, row["password_hash"]):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Incorrect current password.",
            )
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(new), user["id"]),
        )

    return ChangePasswordResponse(message="Password changed successfully.")


@router.post("/change-password", response_model=ChangePasswordResponse)
def change_password(req: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    """Change the signed-in user's password (admin and student)."""
    return _change_password(req, user)


@router.post("/password/change", response_model=ChangePasswordResponse)
def change_password_alias(req: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    """Alias kept for the original stub path."""
    return _change_password(req, user)
