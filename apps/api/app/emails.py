"""Email address checking shared by the newsletter and password reset."""

from __future__ import annotations

import re

# One local part, one @, a dotted domain. No spaces, quotes or angle brackets, so an address can
# never smuggle markup or a header break into a page, a CSV cell or a future email.
_EMAIL = re.compile(
    r"^[a-z0-9._%+\-]{1,64}@[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?)+$"
)
MAX_LEN = 254


def clean_email(v) -> str | None:
    """The lower-cased address if it is plausible, else None."""
    if not isinstance(v, str):
        return None
    e = v.strip().lower()
    if not e or len(e) > MAX_LEN or ".." in e:
        return None
    if not _EMAIL.match(e):
        return None
    local = e.split("@", 1)[0]
    if local.startswith(".") or local.endswith("."):
        return None
    return e
