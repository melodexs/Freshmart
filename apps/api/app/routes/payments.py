"""Payment endpoints for pay-before-delivery (Monnify bank transfer).

Two routers live here:

* ``router`` (``/api/payments``) is for the signed-in customer who owns the order: read the
  current payment state, and ask for a fresh account once the old one expired.
* ``webhook_router`` (``/api/webhooks``) is Monnify calling us. It is the only path that can
  settle a payment without a customer in the loop, and it verifies the signature and the
  transaction itself before anything changes.

Both are rate limited. The webhook limit is applied before the body is read, so a flood of junk
never reaches signature parsing, database lookups or an outbound Monnify call.
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
    if order is None:
        return None, err(404, "That order does not exist.")
    if order.get("user") != user["email"] and not await auth.staff_allowed(request):
        return None, err(403, "That order is not yours.")
    return order, None


@router.get("/{order_id}")
async def payment_status(
    order_id: str, request: Request, user: dict = Depends(auth.require_auth)
) -> JSONResponse:
    """The customer's view of their payment, refreshed from Monnify at most every few seconds."""
    ratelimit.limit(request, "payment-status", 60, 60)
    order, problem = await _owned_order(order_id, request, user)
    if problem is not None:
        return problem
    if order is None:  # pragma: no cover - _owned_order returns one or the other
        return err(404, "That order does not exist.")

    if order.get("payMethod") == "before" and not payments.is_paid(order):
        await payments.expire_stale_reservation(order)
        await payments.sync_status(order, throttle=True)
        fresh = await db.get_order(order_id)
        if fresh is not None:
            order = fresh
    return JSONResponse({"payment": payments.public_view(order)})


@router.post("/{order_id}/new-account")
async def new_account(
    order_id: str, request: Request, user: dict = Depends(auth.require_auth)
) -> JSONResponse:
    """A fresh account for an expired or failed attempt. A live account is never replaced."""
    ratelimit.limit(request, "payment-new-account", 10, 60)
    order, problem = await _owned_order(order_id, request, user)
    if problem is not None:
        return problem
    if order is None:  # pragma: no cover - _owned_order returns one or the other
        return err(404, "That order does not exist.")

    if order.get("payMethod") != "before":
        return err(409, "This order is not paid by bank transfer.")
    if payments.is_paid(order):
        return JSONResponse({"payment": payments.public_view(order)})

    await payments.expire_stale_reservation(order)
    fresh = await db.get_order(order_id) or order
    order = fresh
    if order.get("status") != order_status.AWAITING_PAYMENT:
        return err(409, "This order is no longer awaiting payment.")
    if not payments.can_reissue(order):
        # Still valid, or a part payment is sitting on it: keep the same account.
        return JSONResponse({"payment": payments.public_view(order)})

    try:
        await payments.attach_account(order, force_new=True)
    except payments.PaymentSetupError as exc:
        return err(502, str(exc))
    latest = await db.get_order(order_id) or order
    return JSONResponse({"payment": payments.public_view(latest)})


@webhook_router.post("/monnify")
async def monnify_webhook(request: Request) -> JSONResponse:
    """Monnify's transaction notification. Signed, re-verified, idempotent."""
    ratelimit.limit(request, "monnify-webhook", 60, 60)
    raw = await request.body()
    status, payload = await payments.handle_webhook(raw, request.headers.get("monnify-signature"))
    return JSONResponse(payload, status_code=status)
