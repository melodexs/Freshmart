"""Named admin accounts: sign in as a person, owners above staff.

- The shared staff key keeps working as the lowest level ('staff'); nobody is locked out.
- Only a named owner can create, deactivate or reset other admins, and see the list.
- Passwords are bcrypt-hashed. A password set by someone else (first one, or a reset)
  must be changed at first sign-in, so the person who set it never stays able to sign in as them.
- Wrong passwords lock that one account for 15 min, then 1 h, then 24 h. Unknown emails
  get the same reply and take the same time, so nobody can discover who is an admin.
"""

from __future__ import annotations

import secrets
import time

import bcrypt
from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from .. import auth, db, phone, ratelimit
from ..emails import clean_email

router = APIRouter()
owner_router = APIRouter(dependencies=[Depends(auth.require_owner)])

MIN_PASSWORD = 10
LOCK_AFTER = 5
LOCK_STEPS = (15 * 60, 60 * 60, 24 * 60 * 60)
# A real bcrypt hash of a random string: unknown emails are checked against it so they cost the same time.
_DUMMY = bcrypt.hashpw(secrets.token_bytes(16), bcrypt.gensalt(10)).decode()
ROLES = ("owner", "staff")


def _err(msg: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=code)


async def _body(request: Request) -> dict:
    try:
        b = await request.json()
    except Exception:
        return {}
    return b if isinstance(b, dict) else {}


def _s(v, n: int = 200) -> str:
    return v.strip()[:n] if isinstance(v, str) else ""


def _hash(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(10)).decode()


def public(a: dict) -> dict:
    """What the dashboard may see about an admin. Never the hash."""
    return {
        "email": a["email"],
        "name": a["name"],
        "phone": a["phone"],
        "role": a["role"],
        "active": a["active"],
        "mustChange": a["mustChange"],
        "lastLogin": a["lastLogin"],
        "created": a["created"],
        "createdBy": a["createdBy"],
    }


def password_problem(pw: str, a: dict | None = None) -> str:
    """Why this password is not allowed, or '' if it is fine."""
    if len(pw) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters."
    if len(pw.encode()) > 72:
        return "Use at most 72 characters."
    digits = "".join(ch for ch in pw if ch.isdigit())
    if pw.isdigit():
        return "Add some letters so the password is not just a number."
    if a:
        low = pw.lower()
        words = [w for w in a["name"].lower().replace("-", " ").split() if len(w) >= 3]
        for secret in [a["email"].split("@")[0].lower(), a["name"].lower(), *words]:
            if len(secret) >= 3 and secret in low:
                return "Do not use your name or email in the password."
        if a["phone"] and (a["phone"][1:] in digits or a["phone"] in digits):
            return "Do not use your phone number in the password."
    return ""


async def seed_first_owner() -> str:
    """Create the first owner from the FIRST_OWNER_* settings, only if no owner exists yet.

    Returns what happened, for the start-up log. It never overwrites or re-creates anyone,
    and the password is hashed here and must be changed at first sign-in.
    """
    from .. import config

    if not (config.FIRST_OWNER_EMAIL and config.FIRST_OWNER_PASSWORD):
        return "no first owner configured"
    if any(a["role"] == "owner" for a in await db.list_admins()):
        return "an owner already exists"
    email = clean_email(config.FIRST_OWNER_EMAIL)
    local = phone.normalise(config.FIRST_OWNER_PHONE)
    name = config.FIRST_OWNER_NAME.strip()
    if not email or not local or len(name) < 2 or len(config.FIRST_OWNER_PASSWORD) < 8:
        return "first owner settings are incomplete or invalid"
    made = await db.create_admin(
        {
            "email": email,
            "name": name,
            "phone": local,
            "passHash": await run_in_threadpool(_hash, config.FIRST_OWNER_PASSWORD[:72]),
            "role": "owner",
            "mustChange": True,
            "createdBy": "first-owner setup",
        }
    )
    if made:
        await db.add_audit("first-owner setup", "admin_created", email, {"role": "owner"})
    return "first owner created" if made else "that email is already an admin"


@router.post("/admin-login")
async def admin_login(request: Request):
    ratelimit.limit(request, "admin-login", 10, 60)
    b = await _body(request)
    email = clean_email(b.get("email")) or ""
    password = b.get("password") if isinstance(b.get("password"), str) else ""
    bad = _err("Email or password is incorrect.", 401)
    if not email or not password:
        return bad
    a = await db.get_admin(email)
    now = time.time()
    if a and a["lockedUntil"] > now:
        # Same words as a wrong password, so a lock does not confirm the account exists.
        await run_in_threadpool(lambda: bcrypt.checkpw(password.encode(), _DUMMY.encode()))
        return bad
    ok = await run_in_threadpool(
        lambda: bcrypt.checkpw(password.encode(), (a["passHash"] if a else _DUMMY).encode())
    )
    if not a or not ok or not a["active"]:
        if a and a["active"] and not ok:
            fails = a["fails"] + 1
            if fails >= LOCK_AFTER:
                step = min((fails // LOCK_AFTER) - 1, len(LOCK_STEPS) - 1)
                await db.update_admin(email, fails=fails, lockedUntil=now + LOCK_STEPS[step])
                await db.add_audit(a["name"], "admin_locked", email, {"fails": fails})
            else:
                await db.update_admin(email, fails=fails)
        return bad
    await db.update_admin(email, fails=0, lockedUntil=0, lastLogin=True)
    await db.add_audit(a["name"], "admin_signed_in", email, {"role": a["role"]})
    resp = JSONResponse(
        {"ok": True, "name": a["name"], "role": a["role"], "mustChange": a["mustChange"]}
    )
    auth.set_staff_cookie(resp, a)
    return resp


@router.get("/me")
async def me(request: Request):
    """Who is signed in to the dashboard right now."""
    if not auth.staff_enabled() or not auth.is_staff(request):
        return _err("Not signed in.", 401)
    who = auth.staff_identity(request)
    must = False
    if who["email"]:
        a = await db.get_admin(who["email"])
        if not a or not a["active"]:
            return _err("Not signed in.", 401)
        must = a["mustChange"]
        who = {"name": a["name"], "email": a["email"], "level": a["role"]}
    return {**who, "mustChange": must}


@router.post("/change-password")
async def change_password(request: Request):
    """A signed-in named admin sets their own password (needed at first sign-in)."""
    ratelimit.limit(request, "admin-pw", 10, 60)
    auth.require_staff(request)
    who = auth.staff_identity(request)
    if not who["email"]:
        return _err("The shared staff key has no password to change.", 400)
    a = await db.get_admin(who["email"])
    if not a or not a["active"]:
        return _err("Not signed in.", 401)
    b = await _body(request)
    current = b.get("current") if isinstance(b.get("current"), str) else ""
    new = b.get("new") if isinstance(b.get("new"), str) else ""
    if not await run_in_threadpool(
        lambda: bcrypt.checkpw(current.encode(), a["passHash"].encode())
    ):
        return _err("Your current password is not correct.", 401)
    if new == current:
        return _err("Choose a password that is different from the current one.")
    problem = password_problem(new, a)
    if problem:
        return _err(problem)
    await db.update_admin(
        a["email"], passHash=await run_in_threadpool(_hash, new), mustChange=False
    )
    await db.add_audit(a["name"], "admin_password_changed", a["email"], {})
    resp = JSONResponse({"ok": True})
    auth.set_staff_cookie(resp, {**a, "mustChange": False})  # fresh session after the change
    return resp


# ---------- owner only ----------


@owner_router.get("/admins")
async def list_admins():
    return {"admins": [public(a) for a in await db.list_admins()]}


@owner_router.post("/admins")
async def create_admin(request: Request):
    who = auth.staff_identity(request)
    b = await _body(request)
    name = _s(b.get("name"), 80)
    email = clean_email(b.get("email")) or ""
    local = phone.normalise(_s(b.get("phone"), 30))
    role = _s(b.get("role")) or "staff"
    password = b.get("password") if isinstance(b.get("password"), str) else ""
    if len(name) < 2:
        return _err("Please enter the person's full name.")
    if not email:
        return _err("Please enter a valid email address.")
    if not local:
        return _err("Please enter a valid Nigerian mobile number.")
    if role not in ROLES:
        return _err("Role must be owner or staff.")
    if len(password) < 8 or len(password.encode()) > 72:
        return _err(
            "The first password must be 8 to 72 characters. The person must change it when they first sign in."
        )
    created = await db.create_admin(
        {
            "email": email,
            "name": name,
            "phone": local,
            "passHash": await run_in_threadpool(_hash, password),
            "role": role,
            "mustChange": True,
            "createdBy": who["name"],
        }
    )
    if not created:
        return _err("An admin with that email already exists.", 409)
    await db.add_audit(who["name"], "admin_created", email, {"role": role})
    return JSONResponse({"ok": True}, status_code=201)


async def _target(email: str):
    a = await db.get_admin(clean_email(email) or "")
    return a


async def _last_owner(a: dict) -> bool:
    owners = [x for x in await db.list_admins() if x["role"] == "owner" and x["active"]]
    return a["role"] == "owner" and a["active"] and len(owners) <= 1


@owner_router.post("/admins/{email}/active")
async def set_active(email: str, request: Request):
    who = auth.staff_identity(request)
    a = await _target(email)
    if not a:
        return _err("No such admin.", 404)
    b = await _body(request)
    active = b.get("active") is True
    if not active and await _last_owner(a):
        return _err("You cannot deactivate the only active owner.", 409)
    await db.update_admin(a["email"], active=active)
    await db.add_audit(
        who["name"], "admin_activated" if active else "admin_deactivated", a["email"], {}
    )
    return {"ok": True}


@owner_router.post("/admins/{email}/role")
async def set_role(email: str, request: Request):
    who = auth.staff_identity(request)
    a = await _target(email)
    if not a:
        return _err("No such admin.", 404)
    role = _s((await _body(request)).get("role"))
    if role not in ROLES:
        return _err("Role must be owner or staff.")
    if role != "owner" and await _last_owner(a):
        return _err("You cannot demote the only active owner.", 409)
    await db.update_admin(a["email"], role=role)
    await db.add_audit(who["name"], "admin_role_changed", a["email"], {"role": role})
    return {"ok": True}


@owner_router.post("/admins/{email}/reset-password")
async def reset_password(email: str, request: Request):
    """Owner sets a new first password for someone. They must change it at next sign-in."""
    who = auth.staff_identity(request)
    a = await _target(email)
    if not a:
        return _err("No such admin.", 404)
    password = _s((await _body(request)).get("password"), 100)
    if len(password) < 8 or len(password.encode()) > 72:
        return _err("The temporary password must be 8 to 72 characters.")
    await db.update_admin(
        a["email"],
        passHash=await run_in_threadpool(_hash, password),
        mustChange=True,
        fails=0,
        lockedUntil=0,
    )
    await db.add_audit(who["name"], "admin_password_reset", a["email"], {})
    return {"ok": True}
