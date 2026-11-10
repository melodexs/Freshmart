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
EMPTY = {"users": {}, "orders": [], "storeSms": []}


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
