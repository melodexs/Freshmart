from __future__ import annotations

import bcrypt
from fastapi import APIRouter, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from .. import auth, db, ratelimit

router = APIRouter()


def err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


async def _body(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _s(v) -> str:
    return v.strip() if isinstance(v, str) else ""


@router.post("/signup")
async def signup(request: Request):
    ratelimit.limit(request, "signup", 10, 60)
    b = await _body(request)
    name, phone = _s(b.get("name")), _s(b.get("phone"))
    email = _s(b.get("email")).lower()
    password = b.get("password") if isinstance(b.get("password"), str) else ""
    confirm = b.get("passwordConfirm")

    if not name or not phone:
        return err(400, "Please add your name and phone number.")
    if not email or not password:
        return err(400, "Please fill in email and password.")
    if len(password) < 6:
        return err(400, "Password should be at least 6 characters.")
    if confirm is not None and password != confirm:
        return err(400, "Passwords don't match. Please re-enter them.")

    pass_hash = await run_in_threadpool(
        lambda: bcrypt.hashpw(password.encode(), bcrypt.gensalt(10)).decode()
    )
    user = {"name": name, "phone": phone, "email": email, "passHash": pass_hash}
    # Atomic insert: no race between "check exists" and "save".
    if not await db.create_user(user):
        return err(409, "An account with that email already exists — try signing in instead.")

    resp = JSONResponse({"name": name, "email": email})
    auth.set_auth_cookie(resp, auth.sign_token(user))
    return resp


@router.post("/login")
async def login(request: Request):
    ratelimit.limit(request, "login", 10, 60)
    b = await _body(request)
    email = _s(b.get("email")).lower()
    password = b.get("password") if isinstance(b.get("password"), str) else ""
    if not email or not password:
        return err(400, "Please fill in email and password.")

    user = await db.get_user_by_email(email)
    bad = err(401, "Email or password is incorrect.")
    if not user:
        return bad
    ok = await run_in_threadpool(
        lambda: bcrypt.checkpw(password.encode(), user["passHash"].encode())
    )
    if not ok:
        return bad

    resp = JSONResponse({"name": user["name"], "email": user["email"]})
    auth.set_auth_cookie(resp, auth.sign_token(user))
    return resp


@router.post("/logout")
async def logout():
    resp = JSONResponse({"ok": True})
    auth.clear_auth_cookie(resp)
    return resp


@router.get("/me")
async def me(request: Request):
    u = auth.current_user(request)
    if not u:
        return err(401, "Not signed in.")
    return {"name": u["name"], "email": u["email"]}


@router.get("/lookup/{email}")
async def lookup(email: str, request: Request):
    # Used only for the "Welcome back" quick sign-in. Rate limited to make
    # bulk email enumeration impractical. Returns name only, never the hash.
    ratelimit.limit(request, "lookup", 20, 60)
    user = await db.get_user_by_email(email.strip().lower())
    if not user:
        return err(404, "No account with that email.")
    return {"name": user["name"], "email": user["email"]}
