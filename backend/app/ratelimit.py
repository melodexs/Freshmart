"""Tiny in-memory sliding-window limiter for auth endpoints."""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_hits: dict[str, deque] = defaultdict(deque)


def limit(request: Request, bucket: str, max_hits: int, window_s: int) -> None:
    ip = request.client.host if request.client else "unknown"
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        ip = fwd.split(",")[0].strip()
    key = f"{bucket}:{ip}"
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > window_s:
        q.popleft()
    if len(q) >= max_hits:
        raise HTTPException(status_code=429, detail="Too many attempts. Please wait a minute and try again.")
    q.append(now)


def reset() -> None:
    _hits.clear()
