from __future__ import annotations

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import auth, db, order_status
from ..products import DELIVERY_FEE, find_option

router = APIRouter()

MAX_LINES = 100
MAX_QTY = 1000


def err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def new_order_id() -> str:
    # Random suffix instead of a timestamp: two orders in the same
    # millisecond can no longer collide.
    return "FM" + secrets.token_hex(4).upper()


def naira(n: int) -> str:
    return f"{n:,}"


@router.post("")
@router.post("/")
async def place_order(request: Request, user: dict = Depends(auth.require_auth)):
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    items = body.get("items")
    address = body.get("address")
    phone = body.get("phone")
    city = body.get("city")
    pay_method = body.get("payMethod")
    payment_detail = body.get("paymentDetail")

    if not isinstance(items, list) or len(items) == 0:
        return err(400, "Your cart is empty.")
    if len(items) > MAX_LINES:
        return err(400, "Too many items in one order.")
    if not address or not phone:
        return err(400, "Please add your delivery address and phone number.")
    if pay_method not in ("before", "delivery"):
        return err(400, "Please choose a payment method.")

    # Rebuild every line from the server catalog; prices from the browser
    # are never trusted.
    lines = []
    for raw in items:
        if not isinstance(raw, dict):
            return err(400, "One of the items in your cart is no longer available.")
        found = find_option(raw.get("productId"), raw.get("optionIndex"))
        if not found:
            return err(400, "One of the items in your cart is no longer available.")
        product, option = found
        qty = raw.get("qty")
        if isinstance(qty, float) and qty.is_integer():
            qty = int(qty)
        if isinstance(qty, str) and qty.strip().isdigit():
            qty = int(qty)
        if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0 or qty > MAX_QTY:
            return err(400, f"Invalid quantity for {product['name']}.")
        lines.append(
            {
                "name": f"{product['name']} ({option['label']})",
                "qty": qty,
                "price": option["price"],
                "note": str(raw.get("note") or "")[:300],
            }
        )

    subtotal = sum(line["price"] * line["qty"] for line in lines)
    total = subtotal + DELIVERY_FEE
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    city_s = str(city) if city else ""

    order = {
        "id": new_order_id(),
        "date": now,
        "items": lines,
        "subtotal": subtotal,
        "deliveryFee": DELIVERY_FEE,
        "total": total,
        "address": str(address),
        "phone": str(phone),
        "city": city_s,
        "payMethod": pay_method,
        "paymentDetail": payment_detail if isinstance(payment_detail, dict) else {},
        "status": order_status.INITIAL[pay_method],
        "user": user["email"],
    }
    await db.add_order(order)

    # Simulated store SMS (see README: real SMS needs a gateway such as Termii).
    summary = ", ".join(f"{line['qty']}x {line['name']}" for line in lines)
    pay_line = "PAID (before delivery)" if pay_method == "before" else "Pay on delivery"
    text = (
        f"New order {order['id']} — ₦{naira(total)}. {summary}. "
        f"Deliver to: {order['address']}, {city_s}. Customer: {order['phone']}. {pay_line}."
    )
    await db.add_store_sms({"id": order["id"], "text": text, "date": now})

    return {"order": order}


@router.get("/mine")
async def my_orders(user: dict = Depends(auth.require_auth)):
    return {"orders": await db.get_orders_for_user(user["email"])}
