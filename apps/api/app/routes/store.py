from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import auth, db, ratelimit

router = APIRouter()


@router.post("/login")
async def staff_login(request: Request):
    """Exchange the staff key for a 12h httpOnly staff cookie."""
    ratelimit.limit(request, "staff-login", 5, 60)
    if not auth.staff_enabled():
        return JSONResponse({"error": "Store feed is disabled."}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        body = {}
    key = body.get("key") if isinstance(body, dict) and isinstance(body.get("key"), str) else ""
    if not auth.check_staff_key(key):
        return JSONResponse({"error": "That staff key is not correct."}, status_code=401)
    resp = JSONResponse({"ok": True})
    auth.set_staff_cookie(resp)
    return resp


@router.post("/logout")
async def staff_logout():
    resp = JSONResponse({"ok": True})
    auth.clear_staff_cookie(resp)
    return resp


@router.get("/session")
async def staff_session(request: Request):
    """Lets the UI know whether to show the sign-in form or the feed."""
    return {
        "enabled": auth.staff_enabled(),
        "staff": auth.staff_enabled() and auth.is_staff(request),
    }


@router.get("/notifications", dependencies=[Depends(auth.require_staff)])
async def notifications():
    return {"notifications": await db.get_store_sms()}
