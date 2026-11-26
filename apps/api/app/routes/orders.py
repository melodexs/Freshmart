from __future__ import annotations

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import auth, catalogue, db, discounts, monnify, order_status, payments, ratelimit
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
    # Anything the browser says about payment is ignored: payment is only ever recorded by the
    # server (a verified gateway payment, or an admin confirming receipt).

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
    # Pay before delivery needs somewhere to pay: either the gateway can mint a transfer
    # account, or the store has published its own bank account for manual transfers.
    if pay_method == "before" and not (
        monnify.is_ready() or (await catalogue.bank_details())["ready"]
    ):
        return err(
            409, "Pay before delivery is not available right now. Please choose pay on delivery."
        )
    area = str(city or "").strip() or catalogue.DEFAULT_AREA
    area_fee = await catalogue.fee_for_area(area)
    if area_fee is None:
        return err(
            400, "Sorry, we do not deliver to that area yet. Please choose one from the list."
        )
    customer_name = " ".join(str(body.get("name") or "").split())[:80]
    instructions = " ".join(str(body.get("instructions") or "").split())[:200]

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
    delivery_fee = area_fee
    code_rule, discount = None, 0
    code = discounts.normalise(body.get("discountCode"))
    if code:
        code_rule = await db.get_discount(code)
        used, mine = await db.discount_usage(code, user["email"])
        discount, why = discounts.check(code_rule, subtotal, used, mine)
        if why:
            return err(400, why)
    total = subtotal - discount + delivery_fee
    eta = await catalogue.eta_for_area(area)
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    order = {
        "id": new_order_id(),
        "date": now,
        "items": lines,
        "subtotal": subtotal,
        "discount": discount,
        "deliveryFee": delivery_fee,
        "total": total,
        "address": str(address),
        "phone": clean_phone,
        "city": area,
        "customerName": customer_name,
        "instructions": instructions,
        "payMethod": pay_method,
        "paymentDetail": {
            **({"discountCode": code, "discountAmount": discount} if discount else {}),
            # What the customer was told at checkout, kept as it was even if the store changes it later.
            **({"eta": eta} if eta else {}),
        },
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
    # Claim the code's use last among the checks, in one atomic step, so the last use cannot be taken twice.
    if discount and not await db.claim_discount(code_rule, user["email"], order["id"], discount):
        for pid, q in reserved:
            await db.adjust_stock(pid, q)
        return err(409, "Sorry, that code has just been used up. Please remove it and try again.")
    try:
        await db.add_order(order)
    except Exception:
        for pid, q in reserved:
            await db.adjust_stock(pid, q)
        if discount:
            await db.release_discount(order["id"])
        raise
    for pid, q in reserved:
        product = await db.get_product(pid)
        if product and product.get("stock") is not None:
            await catalogue.log_stock(pid, -q, product["stock"], "Sold", "customer", order["id"])

    # The order exists and its stock is reserved. Only now do we ask for a transfer account, so a
    # gateway hiccup can never leave a phantom order behind: on failure the order is cancelled and
    # its stock released inside attach_account, and the customer is told plainly.
    payment = None
    if pay_method == "before" and monnify.is_ready():
        try:
            await payments.attach_account(order)
        except payments.PaymentSetupError as exc:
            return err(502, str(exc))
        fresh = await db.get_order(order["id"])
        if fresh:
            order = fresh
        payment = payments.public_view(order)

    return {"order": order, "payment": payment}


@router.post("/discount-check")
async def discount_check(request: Request, user: dict = Depends(auth.require_auth)):
    """Show what a code would take off the current cart. Nothing is claimed here."""
    ratelimit.limit(request, "discount-check", 20, 60)  # stops guessing codes
    try:
        body = await request.json()
    except Exception:
        body = {}
    body = body if isinstance(body, dict) else {}
    subtotal = 0
    for raw in body.get("items") if isinstance(body.get("items"), list) else []:
        found = await catalogue.find_option(
            raw.get("productId") if isinstance(raw, dict) else None,
            raw.get("optionIndex") if isinstance(raw, dict) else None,
        )
        qty = raw.get("qty") if isinstance(raw, dict) else None
        if found and isinstance(qty, int) and not isinstance(qty, bool) and 0 < qty <= MAX_QTY:
            subtotal += found[1]["price"] * qty
    code = discounts.normalise(body.get("code"))
    rule = await db.get_discount(code) if code else None
    used, mine = await db.discount_usage(code, user["email"]) if rule else (0, False)
    off, why = discounts.check(rule, subtotal, used, mine)
    if why:
        return JSONResponse({"error": why}, status_code=400)
    return {"code": code, "discount": off, "subtotal": subtotal}


@router.get("/mine")
async def my_orders(user: dict = Depends(auth.require_auth)):
    return {"orders": await db.get_orders_for_user(user["email"])}
