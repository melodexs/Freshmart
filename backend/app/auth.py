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


def require_staff(request: Request) -> None:
    """Protects the store's order feed with a shared staff key.

    Send it as the `X-Staff-Key` header. Disabled entirely when
    STORE_STAFF_KEY is not configured and we are in production.
    """
    key = config.STORE_STAFF_KEY
    if not key:
        if config.IS_PRODUCTION:
            raise HTTPException(status_code=403, detail="Store feed is disabled.")
        return  # open in local development only
    supplied = request.headers.get("x-staff-key", "")
    if not hmac.compare_digest(supplied.encode(), key.encode()):
        raise HTTPException(status_code=401, detail="Staff access required.")
