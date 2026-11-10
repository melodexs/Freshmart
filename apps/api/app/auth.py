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


def current_user(request: Request) -> dict | None:
    """Return the session payload, or None. Never raises."""
    token = request.cookies.get(config.COOKIE_NAME)
    if not token:
        return None
    try:
        return jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


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


def sign_staff_token() -> str:
    now = int(time.time())
    return jwt.encode(
        {"role": "staff", "iat": now, "exp": now + STAFF_TTL_SECONDS},
        config.JWT_SECRET,
        algorithm="HS256",
    )


def set_staff_cookie(response: Response) -> None:
    response.set_cookie(
        STAFF_COOKIE,
        sign_staff_token(),
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


def require_staff(request: Request) -> None:
    """Protects the store's order feed (customer addresses and phones).

    Accepts a staff session cookie (from POST /api/store/login) or the
    X-Staff-Key header. Disabled in production if STORE_STAFF_KEY is unset.
    """
    if not staff_enabled():
        raise HTTPException(status_code=403, detail="Store feed is disabled.")
    if not is_staff(request):
        raise HTTPException(status_code=401, detail="Staff access required.")
