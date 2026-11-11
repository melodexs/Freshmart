"""Nigerian phone number handling.

Accepts the ways people actually type a number (0801 234 5678, +234 801 234 5678,
2348012345678, 801-234-5678) and returns the local 11-digit form 080XXXXXXXX.
"""

from __future__ import annotations

import re

# Mobile prefixes after the leading 0: 70x, 80x, 81x, 90x, 91x.
_MOBILE = re.compile(r"^0(70|80|81|90|91)\d{8}$")


def normalise(raw: str) -> str | None:
    """Return the 11-digit local number, or None if it is not a valid Nigerian mobile."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if digits.startswith("234") and len(digits) == 13:
        digits = "0" + digits[3:]
    elif len(digits) == 10 and not digits.startswith("0"):
        digits = "0" + digits
    return digits if _MOBILE.match(digits) else None
