"""Password reset.

How it stays safe:
  * Asking for a reset always gives the same answer, so the form cannot reveal who has an account.
  * The link holds a random 256-bit token. Only its SHA-256 hash is stored, so a copy of the database
    cannot be used to reset anyone's password.
  * A token works once, expires after 30 minutes, and asking again replaces the older link.
  * Choosing a new password also signs out every older session of that customer.
  * Nothing is emailed unless an email service has been connected. Until then the page says so plainly
    and never claims a message was sent.
"""

from __future__ import annotations

import hashlib
import secrets
import time

import bcrypt
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from .. import auth, db, mailer, ratelimit
from ..emails import clean_email

router = APIRouter()

TTL_SECONDS = 30 * 60
MIN_PASSWORD = 6


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


async def body_of(request: Request) -> dict:
    try:
        b = await request.json()
    except Exception:
        return {}
    return b if isinstance(b, dict) else {}


@router.get("/api/auth/reset/status")
async def reset_status():
    """Lets the page tell the customer the truth about whether a link can be emailed."""
    return {"emailAvailable": mailer.configured()}


@router.post("/api/auth/forgot")
async def forgot(request: Request):
    ratelimit.limit(request, "forgot", 5, 600)
    email = clean_email((await body_of(request)).get("email"))
    if not mailer.configured():
        # Be honest: nothing can be sent yet. This does not reveal whether the account exists.
        return err(
            503,
            "Password reset by email is not switched on yet. Please contact the store and we will help you get back in.",
        )
    if email and await db.get_user_by_email(email):
        token = secrets.token_urlsafe(32)
        await db.add_reset_token(hash_token(token), email, time.time() + TTL_SECONDS)
        await mailer.send_reset(email, token)
    return {
        "ok": True,
        "message": "If that email has an account, we have sent a link to reset the password. It works for 30 minutes.",
    }


@router.get("/api/auth/reset/check")
async def reset_check(token: str = ""):
    ok = (
        bool(token)
        and len(token) < 200
        and await db.peek_reset_token(hash_token(token), time.time())
    )
    return {"valid": ok}


@router.post("/api/auth/reset")
async def reset(request: Request):
    ratelimit.limit(request, "reset", 10, 600)
    b = await body_of(request)
    token = b.get("token") if isinstance(b.get("token"), str) else ""
    new = b.get("password") if isinstance(b.get("password"), str) else ""
    if len(new) < MIN_PASSWORD:
        return err(400, f"The new password should be at least {MIN_PASSWORD} characters.")
    if len(new) > 200:
        return err(400, "That password is too long.")
    if not token or len(token) > 200:
        return err(400, "This reset link is not valid or has expired. Please ask for a new one.")
    email = await db.use_reset_token(hash_token(token), time.time())  # one use, then gone
    user = await db.get_user_by_email(email) if email else None
    if not user:
        return err(400, "This reset link is not valid or has expired. Please ask for a new one.")
    new_hash = await run_in_threadpool(
        lambda: bcrypt.hashpw(new.encode(), bcrypt.gensalt(10)).decode()
    )
    await db.save_user({**user, "passHash": new_hash})
    # Sessions issued before this second stop working; one signed in from now on is fine.
    # The same value is kept in memory and in the database so they can never disagree.
    cutoff = int(time.time())
    auth.revoke_sessions_before(user["email"], cutoff)
    cutoffs = await db.get_setting("session_cutoffs", {}) or {}
    cutoffs[user["email"]] = cutoff
    await db.set_setting("session_cutoffs", cutoffs)
    await db.add_audit("customer", "password_reset", user["email"], {})
    return {"ok": True, "message": "Your password has been changed. Please sign in with it."}
