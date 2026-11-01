"""
Minimal JWT-based auth with two roles: 'student' and 'admin'.
Kept intentionally simple (no refresh tokens, no OAuth) since the goal is a
correctly-separated role boundary, not a production auth system.

Identity for authorization is always taken from the validated JWT `sub`
(user id) and re-loaded from the database — never from client-supplied
enrollment numbers or role fields.
"""
import re
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext

from app import config
from app.database import get_conn

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


MIN_PASSWORD_LENGTH = 8
_PASSWORD_HAS_LETTER = re.compile(r"[A-Za-z]")
_PASSWORD_HAS_DIGIT = re.compile(r"\d")


def validate_password_strength(password: str) -> None:
    """Raise HTTP 400 with a safe message if the password is too weak."""
    if password is None or not isinstance(password, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password does not meet requirements.",
        )
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
        )
    if not _PASSWORD_HAS_LETTER.search(password) or not _PASSWORD_HAS_DIGIT.search(password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must include at least one letter and one number.",
        )


def display_name(user: dict) -> str:
    first = (user.get("first_name") or "").strip()
    last = (user.get("last_name") or "").strip()
    joined = f"{first} {last}".strip()
    if joined:
        return joined
    return (user.get("full_name") or user.get("username") or "").strip()


def create_access_token(user: dict) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=config.JWT_EXPIRE_MINUTES)
    payload = {
        "sub": str(user["id"]),
        "username": user.get("username"),
        "role": user["role"],
        "full_name": display_name(user),
        "exp": expire,
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


def _ensure_active(user: dict) -> dict:
    status_value = user.get("account_status") or "active"
    if status_value == "disabled":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")
    if status_value == "pending_activation":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is pending activation",
        )
    return user


def get_current_user(creds: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    payload = decode_token(creds.credentials)
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (payload["sub"],)).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")
    return _ensure_active(dict(row))


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


def require_student(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "student":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Student access required")
    return user


def fetch_student_profile(user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM student_profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def _present(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


# Required for student profile_complete (email_verified is NOT required here;
# verification is only required before trusting email for password recovery).
STUDENT_REQUIRED_FIELDS = (
    "first_name",
    "last_name",
    "enrollment_number",
    "course",
    "academic_year",
    "current_semester",
    "email",
)

# Fields students may ever set via PATCH /auth/me (further gated if already filled).
STUDENT_EDITABLE_CANDIDATES = (
    "email",
    "first_name",
    "last_name",
    "academic_year",
    "current_semester",
)


def compute_missing_fields(payload: dict) -> list[str]:
    if payload.get("role") != "student":
        return []
    missing = []
    for field in STUDENT_REQUIRED_FIELDS:
        if not _present(payload.get(field)):
            missing.append(field)
    return missing


def compute_editable_fields(user: dict, profile: dict | None) -> list[str]:
    """Allowlist of fields the student may supply right now (fill-once / email)."""
    if user.get("role") != "student":
        return []
    editable = ["email"]  # email may be updated; change resets verification
    if not _present(user.get("first_name")):
        editable.append("first_name")
    if not _present(user.get("last_name")):
        editable.append("last_name")
    if profile is None or not _present(profile.get("academic_year")):
        editable.append("academic_year")
    if profile is None or profile.get("current_semester") is None:
        editable.append("current_semester")
    return editable


def build_profile_payload(user: dict) -> dict:
    """Authoritative profile for greetings / profile page (from token identity)."""
    profile = fetch_student_profile(user["id"]) if user.get("role") == "student" else None
    payload = {
        "id": user["id"],
        "username": user.get("username"),
        "role": user["role"],
        "full_name": display_name(user),
        "first_name": user.get("first_name"),
        "last_name": user.get("last_name"),
        "email": user.get("email"),
        "email_verified": bool(user.get("email_verified")),
        "account_status": user.get("account_status") or "active",
        "department": user.get("department"),
        "enrollment_number": profile.get("enrollment_number") if profile else None,
        "course": profile.get("course") if profile else None,
        "academic_year": profile.get("academic_year") if profile else None,
        "current_semester": profile.get("current_semester") if profile else None,
        "is_demo": bool(profile.get("is_demo")) if profile else False,
    }
    if user.get("role") == "student":
        missing = compute_missing_fields(payload)
        payload["missing_fields"] = missing
        payload["profile_complete"] = len(missing) == 0
        payload["editable_fields"] = compute_editable_fields(user, profile)
        payload["required_fields"] = list(STUDENT_REQUIRED_FIELDS)
    else:
        payload["missing_fields"] = []
        payload["profile_complete"] = True
        payload["editable_fields"] = []
        payload["required_fields"] = []
    return payload
