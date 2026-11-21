from __future__ import annotations

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import auth, catalogue, db, order_status
from ..phone import normalise as normalise_phone

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
    clean_phone = normalise_phone(phone)
    if clean_phone is None:
        return err(400, "Please enter a valid Nigerian mobile number, like 0801 234 5678.")
    if pay_method not in ("before", "delivery"):
        return err(400, "Please choose a payment method.")

    # Rebuild every line from the server catalog; prices from the browser
    # are never trusted.
    lines = []
    wanted: dict[str, int] = {}
    for raw in items:
        if not isinstance(raw, dict):
            return err(400, "One of the items in your cart is no longer available.")
        found = await catalogue.find_option(raw.get("productId"), raw.get("optionIndex"))
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
        stock = product.get("stock")
        wanted[product["id"]] = wanted.get(product["id"], 0) + qty
        if stock is not None and wanted[product["id"]] > stock:
            left = f"only {stock} left" if stock > 0 else "out of stock"
            return err(409, f"Sorry, {product['name']} is {left}.")
        lines.append(
            {
                "name": f"{product['name']} ({option['label']})",
                "qty": qty,
                "price": option["price"],
                "note": str(raw.get("note") or "")[:300],
                # Kept so the customer can reorder later. Old orders simply do not have these.
                "productId": product["id"],
                "optionIndex": raw["optionIndex"],
            }
        )

    subtotal = sum(line["price"] * line["qty"] for line in lines)
    delivery_fee = await catalogue.delivery_fee()
    total = subtotal + delivery_fee
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    city_s = str(city) if city else ""

    order = {
        "id": new_order_id(),
        "date": now,
        "items": lines,
        "subtotal": subtotal,
        "deliveryFee": delivery_fee,
        "total": total,
        "address": str(address),
        "phone": clean_phone,
        "city": city_s,
        "payMethod": pay_method,
        "paymentDetail": payment_detail if isinstance(payment_detail, dict) else {},
        "status": order_status.INITIAL[pay_method],
        "user": user["email"],
    }
    # Reserve stock first, in one conditional statement per product, so two customers
    # cannot both buy the last item. If any product cannot be reserved, give back what we took.
    reserved: list[tuple[str, int]] = []
    for product_id, qty in wanted.items():
        if not await db.reserve_stock(product_id, qty):
            for pid, q in reserved:
                await db.adjust_stock(pid, q)
            return err(409, "Sorry, one of the items just sold out. Please check your cart.")
        reserved.append((product_id, qty))
    try:
        await db.add_order(order)
    except Exception:
        for pid, q in reserved:
            await db.adjust_stock(pid, q)
        raise

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
