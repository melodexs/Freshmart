"""The signed-in customer's own account: profile, saved addresses and password.

Every route takes the customer from their session cookie, never from the request, so one customer
can never read or change another's data.
"""

from __future__ import annotations

import secrets

import bcrypt
from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from .. import auth, catalogue, db, ratelimit
from ..phone import normalise

router = APIRouter(dependencies=[Depends(auth.require_auth)])

MAX_ADDRESSES = 10


def err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


async def body_of(request: Request) -> dict:
    try:
        b = await request.json()
    except Exception:
        return {}
    return b if isinstance(b, dict) else {}


def text(v, limit: int) -> str:
    return " ".join(v.split())[:limit] if isinstance(v, str) else ""


@router.get("")
async def account(request: Request):
    me = auth.current_user(request)
    user = await db.get_user_by_email(me["email"])
    if not user:
        return err(404, "Account not found.")
    orders = await db.get_orders_for_user(me["email"])
    fav_ids = await db.get_favourites(me["email"])
    return {
        "profile": {"name": user["name"], "email": user["email"], "phone": user["phone"]},
        "addresses": await db.list_addresses(me["email"]),
        "favourites": fav_ids,
        "favouriteProducts": [
            {"id": p["id"], "name": p["name"], "from": catalogue.from_price(p)}
            for p in await catalogue.all_products()
            if p["id"] in fav_ids
        ],
        "orderCount": len(orders),
        "totalSpent": sum(o["total"] for o in orders if o["status"] != "Cancelled"),
    }


@router.put("/profile")
async def update_profile(request: Request):
    me = auth.current_user(request)
    b = await body_of(request)
    name = text(b.get("name"), 80)
    phone = normalise(b.get("phone"))
    if len(name) < 2:
        return err(400, "Please enter your full name.")
    if phone is None:
        return err(400, "Please enter a valid Nigerian mobile number, like 0801 234 5678.")
    await db.update_profile(me["email"], name, phone)
    resp = JSONResponse({"profile": {"name": name, "email": me["email"], "phone": phone}})
    # The session cookie carries the name shown in the header, so issue a fresh one.
    auth.set_auth_cookie(resp, auth.sign_token({"email": me["email"], "name": name}))
    return resp


async def parse_address(b: dict, email: str) -> tuple[dict | None, str | None]:
    area = text(b.get("area"), 60)
    address = text(b.get("address"), 200)
    label = text(b.get("label"), 30) or "Home"
    phone = normalise(b.get("phone"))
    if await catalogue.fee_for_area(area) is None:
        return None, "Please choose one of the areas we deliver to."
    if len(address) < 5:
        return None, "Please enter the full delivery address."
    if phone is None:
        return None, "Please enter a valid Nigerian mobile number, like 0801 234 5678."
    return {
        "label": label,
        "area": area,
        "address": address,
        "phone": phone,
        "isDefault": bool(b.get("isDefault")),
    }, None


@router.post("/addresses")
async def add_address(request: Request):
    me = auth.current_user(request)
    existing = await db.list_addresses(me["email"])
    if len(existing) >= MAX_ADDRESSES:
        return err(409, f"You can save up to {MAX_ADDRESSES} addresses. Remove one first.")
    a, problem = await parse_address(await body_of(request), me["email"])
    if problem:
        return err(400, problem)
    a["id"] = "ad" + secrets.token_hex(6)
    a["isDefault"] = a["isDefault"] or not existing  # the first one is the default
    await db.save_address(me["email"], a)
    return {"address": a}


@router.put("/addresses/{address_id}")
async def edit_address(address_id: str, request: Request):
    me = auth.current_user(request)
    mine = {a["id"]: a for a in await db.list_addresses(me["email"])}
    if address_id not in mine:
        return err(404, "That address was not found.")
    a, problem = await parse_address(await body_of(request), me["email"])
    if problem:
        return err(400, problem)
    a["id"] = address_id
    await db.save_address(me["email"], a)
    return {"address": a}


@router.delete("/addresses/{address_id}")
async def remove_address(address_id: str, request: Request):
    me = auth.current_user(request)
    if not await db.delete_address(me["email"], address_id):
        return err(404, "That address was not found.")
    left = await db.list_addresses(me["email"])
    if left and not any(a["isDefault"] for a in left):
        first = {**left[0], "isDefault": True}
        await db.save_address(me["email"], first)
    return {"deleted": True}


@router.post("/password")
async def change_password(request: Request):
    me = auth.current_user(request)
    ratelimit.limit(request, "password", 8, 600)
    b = await body_of(request)
    current = b.get("currentPassword") if isinstance(b.get("currentPassword"), str) else ""
    new = b.get("newPassword") if isinstance(b.get("newPassword"), str) else ""
    user = await db.get_user_by_email(me["email"])
    ok = bool(user) and await run_in_threadpool(
        lambda: bcrypt.checkpw(current.encode(), user["passHash"].encode())
    )
    if not ok:
        return err(403, "Your current password is not correct.")
    if len(new) < 6:
        return err(400, "The new password should be at least 6 characters.")
    if new == current:
        return err(400, "Choose a password that is different from your current one.")
    new_hash = await run_in_threadpool(
        lambda: bcrypt.hashpw(new.encode(), bcrypt.gensalt(10)).decode()
    )
    await db.save_user({**user, "passHash": new_hash})
    return {"ok": True}
