"""Outgoing email. Not connected yet, and honest about it.

No email provider has been given to the store, so `configured()` is False and nothing is ever sent or
reported as sent. To switch it on, set RESEND_API_KEY, EMAIL_FROM (a sender on a domain verified with
the provider) and PUBLIC_URL (the shop's own address, for example https://freshmart-melodexs.onrender.com).

PUBLIC_URL is used for every link in an email. It is never taken from the request, because a forged
Host header could otherwise point a reset link at an attacker's website.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from fastapi.concurrency import run_in_threadpool


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def public_url() -> str:
    u = _env("PUBLIC_URL").rstrip("/")
    return u if u.startswith("https://") else ""


def configured() -> bool:
    return bool(_env("RESEND_API_KEY") and _env("EMAIL_FROM") and public_url())


def _post(payload: dict) -> bool:
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {_env('RESEND_API_KEY')}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:  # noqa: S310 - fixed https URL
            return 200 <= r.status < 300
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


async def send_reset(email: str, token: str) -> bool:
    """Send the reset link. True only if the provider accepted the message."""
    if not configured():
        return False
    link = f"{public_url()}/reset-password?token={token}"
    return await run_in_threadpool(
        _post,
        {
            "from": _env("EMAIL_FROM"),
            "to": [email],
            "subject": "Reset your OGS password",
            "text": f"Use this link within 30 minutes to choose a new password:\n\n{link}\n\nIf you did not ask for this, ignore this email and your password stays the same.",
        },
    )
