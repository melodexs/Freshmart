"""Admin JSON API. Every route needs the staff session (same login as the order feed).

Mounted under /api/store/admin so the existing staff cookie (scoped to /api/store) covers it.
All input is validated here; nothing from the browser is trusted.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from .. import auth, catalogue, db, discounts, images, order_status, social

MEDIA_RE = re.compile(r"/media/im[0-9a-f]{16}")

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
    if image and not (
        MEDIA_RE.fullmatch(image)
        or image.startswith("/static/products/")
        or image.startswith("https://")
    ):
        return None, "The image must be an uploaded photo or an https link."
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
    if p["stock"]:
        await catalogue.log_stock(p["id"], p["stock"], p["stock"], "New product added", "admin")
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
    if p["stock"] != existing.get("stock") and p["stock"] is not None:
        was = existing.get("stock")
        change = p["stock"] if was is None else p["stock"] - was
        reason = "Stock tracking started" if was is None else "Stock edited by admin"
        await catalogue.log_stock(product_id, change, p["stock"], reason, "admin")
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
    before = p.get("stock")
    p["stock"] = n
    await db.save_product(p)
    if before is None:
        await catalogue.log_stock(product_id, n, n, "Stock tracking started", "admin")
    else:
        await catalogue.log_stock(product_id, n - before, n, "Stock corrected by admin", "admin")
    return {"product": p}


@router.get("/stock-history")
async def stock_history(product: str | None = None, limit: int = 100):
    return {"moves": await db.list_stock_moves(product, max(1, min(limit, 500)))}


@router.get("/settings")
async def get_settings():
    return {
        "deliveryFee": await catalogue.delivery_fee(),
        "storeName": await db.get_setting("store_name", "Okwui's Grocery Store (OGS)"),
        "whatsapp": await db.get_setting("whatsapp", ""),
        "contactPhone": await db.get_setting("contact_phone", ""),
        "banner": await db.get_setting("banner", ""),
        "bank": await catalogue.bank_details(),
        "areas": await catalogue.delivery_areas(),
        "social": {
            k: v
            for k, v in (await db.get_setting("social", {}) or {}).items()
            if k in social.NETWORKS
        },
        "socialNetworks": {k: v[0] for k, v in social.NETWORKS.items()},
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
    if "areas" in b:
        raw_areas = b["areas"]
        if not isinstance(raw_areas, list) or not 1 <= len(raw_areas) <= 40:
            return err(400, "Add between 1 and 40 delivery areas.")
        areas, seen = [], set()
        for a in raw_areas:
            name = clean_text(a.get("name") if isinstance(a, dict) else None, 60)
            fee = clean_int(a.get("fee") if isinstance(a, dict) else None, 0, 100_000)
            if not name or fee is None:
                return err(
                    400, "Each delivery area needs a name and a fee from 0 to 100,000 naira."
                )
            if name.lower() in seen:
                return err(400, f"The area '{name}' is listed twice.")
            seen.add(name.lower())
            eta = clean_text(a.get("eta"), 40)
            areas.append({"name": name, "fee": fee, "eta": eta})
        await db.set_setting("delivery_areas", areas)
        await db.add_audit("admin", "delivery_areas_changed", "settings", {"areas": areas})
    if "bank" in b:
        raw = b["bank"] if isinstance(b["bank"], dict) else {}
        bank = clean_text(raw.get("bank"), 60)
        name = clean_text(raw.get("accountName"), 80)
        number = re.sub(r"\s", "", clean_text(raw.get("accountNumber"), 20))
        if (bank or name or number) and not (bank and name and number):
            return err(
                400, "Enter the bank, account name and account number together, or clear all three."
            )
        if number and not re.fullmatch(r"\d{10}", number):
            return err(400, "A Nigerian account number has exactly 10 digits.")
        await db.set_setting(
            "bank_details", {"bank": bank, "accountName": name, "accountNumber": number}
        )
        await db.add_audit(
            "admin",
            "bank_details_changed",
            "settings",
            {"bank": bank, "accountNumberEnding": number[-4:]},
        )
    if "social" in b:
        raw = b["social"] if isinstance(b["social"], dict) else {}
        links = {}
        for net in social.NETWORKS:
            if net not in raw:
                continue
            url = social.clean_social(net, raw[net])
            if url is None:
                return err(
                    400,
                    f"That is not a valid {social.NETWORKS[net][0]} link. Paste the full https address of your page.",
                )
            links[net] = url
        current = await db.get_setting("social", {}) or {}
        await db.set_setting("social", {**current, **links})
        await db.add_audit("admin", "social_links_changed", "settings", {"networks": sorted(links)})
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
    # Unpaid pay-ahead orders are not revenue yet, and cancelled ones never are.
    live = [
        o
        for o in orders
        if o["status"] not in (order_status.CANCELLED, order_status.AWAITING_PAYMENT)
    ]
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
            if o["status"]
            in (
                order_status.AWAITING_PAYMENT,
                order_status.PAID,
                order_status.AWAITING,
                order_status.PREPARING,
            )
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
    await db.add_audit("admin", "status_changed", order_id, {"from": o["status"], "to": new})
    if new == order_status.CANCELLED:
        await catalogue.restock_order(
            o, "Order cancelled by admin", "admin"
        )  # gives the reserved stock back
    return {"order": await db.get_order(order_id)}


PAY_METHODS = {"bank transfer", "ussd", "cash", "pos", "other"}


@router.post("/orders/{order_id}/confirm-payment")
async def confirm_payment(order_id: str, request: Request):
    """Mark a pay-ahead order as paid, once, with a permanent record of who and how much.

    Only an order that is still "Awaiting payment" can be confirmed. The amount received must be
    entered and must match the order total, so a typo cannot quietly mark an order paid.
    """
    o = await db.get_order(order_id)
    if not o:
        return err(404, "That order does not exist.")
    if o["status"] != order_status.AWAITING_PAYMENT:
        return err(409, "Only an order that is awaiting payment can be confirmed as paid.")
    b = await body_of(request)
    amount = clean_int(b.get("amount"), 1, MAX_PRICE * 100)
    if amount is None:
        return err(400, "Enter the amount you received, in naira.")
    if amount != o["total"]:
        return err(
            409,
            f"The amount received (₦{amount:,}) does not match the order total (₦{o['total']:,}). "
            "Check the payment before confirming.",
        )
    method = clean_text(b.get("method"), 20).lower()
    if method not in PAY_METHODS:
        return err(400, "Choose how the payment was received.")
    reference = clean_text(b.get("reference"), 80)
    if not reference:
        return err(400, "Enter the bank or transfer reference so the payment can be traced.")
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    record = {
        "paid": True,
        "paidAmount": amount,
        "paidMethod": method,
        "paidReference": reference,
        "paidAt": now,
        "confirmedBy": "admin",
    }
    ok = await db.confirm_payment(
        order_id, order_status.AWAITING_PAYMENT, order_status.PAID, record
    )
    if not ok:
        return err(409, "That order was just changed by someone else. Please refresh.")
    await db.add_audit(
        "admin",
        "payment_confirmed",
        order_id,
        {"amount": amount, "method": method, "reference": reference, "orderTotal": o["total"]},
    )
    return {"order": await db.get_order(order_id)}


@router.get("/audit")
async def audit(subject: str = ""):
    return {"entries": await db.get_audit(subject.strip()[:40] or None, 100)}


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


@router.post("/images")
async def upload_image(request: Request, file: UploadFile = File(...)):
    """Accept one product photo. Returns the /media/ path to save on the product."""
    raw = await file.read(images.MAX_BYTES + 1)
    try:
        data = await run_in_threadpool(images.process, raw)
    except images.BadImage as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    image_id = images.new_id()
    await db.save_image(image_id, data)
    await db.add_audit("admin", "image_uploaded", image_id, {"bytes": len(data)})
    return {"url": f"/media/{image_id}", "bytes": len(data)}


@router.get("/discounts")
async def list_discount_codes():
    return {"codes": await db.list_discounts()}


@router.post("/discounts")
async def save_discount_code(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    rule, problem = discounts.validate_definition(body if isinstance(body, dict) else {})
    if problem:
        return JSONResponse({"error": problem}, status_code=400)
    existing = await db.get_discount(rule["code"])
    await db.save_discount(rule)
    await db.add_audit(
        "admin", "discount_changed" if existing else "discount_created", rule["code"], rule
    )
    return {"code": rule}
