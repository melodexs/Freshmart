"""Admin JSON API. Every route needs the staff session (same login as the order feed).

Mounted under /api/store/admin so the existing staff cookie (scoped to /api/store) covers it.
All input is validated here; nothing from the browser is trusted.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import auth, catalogue, db, order_status

router = APIRouter(dependencies=[Depends(auth.require_staff)])

MAX_PRICE = 10_000_000
MAX_OPTIONS = 12
LOW_STOCK = 5
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


async def body_of(request: Request) -> dict:
    try:
        b = await request.json()
    except Exception:
        return {}
    return b if isinstance(b, dict) else {}


def clean_int(v, lo: int, hi: int) -> int | None:
    """A whole number within [lo, hi], or None. Rejects bools, floats with decimals and junk."""
    if isinstance(v, bool):
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        v = int(v.strip())
    if not isinstance(v, int) or v < lo or v > hi:
        return None
    return v


def clean_text(v, limit: int) -> str:
    return " ".join(str(v or "").split())[:limit] if isinstance(v, str) else ""


def parse_product(b: dict, existing: dict | None) -> tuple[dict | None, str | None]:
    """Validate a product from the admin form. Returns (product, None) or (None, message)."""
    name = clean_text(b.get("name"), 80)
    cat = clean_text(b.get("cat"), 40)
    if not name:
        return None, "Please give the product a name."
    if not cat:
        return None, "Please choose a category."
    raw_opts = b.get("options")
    if not isinstance(raw_opts, list) or not 1 <= len(raw_opts) <= MAX_OPTIONS:
        return None, f"Add between 1 and {MAX_OPTIONS} sizes with prices."
    options, compare = [], []
    for o in raw_opts:
        if not isinstance(o, dict):
            return None, "Each size needs a label and a price."
        label = clean_text(o.get("label"), 40)
        price = clean_int(o.get("price"), 1, MAX_PRICE)
        if not label or price is None:
            return None, "Each size needs a label and a whole-number price in naira."
        was = o.get("was")
        was_n = None if was in (None, "", 0) else clean_int(was, 1, MAX_PRICE)
        if was not in (None, "", 0) and (was_n is None or was_n <= price):
            return None, f"The old price for {label} must be higher than its current price."
        options.append({"label": label, "price": price})
        compare.append(was_n)
    stock_raw = b.get("stock")
    stock = None if stock_raw in (None, "") else clean_int(stock_raw, 0, 1_000_000)
    if stock_raw not in (None, "") and stock is None:
        return None, "Stock must be a whole number, or left empty to not track it."
    image = clean_text(b.get("image"), 300)
    if image and not (image.startswith("/static/") or image.startswith("https://")):
        return None, "The image must be an uploaded file or an https link."
    pid = existing["id"] if existing else clean_text(b.get("id"), 40).lower()
    if not existing and not ID_RE.match(pid):
        return None, "The product code can use letters, numbers, - and _ only."
    return {
        "id": pid,
        "name": name,
        "cat": cat,
        "emoji": clean_text(b.get("emoji"), 8),
        "description": clean_text(b.get("description"), 600),
        "image": image,
        "options": options,
        "comparePrices": compare,
        "stock": stock,
        "active": bool(b.get("active", True)),
        "featured": bool(b.get("featured", False)),
        "sort": clean_int(b.get("sort"), 0, 100000) or (existing or {}).get("sort", 0),
    }, None


@router.get("/products")
async def products():
    return {"products": await catalogue.all_products(include_inactive=True)}


@router.post("/products")
async def create_product(request: Request):
    p, problem = parse_product(await body_of(request), None)
    if problem:
        return err(400, problem)
    if await db.get_product(p["id"]):
        return err(409, "A product with that code already exists.")
    await db.save_product(p)
    return {"product": p}


@router.put("/products/{product_id}")
async def update_product(product_id: str, request: Request):
    existing = await db.get_product(product_id)
    if not existing:
        return err(404, "That product does not exist.")
    p, problem = parse_product(await body_of(request), existing)
    if problem:
        return err(400, problem)
    await db.save_product(p)
    return {"product": p}


@router.delete("/products/{product_id}")
async def remove_product(product_id: str):
    """Hide instead of delete when the product has been ordered, so old orders stay readable."""
    if not await db.get_product(product_id):
        return err(404, "That product does not exist.")
    orders = await db.get_all_orders()
    if any(i.get("productId") == product_id for o in orders for i in o["items"]):
        p = await db.get_product(product_id)
        p["active"] = False
        await db.save_product(p)
        return {"deleted": False, "hidden": True}
    await db.delete_product(product_id)
    return {"deleted": True, "hidden": False}


@router.post("/products/{product_id}/stock")
async def set_stock(product_id: str, request: Request):
    p = await db.get_product(product_id)
    if not p:
        return err(404, "That product does not exist.")
    b = await body_of(request)
    n = clean_int(b.get("stock"), 0, 1_000_000)
    if n is None:
        return err(400, "Stock must be a whole number from 0 up.")
    p["stock"] = n
    await db.save_product(p)
    return {"product": p}


@router.get("/settings")
async def get_settings():
    return {
        "deliveryFee": await catalogue.delivery_fee(),
        "storeName": await db.get_setting("store_name", "Okwui's Grocery Store (OGS)"),
        "whatsapp": await db.get_setting("whatsapp", ""),
        "contactPhone": await db.get_setting("contact_phone", ""),
        "banner": await db.get_setting("banner", ""),
    }


@router.put("/settings")
async def put_settings(request: Request):
    b = await body_of(request)
    if "deliveryFee" in b:
        fee = clean_int(b["deliveryFee"], 0, 100_000)
        if fee is None:
            return err(400, "The delivery fee must be a whole number of naira from 0 to 100,000.")
        await db.set_setting("delivery_fee", fee)
    for key, setting, limit in (
        ("storeName", "store_name", 80),
        ("banner", "banner", 200),
    ):
        if key in b:
            await db.set_setting(setting, clean_text(b[key], limit))
    for key, setting in (("whatsapp", "whatsapp"), ("contactPhone", "contact_phone")):
        if key in b:
            from ..phone import normalise

            raw = clean_text(b[key], 30)
            if raw and normalise(raw) is None:
                return err(400, "Please enter a valid Nigerian mobile number, like 0801 234 5678.")
            await db.set_setting(setting, normalise(raw) if raw else "")
    return await get_settings()


@router.get("/overview")
async def overview():
    orders = await db.get_all_orders()
    live = [o for o in orders if o["status"] != order_status.CANCELLED]
    now = datetime.now(UTC)
    today = now.date().isoformat()

    def day(o):
        return o["date"][:10]

    products = await catalogue.all_products(include_inactive=True)
    by_day = {}
    for i in range(6, -1, -1):
        d = (now - timedelta(days=i)).date().isoformat()
        by_day[d] = {"date": d, "orders": 0, "revenue": 0}
    for o in live:
        if day(o) in by_day:
            by_day[day(o)]["orders"] += 1
            by_day[day(o)]["revenue"] += o["total"]
    counts: dict[str, int] = {}
    for o in orders:
        counts[o["status"]] = counts.get(o["status"], 0) + 1
    low = [
        {"id": p["id"], "name": p["name"], "stock": p["stock"]}
        for p in products
        if p["active"] and p["stock"] is not None and p["stock"] <= LOW_STOCK
    ]
    return {
        "revenue": sum(o["total"] for o in live),
        "todaySales": sum(o["total"] for o in live if day(o) == today),
        "totalOrders": len(orders),
        "pendingOrders": sum(
            1
            for o in orders
            if o["status"] in (order_status.PAID, order_status.AWAITING, order_status.PREPARING)
        ),
        "completedOrders": counts.get(order_status.DELIVERED, 0),
        "customers": len({o["user"] for o in orders}),
        "products": len(products),
        "lowStock": low,
        "statusCounts": counts,
        "last7Days": list(by_day.values()),
        "recent": [
            {"id": o["id"], "total": o["total"], "status": o["status"], "date": o["date"]}
            for o in orders[:8]
        ],
    }


@router.get("/orders")
async def orders(q: str = "", status: str = ""):
    items = await db.get_all_orders()
    q = q.strip().lower()[:60]
    if status:
        items = [o for o in items if o["status"] == status]
    if q:
        items = [
            o for o in items if q in o["id"].lower() or q in o["phone"] or q in o["user"].lower()
        ]
    return {"orders": items[:200], "statuses": order_status.ALL}


@router.post("/orders/{order_id}/status")
async def set_order_status(order_id: str, request: Request):
    o = await db.get_order(order_id)
    if not o:
        return err(404, "That order does not exist.")
    new = clean_text((await body_of(request)).get("status"), 80)
    if new not in order_status.staff_options(o["status"]):
        return err(409, f"An order that is '{o['status']}' cannot move to '{new}'.")
    ok = await db.update_order_status(order_id, new, allowed_from=[o["status"]])
    if not ok:
        return err(409, "That order was just changed by someone else. Please refresh.")
    if new == order_status.CANCELLED:
        # Cancelling gives the reserved stock back.
        for i in o["items"]:
            if i.get("productId"):
                await db.adjust_stock(i["productId"], int(i["qty"]))
    return {"order": await db.get_order(order_id)}


@router.get("/customers")
async def customers():
    orders = await db.get_all_orders()
    seen: dict[str, dict] = {}
    for o in orders:
        c = seen.setdefault(
            o["user"], {"email": o["user"], "phone": o["phone"], "orders": 0, "spent": 0}
        )
        c["orders"] += 1
        if o["status"] != order_status.CANCELLED:
            c["spent"] += o["total"]
    out = []
    for email, c in seen.items():
        u = await db.get_user_by_email(email)
        out.append({**c, "name": (u or {}).get("name", "")})
    return {"customers": sorted(out, key=lambda c: -c["spent"])}
