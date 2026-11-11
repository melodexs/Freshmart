"""Tiny in-memory sliding-window limiter for auth endpoints."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_hits: dict[str, deque] = defaultdict(deque)


_SWEEP_EVERY_S = 60
_last_sweep = 0.0


def _sweep(now: float, window_s: int) -> None:
    """Drop clients whose hits have all expired, so memory cannot grow without bound."""
    global _last_sweep
    if now - _last_sweep < _SWEEP_EVERY_S:
        return
    _last_sweep = now
    for key in [k for k, q in _hits.items() if not q or now - q[-1] > max(window_s, 300)]:
        del _hits[key]


def limit(request: Request, bucket: str, max_hits: int, window_s: int) -> None:
    ip = request.client.host if request.client else "unknown"
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        ip = fwd.split(",")[0].strip()
    key = f"{bucket}:{ip}"
    now = time.monotonic()
    _sweep(now, window_s)
    q = _hits[key]
    while q and now - q[0] > window_s:
        q.popleft()
    if len(q) >= max_hits:
        # Tell well-behaved clients exactly when the oldest hit leaves the window.
        wait = max(1, int(window_s - (now - q[0])) + 1)
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Please wait a minute and try again.",
            headers={"Retry-After": str(wait)},
        )
    q.append(now)


def reset() -> None:
    global _last_sweep
    _hits.clear()
    _last_sweep = 0.0
