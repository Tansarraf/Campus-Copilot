"""Validation helpers for student identity fields (enrollment numbers, etc.)."""
import re

ENROLLMENT_NUMBER_PATTERN = re.compile(r"^\d{11}$")


def is_valid_enrollment_number(value: str | None) -> bool:
    """Enrollment numbers are digit strings of length 11 (preserve leading zeros)."""
    if value is None:
        return False
    return bool(ENROLLMENT_NUMBER_PATTERN.fullmatch(str(value).strip()))


def normalize_enrollment_number(value: str) -> str:
    normalized = str(value).strip()
    if not is_valid_enrollment_number(normalized):
        raise ValueError("Enrollment number must be exactly 11 digits")
    return normalized
