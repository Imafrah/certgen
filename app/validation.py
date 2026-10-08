"""Per-recipient validation.

Done by hand (not via the request schema) so that ONE bad recipient is
reported as a failed item instead of rejecting the entire request.
"""
import re
from typing import Any

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_NAME = 100
MAX_COURSE = 150


def validate_recipient(raw: Any) -> tuple[dict | None, str | None]:
    """Return (clean_data, None) if valid, else (None, error_message)."""
    if not isinstance(raw, dict):
        return None, "recipient must be an object"

    errors = []

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("name is required")
        name = None
    else:
        name = " ".join(name.split())
        if len(name) > MAX_NAME:
            errors.append(f"name must be at most {MAX_NAME} characters")

    email = raw.get("email")
    if not isinstance(email, str) or not EMAIL_RE.match(email.strip()):
        errors.append("a valid email is required")
        email = None
    else:
        email = email.strip().lower()

    course = raw.get("course")
    if course is not None:
        if not isinstance(course, str):
            errors.append("course must be a string")
        elif len(course.strip()) > MAX_COURSE:
            errors.append(f"course must be at most {MAX_COURSE} characters")
        else:
            course = course.strip() or None

    if errors:
        return None, "; ".join(errors)
    return {"name": name, "email": email, "course": course}, None
