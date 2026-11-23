"""JWT cookie helpers and auth dependencies."""

from __future__ import annotations

import hmac
import time

import jwt
from fastapi import HTTPException, Request, Response

from . import config


def sign_token(user: dict) -> str:
    now = int(time.time())
    payload = {
        "email": user["email"],
        "name": user["name"],
        "iat": now,
        "exp": now + config.TOKEN_TTL_SECONDS,
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        config.COOKIE_NAME,
        token,
        max_age=config.TOKEN_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=config.COOKIE_SECURE,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(config.COOKIE_NAME, path="/")


# Sessions issued before a user's last password reset are dead. Only users who have reset appear here,
# so the check on each request is a single dictionary lookup, with no database call.
_revoked_before: dict[str, int] = {}


def revoke_sessions_before(email: str, when: int) -> None:
    """Called after a reset: any session issued before `when` stops working immediately."""
    _revoked_before[email] = when


def current_user(request: Request) -> dict | None:
    """Return the session payload, or None. Never raises."""
    token = request.cookies.get(config.COOKIE_NAME)
    if not token:
        return None
    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    cutoff = _revoked_before.get(payload.get("email", ""))
    if cutoff and int(payload.get("iat", 0)) < cutoff:
        return None
    return payload


def require_auth(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Please sign in to continue.")
    return user


STAFF_COOKIE = "fm_staff"
STAFF_TTL_SECONDS = 12 * 60 * 60


def staff_enabled() -> bool:
    """Staff access is on when a key is set, or in local dev (open)."""
    return bool(config.STORE_STAFF_KEY) or not config.IS_PRODUCTION


def check_staff_key(supplied: str) -> bool:
    key = config.STORE_STAFF_KEY
    if not key:
        return not config.IS_PRODUCTION
    return hmac.compare_digest(supplied.encode(), key.encode())


def sign_staff_token(admin: dict | None = None) -> str:
    """A staff session. With no admin it is the shared-key session (level 'staff', no name)."""
    now = int(time.time())
    claims = {"role": "staff", "iat": now, "exp": now + STAFF_TTL_SECONDS}
    if admin:
        claims.update({"level": admin["role"], "email": admin["email"], "name": admin["name"]})
    return jwt.encode(claims, config.JWT_SECRET, algorithm="HS256")


def set_staff_cookie(response: Response, admin: dict | None = None) -> None:
    response.set_cookie(
        STAFF_COOKIE,
        sign_staff_token(admin),
        max_age=STAFF_TTL_SECONDS,
        httponly=True,
        samesite="strict",
        secure=config.COOKIE_SECURE,
        path="/api/store",
    )


def clear_staff_cookie(response: Response) -> None:
    response.delete_cookie(STAFF_COOKIE, path="/api/store")


def is_staff(request: Request) -> bool:
    if not config.STORE_STAFF_KEY and not config.IS_PRODUCTION:
        return True  # open in local development only
    # Header still works for scripts/curl.
    if check_staff_key(request.headers.get("x-staff-key", "")) and config.STORE_STAFF_KEY:
        return True
    token = request.cookies.get(STAFF_COOKIE)
    if not token:
        return False
    try:
        return jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"]).get("role") == "staff"
    except jwt.PyJWTError:
        return False


def staff_identity(request: Request) -> dict:
    """Who is acting: {'name', 'email', 'level'}. The shared key has no person behind it."""
    if check_staff_key(request.headers.get("x-staff-key", "")) and config.STORE_STAFF_KEY:
        return {"name": "Shared staff key", "email": "", "level": "staff"}
    token = request.cookies.get(STAFF_COOKIE)
    if token:
        try:
            c = jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
        except jwt.PyJWTError:
            c = {}
        if c.get("role") == "staff":
            return {
                "name": c.get("name") or "Shared staff key",
                "email": c.get("email", ""),
                "level": c.get("level", "staff"),
            }
    if not config.STORE_STAFF_KEY and not config.IS_PRODUCTION:
        return {"name": "Local development", "email": "", "level": "owner"}
    return {"name": "Shared staff key", "email": "", "level": "staff"}


def actor_name(request: Request) -> str:
    """The name to put in the audit log for whoever is acting."""
    return staff_identity(request)["name"]


async def require_owner(request: Request) -> dict:
    """Only a named owner account may pass (never the shared key)."""
    await require_active_staff(request)
    who = staff_identity(request)
    if who["level"] != "owner":
        raise HTTPException(status_code=403, detail="Only the store owner can do that.")
    return who


def require_staff(request: Request) -> None:
    """Protects the store's order feed (customer addresses and phones).

    Accepts a staff session cookie (from POST /api/store/login) or the
    X-Staff-Key header. Disabled in production if STORE_STAFF_KEY is unset.
    """
    if not staff_enabled():
        raise HTTPException(status_code=403, detail="Store feed is disabled.")
    if not is_staff(request):
        raise HTTPException(status_code=401, detail="Staff access required.")


async def require_active_staff(request: Request) -> None:
    """Like require_staff, and for a named admin also checks, on every request, that the account
    is still active and has chosen its own password.

    Until then the session can do nothing except change the password or ask who it is, so the
    first password (which someone else set) cannot be used to run the store.
    """
    require_staff(request)
    who = staff_identity(request)
    if not who["email"]:
        return  # the shared staff key has no account to check
    from . import db

    a = await db.get_admin(who["email"])
    if not a or not a["active"]:
        raise HTTPException(status_code=401, detail="Staff access required.")
    if a["mustChange"]:
        raise HTTPException(status_code=403, detail="Choose your own password first.")


async def staff_allowed(request: Request) -> bool:
    """True when this request may act as staff right now (the yes/no form of require_active_staff)."""
    if not staff_enabled() or not is_staff(request):
        return False
    who = staff_identity(request)
    if not who["email"]:
        return True
    from . import db

    a = await db.get_admin(who["email"])
    return bool(a and a["active"] and not a["mustChange"])
