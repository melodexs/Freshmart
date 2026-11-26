"""Payment endpoints for pay-before-delivery (Monnify bank transfer).

Two routers live here:

* ``router`` (``/api/payments``) is for the signed-in customer who owns the order: read the
  current payment state, and ask for a fresh account once the old one expired.
* ``webhook_router`` (``/api/webhooks``) is Monnify calling us. It is the only path that can
  settle a payment without a customer in the loop, and it verifies the signature and the
  transaction itself before anything changes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import auth, db, order_status, payments, ratelimit

router = APIRouter()
webhook_router = APIRouter()


def err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


async def _owned_order(
    order_id: str, request: Request, user: dict
) -> tuple[dict | None, JSONResponse | None]:
    """The order, but only if this customer owns it or a staff member is asking."""
    order = await db.get_order(order_id)
    if not order:
        return None, err(404, "That order does not exist.")
    if order.get("user") != user["email"] and not await auth.staff_allowed(request):
        return None, err(403, "That order is not yours.")
    return order, None


@router.get("/{order_id}")
async def payment_status(
    order_id: str, request: Request, user: dict = Depends(auth.require_auth)
) -> JSONResponse:
    """Current payment state for one order, refreshed from Monnify (throttled)."""
    ratelimit.limit(request, "payment-status", 60, 60)
    order, problem = await _owned_order(order_id, request, user)
    if problem:
        return problem
    assert order is not None
    if order.get("payMethod") != "before":
        return JSONResponse({"payment": None})

    if not payments.is_paid(order):
        await payments.sync_status(order, throttle=True)
        fresh = await db.get_order(order_id)
        if fresh:
            order = fresh
    return JSONResponse({"payment": payments.public_view(order)})


@router.post("/{order_id}/new-account")
async def new_account(
    order_id: str, request: Request, user: dict = Depends(auth.require_auth)
) -> JSONResponse:
    """Ask for a fresh transfer account after the old one expired or failed.

    Never creates a second order, and never reuses an expired account.
    """
    ratelimit.limit(request, "payment-new-account", 10, 60)
    order, problem = await _owned_order(order_id, request, user)
    if problem:
        return problem
    assert order is not None
    if order.get("payMethod") != "before":
        return err(400, "This order is not paid by bank transfer.")
    if payments.is_paid(order):
        return JSONResponse({"payment": payments.public_view(order)})
    if order.get("status") != order_status.AWAITING_PAYMENT:
        return err(409, "This order is no longer awaiting payment.")
    if payments.usable(order):
        # Still valid: hand back the same account instead of churning references.
        return JSONResponse({"payment": payments.public_view(order)})

    try:
        await payments.attach_account(order, force_new=True)
    except payments.PaymentSetupError as exc:
        return err(502, str(exc))
    fresh = await db.get_order(order_id)
    return JSONResponse({"payment": payments.public_view(fresh or order)})


@webhook_router.post("/monnify")
async def monnify_webhook(request: Request) -> JSONResponse:
    """Monnify's transaction notification.

    The signature is checked against the raw body, and the payment is re-verified with Monnify
    before an order is settled. Duplicate deliveries are harmless.
    """
    raw = await request.body()
    status, payload = await payments.handle_webhook(raw, request.headers.get("monnify-signature"))
    return JSONResponse(payload, status_code=status)
