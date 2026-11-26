"""Flat JSON file store for local development (zero setup).

Writes are guarded by a lock and are atomic (temp file + rename), which fixes
the concurrent-write weakness of the original Node version for single-process use.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from . import config

_lock = threading.Lock()
EMPTY = {
    "users": {},
    "orders": [],
    "storeSms": [],
    "products": {},
    "settings": {},
    "audit": [],
    "favourites": {},
    "reviews": [],
    "subscribers": [],
    "reset_tokens": [],
    "addresses": {},
    "images": {},
    "stockMoves": [],
    "discounts": {},
    "discountUses": [],
    "admins": {},
}


def _path() -> Path:
    return config.DATA_FILE


def _read() -> dict:
    try:
        data = json.loads(_path().read_text("utf8"))
    except (OSError, ValueError):
        return json.loads(json.dumps(EMPTY))
    for k, v in EMPTY.items():
        data.setdefault(k, json.loads(json.dumps(v)))
    return data


def _write(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf8")
    os.replace(tmp, p)


async def init() -> None:
    return None


async def get_user_by_email(email: str):
    with _lock:
        return _read()["users"].get(email)


async def save_user(user: dict) -> None:
    with _lock:
        data = _read()
        data["users"][user["email"]] = user
        _write(data)


async def create_user(user: dict) -> bool:
    """Insert only if the email is free. Returns False if it already exists."""
    with _lock:
        data = _read()
        if user["email"] in data["users"]:
            return False
        data["users"][user["email"]] = user
        _write(data)
        return True


async def get_orders_for_user(email: str):
    with _lock:
        return [o for o in _read()["orders"] if o.get("user") == email]


async def add_order(order: dict) -> None:
    with _lock:
        data = _read()
        data["orders"].insert(0, order)
        _write(data)


async def get_store_sms():
    with _lock:
        return _read()["storeSms"]


async def add_store_sms(entry: dict) -> None:
    with _lock:
        data = _read()
        data["storeSms"].insert(0, entry)
        _write(data)


async def get_order(order_id: str):
    with _lock:
        return next((o for o in _read()["orders"] if o["id"] == order_id), None)


async def get_all_orders():
    with _lock:
        return list(_read()["orders"])


async def update_order_status(
    order_id: str, new_status: str, allowed_from: list[str] | None = None
) -> bool:
    """Set the status. If allowed_from is given, only change it when the current
    status is one of those (so two staff clicks cannot race into a bad state)."""
    with _lock:
        data = _read()
        for o in data["orders"]:
            if o["id"] == order_id:
                if allowed_from is not None and o["status"] not in allowed_from:
                    return False
                o["status"] = new_status
                _write(data)
                return True
        return False


async def ping() -> None:
    """Liveness check for the JSON file store (local development).

    This store treats a missing or corrupt file as empty and keeps going, so there is
    nothing meaningful to fail here. The real check is the Postgres one, which runs a
    query and raises when the database is unreachable.
    """
    return None


# ---------- catalogue ----------


def _sorted(products) -> list[dict]:
    return sorted(products, key=lambda p: (p.get("sort", 0), p["name"]))


async def list_products(include_inactive: bool = False) -> list[dict]:
    with _lock:
        items = list(_read()["products"].values())
    return _sorted(p for p in items if include_inactive or p.get("active", True))


async def get_product(product_id: str) -> dict | None:
    with _lock:
        return _read()["products"].get(product_id)


async def save_product(p: dict) -> None:
    with _lock:
        data = _read()
        data["products"][p["id"]] = {
            "id": p["id"],
            "name": p["name"],
            "cat": p["cat"],
            "sub": p.get("sub", ""),
            "brand": p.get("brand", ""),
            "emoji": p.get("emoji", ""),
            "description": p.get("description", ""),
            "image": p.get("image", ""),
            "options": p["options"],
            "comparePrices": p.get("comparePrices") or [],
            "stock": p.get("stock"),
            "active": bool(p.get("active", True)),
            "featured": bool(p.get("featured", False)),
            "sort": int(p.get("sort", 0)),
        }
        _write(data)


async def delete_product(product_id: str) -> bool:
    with _lock:
        data = _read()
        if product_id not in data["products"]:
            return False
        del data["products"][product_id]
        _write(data)
        return True


async def count_products() -> int:
    with _lock:
        return len(_read()["products"])


async def adjust_stock(product_id: str, delta: int) -> int | None:
    with _lock:
        data = _read()
        p = data["products"].get(product_id)
        if p is None or p.get("stock") is None:
            return None
        p["stock"] = max(p["stock"] + delta, 0)
        _write(data)
        return p["stock"]


async def get_setting(key: str, default=None):
    with _lock:
        return _read()["settings"].get(key, default)


async def set_setting(key: str, value) -> None:
    with _lock:
        data = _read()
        data["settings"][key] = value
        _write(data)


async def reserve_stock(product_id: str, qty: int) -> bool:
    with _lock:
        data = _read()
        p = data["products"].get(product_id)
        if p is None:
            return False
        if p.get("stock") is None:
            return True
        if p["stock"] < qty:
            return False
        p["stock"] -= qty
        _write(data)
        return True


async def add_audit(actor: str, action: str, subject: str, detail: dict) -> None:
    from datetime import UTC, datetime

    with _lock:
        data = _read()
        data["audit"].insert(
            0,
            {
                "at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "actor": actor,
                "action": action,
                "subject": subject,
                "detail": detail,
            },
        )
        _write(data)


async def get_audit(subject: str | None = None, limit: int = 100) -> list[dict]:
    with _lock:
        rows = _read()["audit"]
    if subject:
        rows = [r for r in rows if r["subject"] == subject]
    return rows[:limit]


async def confirm_payment(order_id: str, expected_from: str, new_status: str, record: dict) -> bool:
    with _lock:
        data = _read()
        for o in data["orders"]:
            if o["id"] == order_id:
                if o["status"] != expected_from:
                    return False
                o["status"] = new_status
                o["paymentDetail"] = {**(o.get("paymentDetail") or {}), **record}
                _write(data)
                return True
        return False


async def merge_payment_detail(
    order_id: str, patch: dict, only_if_absent: str | None = None
) -> bool:
    """JSON-store twin of the Postgres merge. Same contract, same one-shot guarantee."""
    with _lock:
        data = _read()
        for o in data["orders"]:
            if o["id"] != order_id:
                continue
            detail = dict(o.get("paymentDetail") or {})
            if only_if_absent and only_if_absent in detail:
                return False
            detail.update(patch)
            o["paymentDetail"] = detail
            _write(data)
            return True
        return False


async def get_order_by_payment_reference(reference: str):
    """Current attempt first, then every earlier one: a late payment must still find its order."""
    with _lock:
        for o in _read()["orders"]:
            attempt = (o.get("paymentDetail") or {}).get("monnify") or {}
            if attempt.get("paymentReference") == reference:
                return o
            for entry in attempt.get("history") or []:
                if isinstance(entry, dict) and entry.get("paymentReference") == reference:
                    return o
        return None


async def drop_payment_detail_keys(order_id: str, keys: list[str]) -> bool:
    """JSON-store twin of the Postgres key removal (the attempt lock uses this)."""
    if not keys:
        return False
    with _lock:
        data = _read()
        for o in data["orders"]:
            if o["id"] != order_id:
                continue
            detail = dict(o.get("paymentDetail") or {})
            for key in keys:
                detail.pop(key, None)
            o["paymentDetail"] = detail
            _write(data)
            return True
        return False


async def mark_paid_verified(
    order_id: str, expected_from: str, new_status: str, record: dict
) -> bool:
    """Move an order to paid only if it is still awaiting payment."""
    with _lock:
        data = _read()
        for o in data["orders"]:
            if o["id"] != order_id:
                continue
            if o["status"] != expected_from:
                return False
            o["status"] = new_status
            o["paymentDetail"] = {**(o.get("paymentDetail") or {}), **record}
            _write(data)
            return True
        return False


async def get_favourites(email: str) -> list[str]:
    with _lock:
        return list(_read()["favourites"].get(email, []))


async def add_favourite(email: str, product_id: str) -> None:
    with _lock:
        data = _read()
        favs = data["favourites"].setdefault(email, [])
        if product_id not in favs:
            favs.insert(0, product_id)
            _write(data)


async def remove_favourite(email: str, product_id: str) -> None:
    with _lock:
        data = _read()
        favs = data["favourites"].get(email, [])
        if product_id in favs:
            favs.remove(product_id)
            _write(data)


async def popularity() -> dict[str, int]:
    with _lock:
        orders = list(_read()["orders"])
    out: dict[str, int] = {}
    for o in orders:
        if o["status"] == "Cancelled":
            continue
        for i in o["items"]:
            if i.get("productId"):
                out[i["productId"]] = out.get(i["productId"], 0) + int(i.get("qty", 0))
    return out


async def list_addresses(email: str) -> list[dict]:
    with _lock:
        rows = list(_read()["addresses"].get(email, []))
    return sorted(rows, key=lambda a: not a["isDefault"])


async def save_address(email: str, a: dict) -> None:
    with _lock:
        data = _read()
        rows = data["addresses"].setdefault(email, [])
        if a["isDefault"]:
            for r in rows:
                r["isDefault"] = False
        for i, r in enumerate(rows):
            if r["id"] == a["id"]:
                rows[i] = a
                break
        else:
            rows.append(a)
        _write(data)


async def delete_address(email: str, address_id: str) -> bool:
    with _lock:
        data = _read()
        rows = data["addresses"].get(email, [])
        kept = [r for r in rows if r["id"] != address_id]
        if len(kept) == len(rows):
            return False
        data["addresses"][email] = kept
        _write(data)
        return True


async def update_profile(email: str, name: str, phone: str) -> None:
    with _lock:
        data = _read()
        u = data["users"].get(email)
        if u:
            u["name"], u["phone"] = name, phone
            _write(data)


async def save_image(image_id: str, data: bytes) -> None:
    import base64

    with _lock:
        d = _read()
        d["images"][image_id] = base64.b64encode(data).decode()
        _write(d)


async def get_image(image_id: str) -> bytes | None:
    import base64

    with _lock:
        raw = _read()["images"].get(image_id)
    return base64.b64decode(raw) if raw else None


async def get_discount(code: str) -> dict | None:
    with _lock:
        return _read()["discounts"].get(code)


async def list_discounts() -> list[dict]:
    with _lock:
        d = _read()
    out = []
    for rule in d["discounts"].values():
        uses = [u for u in d["discountUses"] if u["code"] == rule["code"]]
        out.append({**rule, "used": len(uses), "given": sum(u["amount"] for u in uses)})
    return out


async def save_discount(rule: dict) -> None:
    with _lock:
        d = _read()
        d["discounts"][rule["code"]] = rule
        _write(d)


async def discount_usage(code: str, email: str) -> tuple[int, bool]:
    with _lock:
        uses = [u for u in _read()["discountUses"] if u["code"] == code]
    return len(uses), any(u["email"] == email for u in uses)


async def claim_discount(rule: dict, email: str, order_id: str, amount: int) -> bool:
    with _lock:
        d = _read()
        uses = [u for u in d["discountUses"] if u["code"] == rule["code"]]
        if rule.get("maxUses") and len(uses) >= rule["maxUses"]:
            return False
        if rule.get("perCustomerOnce") and any(u["email"] == email for u in uses):
            return False
        d["discountUses"].append(
            {"code": rule["code"], "email": email, "orderId": order_id, "amount": amount}
        )
        _write(d)
        return True


async def release_discount(order_id: str) -> None:
    with _lock:
        d = _read()
        d["discountUses"] = [u for u in d["discountUses"] if u["orderId"] != order_id]
        _write(d)


async def add_stock_move(m: dict) -> None:
    from datetime import UTC, datetime

    with _lock:
        d = _read()
        d["stockMoves"].insert(0, {**m, "at": datetime.now(UTC).isoformat().replace("+00:00", "Z")})
        _write(d)


async def list_stock_moves(product_id: str | None, limit: int) -> list[dict]:
    with _lock:
        d = _read()
    names = {k: v.get("name", k) for k, v in d["products"].items()}
    rows = [m for m in d["stockMoves"] if product_id is None or m["productId"] == product_id]
    return [{**m, "name": names.get(m["productId"], m["productId"])} for m in rows[:limit]]


# ---- product reviews (a review is one row per customer per product) ----
async def save_review(r: dict) -> None:
    """Insert or replace this customer's review of this product. Hidden state is kept on edit."""
    with _lock:
        data = _read()
        rows = data["reviews"]
        for i, old in enumerate(rows):
            if old["email"] == r["email"] and old["productId"] == r["productId"]:
                rows[i] = {**r, "created": old["created"], "hidden": old.get("hidden", False)}
                break
        else:
            rows.append({**r, "hidden": False})
        _write(data)


async def list_reviews(product_id: str | None = None, include_hidden: bool = False) -> list[dict]:
    with _lock:
        rows = list(_read()["reviews"])
    rows = [
        r
        for r in rows
        if (product_id is None or r["productId"] == product_id)
        and (include_hidden or not r.get("hidden"))
    ]
    return sorted(rows, key=lambda r: r["updated"], reverse=True)


async def get_review(email: str, product_id: str) -> dict | None:
    with _lock:
        for r in _read()["reviews"]:
            if r["email"] == email and r["productId"] == product_id:
                return dict(r)
    return None


async def set_review_hidden(email: str, product_id: str, hidden: bool) -> bool:
    with _lock:
        data = _read()
        for r in data["reviews"]:
            if r["email"] == email and r["productId"] == product_id:
                r["hidden"] = hidden
                _write(data)
                return True
    return False


# ---- newsletter subscribers (email is the key; unsubscribing keeps the row so a re-subscribe is clean) ----
async def add_subscriber(email: str, at: str) -> bool:
    """True if this is a new subscription (or a re-subscription), False if already subscribed."""
    with _lock:
        data = _read()
        for r in data["subscribers"]:
            if r["email"] == email:
                if r.get("unsubscribed"):
                    r["unsubscribed"] = False
                    r["subscribed"] = at
                    _write(data)
                    return True
                return False
        data["subscribers"].append({"email": email, "subscribed": at, "unsubscribed": False})
        _write(data)
        return True


async def remove_subscriber(email: str) -> bool:
    with _lock:
        data = _read()
        for r in data["subscribers"]:
            if r["email"] == email and not r.get("unsubscribed"):
                r["unsubscribed"] = True
                _write(data)
                return True
    return False


async def list_subscribers(include_unsubscribed: bool = False) -> list[dict]:
    with _lock:
        rows = list(_read()["subscribers"])
    rows = [r for r in rows if include_unsubscribed or not r.get("unsubscribed")]
    return sorted(rows, key=lambda r: r["subscribed"], reverse=True)


# ---- password reset tokens: only the hash of a token is kept, never the token itself ----
async def add_reset_token(token_hash: str, email: str, expires: float) -> None:
    with _lock:
        data = _read()
        # Drop expired rows and any older tokens for this email, so only the newest link works.
        import time as _t

        data["reset_tokens"] = [
            t for t in data["reset_tokens"] if t["expires"] > _t.time() and t["email"] != email
        ]
        data["reset_tokens"].append({"hash": token_hash, "email": email, "expires": expires})
        _write(data)


async def use_reset_token(token_hash: str, now: float) -> str | None:
    """Consume a token: returns its email once, and never again. Expired or unknown gives None."""
    with _lock:
        data = _read()
        found = next((t for t in data["reset_tokens"] if t["hash"] == token_hash), None)
        if not found:
            return None
        data["reset_tokens"].remove(found)
        _write(data)
        return found["email"] if found["expires"] > now else None


async def peek_reset_token(token_hash: str, now: float) -> bool:
    with _lock:
        return any(t["hash"] == token_hash and t["expires"] > now for t in _read()["reset_tokens"])


# ---------- named admin accounts ----------


async def get_admin(email: str):
    with _lock:
        a = _read().get("admins", {}).get(email)
    return dict(a) if a else None


async def list_admins() -> list[dict]:
    with _lock:
        rows = [dict(a) for a in _read().get("admins", {}).values()]
    return sorted(rows, key=lambda a: (a["role"] != "owner", a["created"]))


async def create_admin(a: dict) -> bool:
    """Insert only if the email is free. Returns False if it already exists."""
    from datetime import UTC, datetime

    with _lock:
        data = _read()
        admins = data.setdefault("admins", {})
        if a["email"] in admins:
            return False
        admins[a["email"]] = {
            "email": a["email"],
            "name": a["name"],
            "phone": a["phone"],
            "passHash": a["passHash"],
            "role": a["role"],
            "mustChange": a.get("mustChange", True),
            "active": True,
            "created": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "lastLogin": "",
            "fails": 0,
            "lockedUntil": 0,
            "createdBy": a.get("createdBy", ""),
        }
        _write(data)
        return True


async def update_admin(email: str, **fields) -> None:
    from datetime import UTC, datetime

    with _lock:
        data = _read()
        a = data.setdefault("admins", {}).get(email)
        if a is None:
            return
        for k, v in fields.items():
            a[k] = datetime.now(UTC).isoformat().replace("+00:00", "Z") if k == "lastLogin" else v
        _write(data)
