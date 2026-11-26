"""The pay-before-delivery payment lifecycle, on top of Monnify.

An order is created first, with stock reserved. Only then is a payment attached:

    paymentReference  ->  init-transaction  ->  init-payment  ->  bank, account, expiry

Everything Monnify told us is kept on the order's ``paymentDetail.monnify`` so that:

* a page refresh or a retried request reuses the account that is still valid (idempotent);
* an expired or failed attempt is replaced by a brand new payment reference;
* the order and its payment status are separate things, and only a server-verified payment
  can move an order to "Payment confirmed".

No function here trusts the browser. The only paths to PAID are a verified webhook and a
server-side query of Monnify, and both end in the same atomic database transition.
"""

from __future__ import annotations

import json
import secrets
import time
from datetime import UTC, datetime

from . import catalogue, config, db, monnify, order_status

PENDING = "PENDING"
PAID = "PAID"
FAILED = "FAILED"
EXPIRED = "EXPIRED"
PARTIALLY_PAID = "PARTIALLY_PAID"
OVERPAID = "OVERPAID"
REVERSED = "REVERSED"
CREATING = "CREATING"

# Polls from the browser are cheap, but not free: one Monnify lookup per order per few seconds.
_SYNC_INTERVAL_SECONDS = 5
_LAST_SYNC: dict[str, float] = {}


class PaymentSetupError(Exception):
    """The transfer account could not be created. The message is safe to show a customer."""


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _attempt(order: dict) -> dict:
    return ((order.get("paymentDetail") or {}).get("monnify")) or {}


def _expires_at(attempt: dict) -> float:
    try:
        return float(attempt.get("expiresAtEpoch") or 0)
    except (TypeError, ValueError):
        return 0.0


def is_expired(attempt: dict, now: float | None = None) -> bool:
    if not attempt:
        return False
    stamp = _expires_at(attempt)
    if not stamp:
        return False
    moment = time.time() if now is None else now
    return moment >= stamp - config.MONNIFY_EXPIRY_MARGIN_SECONDS


def is_paid(order: dict) -> bool:
    detail = order.get("paymentDetail") or {}
    if detail.get("paid"):
        return True
    return _attempt(order).get("status") == PAID


def usable(order: dict) -> bool:
    """A still-valid account the customer can pay into right now."""
    attempt = _attempt(order)
    return (
        bool(attempt.get("accountNumber"))
        and attempt.get("status") == PENDING
        and not is_expired(attempt)
    )


def public_view(order: dict) -> dict | None:
    """What the browser may see. Never contains credentials, only payment instructions."""
    attempt = _attempt(order)
    if not attempt:
        return None
    status = str(attempt.get("status") or PENDING)
    if status == PENDING and is_expired(attempt):
        status = EXPIRED
    seconds_left = 0
    if _expires_at(attempt):
        seconds_left = max(0, int(_expires_at(attempt) - time.time()))
    return {
        "orderId": order.get("id"),
        "status": status,
        "bank": attempt.get("bankName") or "",
        "bankCode": attempt.get("bankCode") or "",
        "accountName": attempt.get("accountName") or "",
        "accountNumber": attempt.get("accountNumber") or "",
        "amount": order.get("total"),
        "paymentReference": attempt.get("paymentReference") or "",
        "transactionReference": attempt.get("transactionReference") or "",
        "expiresOn": attempt.get("expiresOn") or "",
        "secondsLeft": seconds_left,
        "amountPaid": attempt.get("amountPaid"),
        "message": _message_for(status),
    }


def _message_for(status: str) -> str:
    if status == PENDING:
        return (
            "Waiting for your bank transfer. Your order will be processed after payment "
            "confirmation."
        )
    if status == PAID:
        return (
            "Payment received successfully! Your order is confirmed and will be prepared for "
            "delivery."
        )
    if status == EXPIRED:
        return "This payment account has expired. Please request a new payment account."
    if status == PARTIALLY_PAID:
        return (
            "We received less than the order total. Please send the balance to complete your "
            "order, or contact the store."
        )
    if status == OVERPAID:
        return (
            "Payment received. You paid more than the order total; the store will contact you "
            "about the difference."
        )
    if status == REVERSED:
        return "This payment was reversed by the bank. Please pay again or contact the store."
    return "We could not set up your payment. Please request a new payment account."


def new_reference(order_id: str) -> str:
    """Unique, unguessable, and tied to the order for tracing."""
    return f"OGS-{order_id}-{secrets.token_hex(6)}"


# ---------- creating the account ----------


async def attach_account(order: dict, *, force_new: bool = False) -> dict:
    """Make sure this order has a usable transfer account. Idempotent.

    Reuses the stored account while it is valid. Creates a new payment reference when the old
    account expired, failed, or when ``force_new`` is set. If Monnify cannot be reached the order
    is cancelled, its stock released, and ``PaymentSetupError`` is raised: an order is never left
    sitting as if it could be paid when it cannot.
    """
    if not monnify.is_ready():
        raise PaymentSetupError(monnify.disabled_reason() or "Pay before delivery is unavailable.")

    current = _attempt(order)
    if current and not force_new and usable(order):
        return current

    attempt_no = int(current.get("attempt") or 0) + 1
    reference = new_reference(order["id"])
    creating = {
        "paymentReference": reference,
        "status": CREATING,
        "attempt": attempt_no,
        "amount": order.get("total"),
        "createdAt": now_iso(),
    }
    await db.merge_payment_detail(order["id"], {"monnify": creating})
    await db.add_audit(
        "monnify",
        "payment_attempt_created",
        order["id"],
        {"paymentReference": reference, "attempt": attempt_no, "amount": order.get("total")},
    )

    try:
        transaction = await monnify.init_transaction(
            order_id=order["id"],
            payment_reference=reference,
            amount=int(order.get("total") or 0),
            customer_name=_customer_name(order),
            customer_email=str(order.get("user") or ""),
        )
        account = await monnify.init_payment(str(transaction.get("transactionReference")))
    except monnify.MonnifyError as exc:
        await _record_setup_failure(order, reference, attempt_no, str(exc))
        raise PaymentSetupError(
            "We could not set up your bank transfer. Nothing was charged. Please try again or "
            "choose pay on delivery."
        ) from exc

    try:
        seconds = int(account.get("accountDurationSeconds") or config.MONNIFY_ACCOUNT_SECONDS)
    except (TypeError, ValueError):
        seconds = config.MONNIFY_ACCOUNT_SECONDS
    seconds = max(60, min(seconds, config.MONNIFY_ACCOUNT_SECONDS))

    record = {
        "paymentReference": reference,
        "status": PENDING,
        "attempt": attempt_no,
        "amount": order.get("total"),
        "transactionReference": str(transaction.get("transactionReference") or ""),
        "accountNumber": str(account.get("accountNumber") or ""),
        "accountName": str(account.get("accountName") or ""),
        "bankName": str(account.get("bankName") or ""),
        "bankCode": str(account.get("bankCode") or ""),
        "accountDurationSeconds": seconds,
        "expiresOn": account.get("expiresOn") or "",
        "expiresAtEpoch": time.time() + seconds,
        "createdAt": now_iso(),
    }
    await db.merge_payment_detail(order["id"], {"monnify": record})
    await db.add_audit(
        "monnify",
        "payment_account_created",
        order["id"],
        {
            "paymentReference": reference,
            "transactionReference": record["transactionReference"],
            "bank": record["bankName"],
            "accountNumber": record["accountNumber"],
            "expiresOn": record["expiresOn"],
            "attempt": attempt_no,
        },
    )
    order.setdefault("paymentDetail", {})["monnify"] = record
    return record


def _customer_name(order: dict) -> str:
    detail = order.get("paymentDetail") or {}
    name = str(detail.get("_name") or "").strip()
    return name or "OGS customer"


async def _record_setup_failure(order: dict, reference: str, attempt_no: int, why: str) -> None:
    """Keep the failure on the order, release its stock, and stop it looking payable."""
    failed = {
        "paymentReference": reference,
        "status": FAILED,
        "attempt": attempt_no,
        "amount": order.get("total"),
        "lastError": why[:200],
        "failedAt": now_iso(),
    }
    await db.merge_payment_detail(order["id"], {"monnify": failed})
    await db.add_audit(
        "monnify",
        "payment_setup_failed",
        order["id"],
        {"paymentReference": reference, "reason": why[:200], "attempt": attempt_no},
    )
    await release_stock(order, "payment setup failed")
    await db.release_discount(order["id"])
    await db.update_order_status(
        order["id"], order_status.CANCELLED, [order_status.AWAITING_PAYMENT]
    )


async def release_stock(order: dict, reason: str) -> bool:
    """Give reserved stock back, once. The flag on the order makes a second call a no-op."""
    claimed = await db.merge_payment_detail(
        order["id"],
        {"stockReleased": True, "stockReleasedAt": now_iso(), "stockReleasedReason": reason},
        only_if_absent="stockReleased",
    )
    if not claimed:
        return False
    for line in order.get("items") or []:
        product_id = line.get("productId")
        try:
            qty = int(line.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        if not product_id or qty <= 0:
            continue
        left = await db.adjust_stock(product_id, qty)
        if left is not None:
            await catalogue.log_stock(product_id, qty, left, "Released", "system", order["id"])
    return True


# ---------- reading the truth back from Monnify ----------


async def sync_status(order: dict, *, throttle: bool = True) -> dict:
    """Ask Monnify for the payment status and reconcile it. Returns the fresh attempt record."""
    attempt = _attempt(order)
    if not attempt or not monnify.is_ready():
        return attempt
    reference = str(attempt.get("paymentReference") or "")
    if not reference:
        return attempt
    if throttle:
        last = _LAST_SYNC.get(order["id"], 0.0)
        if time.monotonic() - last < _SYNC_INTERVAL_SECONDS:
            return attempt
        _LAST_SYNC[order["id"]] = time.monotonic()
    try:
        data = await monnify.query_transaction(reference)
    except monnify.MonnifyError:
        return attempt
    return await reconcile(order, data, source="monnify-poll")


def _amount(value) -> int:
    try:
        return int(round(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def classify(data: dict, total: int) -> tuple[str, int]:
    """Turn Monnify's record into one of our payment states, plus what was actually paid."""
    raw = str(data.get("paymentStatus") or "").upper()
    paid = _amount(data.get("amountPaid"))
    if raw in (FAILED, EXPIRED, REVERSED):
        return raw, paid
    if paid <= 0:
        return PENDING, paid
    if paid > total:
        return OVERPAID, paid
    if paid == total:
        return PAID, paid
    return PARTIALLY_PAID, paid


async def reconcile(order: dict, data: dict, *, source: str) -> dict:
    """Apply Monnify's record to the order. Idempotent, and never downgrades a paid order."""
    attempt = _attempt(order)
    total = _amount(order.get("total"))
    reference = str(attempt.get("paymentReference") or "")
    seen_reference = str(data.get("paymentReference") or "")
    currency = str(data.get("currency") or data.get("currencyCode") or "").upper()
    seen_transaction = str(data.get("transactionReference") or "")

    if is_paid(order):
        # A retried or late notification for an order we already settled changes nothing.
        await db.add_audit(
            "monnify",
            "payment_already_settled",
            order["id"],
            {
                "source": source,
                "paymentReference": seen_reference,
                "paymentStatus": data.get("paymentStatus"),
            },
        )
        return attempt

    if seen_reference and seen_reference != reference:
        await db.add_audit(
            "monnify",
            "payment_reference_mismatch",
            order["id"],
            {"source": source, "expected": reference, "received": seen_reference},
        )
        return attempt

    if currency and currency != "NGN":
        await db.add_audit(
            "monnify",
            "payment_currency_mismatch",
            order["id"],
            {"source": source, "currency": currency, "paymentReference": seen_reference},
        )
        return attempt

    state, paid = classify(data, total)
    merged = {
        **attempt,
        "status": state,
        "amountPaid": paid,
        "checkedAt": now_iso(),
        "lastSource": source,
    }
    if seen_transaction:
        merged["transactionReference"] = seen_transaction
    if data.get("paidOn"):
        merged["paidOn"] = data.get("paidOn")
    if state == OVERPAID:
        merged["overpaidBy"] = paid - total

    if state in (PAID, OVERPAID):
        record = {
            "paid": True,
            "paidAmount": paid,
            "paidMethod": "monnify",
            "paidReference": seen_transaction or reference,
            "paidAt": data.get("paidOn") or now_iso(),
            "confirmedBy": source,
            "monnify": merged,
        }
        moved = await db.mark_paid_verified(
            order["id"], order_status.AWAITING_PAYMENT, order_status.PAID, record
        )
        if moved:
            await db.add_audit(
                "monnify",
                "payment_confirmed",
                order["id"],
                {
                    "source": source,
                    "paymentReference": reference,
                    "transactionReference": merged.get("transactionReference"),
                    "amountPaid": paid,
                    "orderTotal": total,
                    "overpaid": state == OVERPAID,
                },
            )
        else:
            # Paid, but the order was no longer awaiting payment (cancelled or already handled).
            await db.merge_payment_detail(order["id"], {"monnify": merged})
            await db.add_audit(
                "monnify",
                "payment_received_unmatched",
                order["id"],
                {
                    "source": source,
                    "paymentReference": reference,
                    "amountPaid": paid,
                    "orderStatus": order.get("status"),
                    "note": "Money arrived but the order was not awaiting payment. Check manually.",
                },
            )
        order.setdefault("paymentDetail", {})["monnify"] = merged
        return merged

    await db.merge_payment_detail(order["id"], {"monnify": merged})
    if state in (PARTIALLY_PAID, FAILED, EXPIRED, REVERSED):
        await db.add_audit(
            "monnify",
            f"payment_{state.lower()}",
            order["id"],
            {
                "source": source,
                "paymentReference": reference,
                "amountPaid": paid,
                "orderTotal": total,
            },
        )
    order.setdefault("paymentDetail", {})["monnify"] = merged
    return merged


# ---------- webhook ----------


async def handle_webhook(raw_body: bytes, signature: str | None) -> tuple[int, dict]:
    """Validate, re-verify server side, then settle. Safe to receive twice."""
    if not monnify.is_ready():
        return 503, {"error": monnify.disabled_reason() or "Payments are not configured."}

    signed = monnify.verify_signature(raw_body, signature)
    if not signed:
        if signature:
            return 401, {"error": "Bad signature."}
        # Sandbox deliveries may arrive unsigned. We still refuse to trust them: the payment is
        # re-verified with Monnify below, and this branch is never open in production.
        if not config.MONNIFY_IS_SANDBOX:
            return 401, {"error": "Missing signature."}

    try:
        payload = json.loads(raw_body or b"{}")
    except ValueError:
        return 400, {"error": "Bad payload."}
    if not isinstance(payload, dict):
        return 400, {"error": "Bad payload."}

    event = str(payload.get("eventType") or "").upper()
    data = payload.get("eventData") or {}
    if not isinstance(data, dict):
        return 400, {"error": "Bad payload."}
    reference = str(data.get("paymentReference") or "").strip()
    if not reference:
        return 400, {"error": "No payment reference."}

    order = await db.get_order_by_payment_reference(reference)
    if not order:
        return 404, {"error": "Unknown payment reference."}

    if event and event not in (
        "SUCCESSFUL_TRANSACTION",
        "FAILED_TRANSACTION",
        "REVERSED_TRANSACTION",
        "PENDING_TRANSACTION",
    ):
        # Not a payment event we act on. Acknowledge so Monnify stops retrying.
        return 200, {"status": "ignored"}

    try:
        verified = await monnify.query_transaction(reference)
    except monnify.MonnifyError as exc:
        # We could not confirm it ourselves, so we do not settle. Monnify will retry.
        return 502, {"error": f"Could not verify the payment: {exc}"}

    await reconcile(order, verified, source="monnify-webhook")
    return 200, {"status": "ok"}
