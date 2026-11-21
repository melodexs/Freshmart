"""Discount codes: the rules, kept pure so they can be tested without a database.

A code takes money off the items total only, never the delivery fee, and can never take more than
the items cost. Every limit is checked on the server at the moment the order is placed.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

CODE_RE = re.compile(r"[A-Z0-9_-]{3,24}")
MAX_PERCENT = 90
MAX_FIXED = 1_000_000


def normalise(raw) -> str:
    return re.sub(r"\s+", "", str(raw or "")).upper()


def _parse(ts) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def validate_definition(b: dict) -> tuple[dict | None, str | None]:
    """Clean what the admin typed. Returns (code_record, problem)."""
    code = normalise(b.get("code"))
    if not CODE_RE.fullmatch(code):
        return None, "The code must be 3 to 24 letters, numbers, - or _."
    kind = b.get("kind")
    if kind not in ("percent", "fixed"):
        return None, "Choose whether the code takes off a percentage or a fixed amount."
    value = b.get("value")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return None, "Enter the discount as a whole number greater than zero."
    if kind == "percent" and value > MAX_PERCENT:
        return None, f"A percentage discount can be at most {MAX_PERCENT}%."
    if kind == "fixed" and value > MAX_FIXED:
        return None, "That fixed amount is too large."

    def opt_int(key, low, high, label):
        v = b.get(key)
        if v in (None, "", 0):
            return None, None
        if not isinstance(v, int) or isinstance(v, bool) or not low <= v <= high:
            return None, f"{label} must be a whole number."
        return v, None

    min_order, p = opt_int("minOrder", 1, 100_000_000, "The minimum order")
    if p:
        return None, p
    max_discount, p = opt_int("maxDiscount", 1, 100_000_000, "The maximum discount")
    if p:
        return None, p
    max_uses, p = opt_int("maxUses", 1, 10_000_000, "The total use limit")
    if p:
        return None, p
    starts, ends = b.get("startsAt") or None, b.get("endsAt") or None
    s, e = _parse(starts), _parse(ends)
    if (starts and s is None) or (ends and e is None):
        return None, "Those dates are not valid."
    if s and e and e <= s:
        return None, "The end date must be after the start date."
    return {
        "code": code,
        "kind": kind,
        "value": value,
        "minOrder": min_order,
        "maxDiscount": max_discount,
        "maxUses": max_uses,
        "perCustomerOnce": bool(b.get("perCustomerOnce", True)),
        "startsAt": starts,
        "endsAt": ends,
        "active": bool(b.get("active", True)),
        "note": " ".join(str(b.get("note") or "").split())[:120],
    }, None


def amount_off(rule: dict, subtotal: int) -> int:
    """Naira taken off a given items total. Never negative, never more than the items cost."""
    if rule["kind"] == "percent":
        off = subtotal * rule["value"] // 100
    else:
        off = rule["value"]
    if rule.get("maxDiscount"):
        off = min(off, rule["maxDiscount"])
    return max(0, min(off, subtotal))


def check(
    rule: dict | None,
    subtotal: int,
    used_total: int,
    used_by_customer: bool,
    now: datetime | None = None,
) -> tuple[int, str | None]:
    """Return (naira_off, None) when the code applies, or (0, reason it does not)."""
    now = now or datetime.now(UTC)
    if not rule or not rule.get("active"):
        return 0, "That code is not valid."
    s, e = _parse(rule.get("startsAt")), _parse(rule.get("endsAt"))
    if s and now < s:
        return 0, "That code is not active yet."
    if e and now >= e:
        return 0, "That code has expired."
    if rule.get("maxUses") and used_total >= rule["maxUses"]:
        return 0, "That code has been fully used."
    if rule.get("perCustomerOnce") and used_by_customer:
        return 0, "You have already used that code."
    if rule.get("minOrder") and subtotal < rule["minOrder"]:
        return 0, f"This code needs an order of at least ₦{rule['minOrder']:,}."
    off = amount_off(rule, subtotal)
    if off <= 0:
        return 0, "That code does not apply to this order."
    return off, None
