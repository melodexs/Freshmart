"""The pay-before-delivery payment lifecycle, on top of Monnify.

An order is created first, with stock reserved. Only then is a payment attached:

    paymentReference  ->  init-transaction  ->  init-payment  ->  bank, account, expiry

Everything Monnify told us is kept on the order's ``paymentDetail.monnify`` so that:

* a page refresh or a retried request reuses the account that is still valid (idempotent);
* an expired or failed attempt is replaced by a brand new payment reference;
* the order and its payment status are separate things, and only a server-verified payment
  can move an order to "Payment confirmed".

Every attempt is also copied into ``paymentDetail.monnify.history``. Money can arrive against an
older account after a replacement, and an old reference must still lead back to its order: losing
that link would lose the evidence of a real payment.

No function here trusts the browser. The only paths to PAID are a verified webhook and a
server-side query of Monnify, and both end in the same atomic database transition.
"""

from __future__ import annotations

import asyncio
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

SETTLED_STATES = (PAID, OVERPAID)

# Polls from the browser are cheap, but not free: one Monnify lookup per order per few seconds.
_SYNC_INTERVAL_SECONDS = 5
_LAST_SYNC: dict[str, float] = {}
_LAST_SYNC_LIMIT = 500
_LAST_SYNC_TTL = 600.0

# One attempt at a time per order, so two clicks cannot mint two accounts.
_LOCK_KEY = "paymentAttemptLock"
_LOCK_STALE_SECONDS = 120

# A temporary Monnify outage must not destroy the order: the stock stays reserved for a while,
# then a sweeper gives it back.
RESERVATION_SECONDS = 15 * 60
TRANSIENT_RETRIES = 1
RETRY_DELAY_SECONDS = 0.4


class PaymentSetupError(Exception):
    """The transfer account could not be created. The message is safe to show a customer."""


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def now_epoch() -> float:
    return time.time()


def _detail(order: dict) -> dict:
    return order.get("paymentDetail") or {}


def _attempt(order: dict) -> dict:
    return (_detail(order).get("monnify")) or {}


def history_of(attempt: dict) -> list[dict]:
    """Every earlier attempt, newest last. Always a list, never the stored object itself."""
    entries = attempt.get("history")
    if not isinstance(entries, list):
        return []
    return [e for e in entries if isinstance(e, dict)]


def attempt_for_reference(attempt: dict, reference: str) -> tuple[dict | None, bool]:
    """The attempt this reference belongs to, and whether it is an older one.

    A payment for an account we have since replaced is still a payment for this order.
    """
    if not reference:
        return None, False
    if str(attempt.get("paymentReference") or "") == reference:
        return attempt, False
    for entry in history_of(attempt):
        if str(entry.get("paymentReference") or "") == reference:
            return entry, True
    return None, False


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
    moment = now_epoch() if now is None else now
    return moment >= stamp - config.MONNIFY_EXPIRY_MARGIN_SECONDS


def is_paid(order: dict) -> bool:
    if _detail(order).get("paid"):
        return True
    return _attempt(order).get("status") in SETTLED_STATES


def usable(order: dict) -> bool:
    """A still-valid account the customer can pay into right now."""
    attempt = _attempt(order)
    return (
        bool(attempt.get("accountNumber"))
        and attempt.get("status") == PENDING
        and not is_expired(attempt)
    )


def can_reissue(order: dict) -> bool:
    """Whether a fresh account would help: the current one is gone, dead, or never existed."""
    attempt = _attempt(order)
    if not attempt:
        return True
    status = str(attempt.get("status") or "")
    if status in (EXPIRED, FAILED, REVERSED):
        return True
    return is_expired(attempt)


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
        seconds_left = max(0, int(_expires_at(attempt) - now_epoch()))
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
        "attempt": attempt.get("attempt"),
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


def _customer_name(order: dict) -> str:
    """The name the customer typed at checkout.

    Postgres keeps it inside paymentDetail._name, the JSON store keeps it at the top level, so
    both are tried and the real name always wins over the generic fallback.
    """
    top = str(order.get("customerName") or "").strip()
    if top:
        return top
    return str(_detail(order).get("_name") or "").strip()


def _closed_entry(attempt: dict, reason: str) -> dict:
    """A history record for an attempt we are replacing. Keeps its evidence, closes it."""
    return {
        "paymentReference": attempt.get("paymentReference") or "",
        "transactionReference": attempt.get("transactionReference") or "",
        "amount": attempt.get("amount"),
        "accountNumber": attempt.get("accountNumber") or "",
        "accountName": attempt.get("accountName") or "",
        "bankName": attempt.get("bankName") or "",
        "expiresOn": attempt.get("expiresOn") or "",
        "createdAt": attempt.get("createdAt") or "",
        "closedAt": now_iso(),
        "closedReason": reason,
        "status": EXPIRED if reason == "expired" else FAILED,
        "amountPaid": attempt.get("amountPaid"),
    }


def _prune_last_sync() -> None:
    """The throttle map is per process and must not grow forever."""
    if len(_LAST_SYNC) <= _LAST_SYNC_LIMIT:
        return
    cutoff = time.monotonic() - _LAST_SYNC_TTL
    for key in [k for k, seen in _LAST_SYNC.items() if seen < cutoff]:
        _LAST_SYNC.pop(key, None)


# ---------- creating the account ----------


async def _claim_attempt(order: dict) -> str | None:
    """Take the per-order attempt lock. None means someone else is already creating one."""
    token = secrets.token_hex(8)
    claim = {"token": token, "epoch": now_epoch(), "at": now_iso()}
    if await db.merge_payment_detail(order["id"], {_LOCK_KEY: claim}, only_if_absent=_LOCK_KEY):
        return token
    fresh = await db.get_order(order["id"]) or order
    held = _detail(fresh).get(_LOCK_KEY) or {}
    try:
        age = now_epoch() - float(held.get("epoch") or 0)
    except (TypeError, ValueError):
        age = _LOCK_STALE_SECONDS + 1
    if age <= _LOCK_STALE_SECONDS:
        return None
    # The holder died mid-flight. Take the lock over rather than leaving the order stuck.
    await db.merge_payment_detail(order["id"], {_LOCK_KEY: claim})
    return token


async def _release_claim(order_id: str, token: str | None) -> None:
    if not token:
        return
    try:
        await db.drop_payment_detail_keys(order_id, [_LOCK_KEY])
    except Exception:  # noqa: BLE001 - a stuck lock must never break a customer's checkout
        pass


async def attach_account(order: dict, *, force_new: bool = False) -> dict:
    """Make sure this order has a usable transfer account. Idempotent.

    Reuses the stored account while it is valid, and creates a new payment reference when the
    old account expired or failed. Only one attempt runs at a time per order. A permanent Monnify
    refusal cancels the order and releases its stock; a temporary outage keeps the order alive
    with a time-limited reservation instead.
    """
    current = _attempt(order)
    if current and not force_new and usable(order):
        return current

    if not monnify.is_ready():
        await _record_setup_failure(
            order, "", int(current.get("attempt") or 0) + 1, monnify.disabled_reason() or ""
        )
        raise PaymentSetupError(
            "Pay before delivery is not available right now. Please choose pay on delivery."
        )

    token = await _claim_attempt(order)
    if token is None:
        fresh = await db.get_order(order["id"]) or order
        if usable(fresh):
            return _attempt(fresh)
        raise PaymentSetupError(
            "We are already setting up your bank transfer. Please give it a moment and refresh."
        )
    try:
        return await _create_attempt(order, current)
    finally:
        await _release_claim(order["id"], token)


async def _create_attempt(order: dict, current: dict) -> dict:
    attempt_no = int(current.get("attempt") or 0) + 1
    reference = new_reference(order["id"])
    history = history_of(current)
    if current.get("paymentReference"):
        history = [*history, _closed_entry(current, "replaced")]

    creating = {
        "paymentReference": reference,
        "status": CREATING,
        "attempt": attempt_no,
        "amount": order.get("total"),
        "createdAt": now_iso(),
        "history": history,
    }
    await db.merge_payment_detail(order["id"], {"monnify": creating})
    await db.add_audit(
        "monnify",
        "payment_attempt_created",
        order["id"],
        {"paymentReference": reference, "attempt": attempt_no, "amount": order.get("total")},
    )

    try:
        transaction = await _init_with_retry(order, reference)
        account = await monnify.init_payment(str(transaction.get("transactionReference")))
    except monnify.MonnifyError as exc:
        if exc.transient:
            await _record_transient_failure(order, reference, attempt_no, str(exc), creating)
            raise PaymentSetupError(
                "The bank did not answer in time. Your order is safe and your items are held: "
                "please try again in a minute."
            ) from exc
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
        **creating,
        "status": PENDING,
        "transactionReference": str(transaction.get("transactionReference") or ""),
        "accountNumber": str(account.get("accountNumber") or ""),
        "accountName": str(account.get("accountName") or ""),
        "bankName": str(account.get("bankName") or ""),
        "bankCode": str(account.get("bankCode") or ""),
        "expiresOn": str(account.get("expiresOn") or ""),
        "accountDurationSeconds": seconds,
        "expiresAtEpoch": now_epoch() + seconds,
        "amount": order.get("total"),
        "history": history,
    }
    await db.merge_payment_detail(
        order["id"],
        {"monnify": record, "reservationExpiresAt": None, "reservationExpiresAtEpoch": None},
    )
    await db.add_audit(
        "monnify",
        "payment_account_issued",
        order["id"],
        {
            "paymentReference": reference,
            "transactionReference": record["transactionReference"],
            "bankName": record["bankName"],
            "accountNumber": record["accountNumber"],
            "expiresOn": record["expiresOn"],
            "attempt": attempt_no,
        },
    )
    order.setdefault("paymentDetail", {})["monnify"] = record
    return record


async def _init_with_retry(order: dict, reference: str) -> dict:
    """One retry for a temporary failure, so a blip does not cost the customer their order."""
    last: monnify.MonnifyError | None = None
    for attempt in range(TRANSIENT_RETRIES + 1):
        try:
            return await monnify.init_transaction(
                order_id=order["id"],
                payment_reference=reference,
                amount=int(order.get("total") or 0),
                customer_name=_customer_name(order),
                customer_email=str(order.get("user") or ""),
            )
        except monnify.MonnifyError as exc:
            last = exc
            if not exc.transient or attempt >= TRANSIENT_RETRIES:
                raise
            await asyncio.sleep(RETRY_DELAY_SECONDS)
    raise last or monnify.MonnifyError("Monnify did not answer.")


async def _record_setup_failure(order: dict, reference: str, attempt_no: int, why: str) -> None:
    """A permanent failure: the order must not sit there looking payable."""
    failed = {
        **_attempt(order),
        "status": FAILED,
        "paymentReference": reference or _attempt(order).get("paymentReference") or "",
        "attempt": attempt_no,
        "lastError": (why or "")[:200],
        "failedAt": now_iso(),
        "transient": False,
    }
    await db.merge_payment_detail(
        order["id"],
        {
            "monnify": failed,
            "reservationExpiresAt": None,
            "reservationExpiresAtEpoch": None,
            "needsReconciliation": None,
        },
    )
    await db.add_audit(
        "monnify",
        "payment_setup_failed",
        order["id"],
        {"paymentReference": reference, "attempt": attempt_no, "reason": (why or "")[:200]},
    )
    await release_stock(order, "payment setup failed")
    await db.release_discount(order["id"])
    await db.update_order_status(
        order["id"], order_status.CANCELLED, [order_status.AWAITING_PAYMENT]
    )


async def _record_transient_failure(
    order: dict, reference: str, attempt_no: int, why: str, creating: dict
) -> None:
    """A temporary outage: keep the order, keep the stock for a while, let them retry."""
    until = now_epoch() + RESERVATION_SECONDS
    failed = {
        **creating,
        "paymentReference": reference,
        "attempt": attempt_no,
        "status": FAILED,
        "transient": True,
        "lastError": (why or "")[:200],
        "failedAt": now_iso(),
        "retryAfter": datetime.fromtimestamp(until, UTC).isoformat().replace("+00:00", "Z"),
    }
    await db.merge_payment_detail(
        order["id"],
        {
            "monnify": failed,
            "reservationExpiresAt": failed["retryAfter"],
            "reservationExpiresAtEpoch": until,
        },
    )
    await db.add_audit(
        "monnify",
        "payment_setup_transient_failure",
        order["id"],
        {
            "paymentReference": reference,
            "attempt": attempt_no,
            "reason": (why or "")[:200],
            "reservedUntil": failed["retryAfter"],
        },
    )


async def expire_stale_reservation(order: dict) -> bool:
    """Cancel and release an order whose payment setup never recovered. Safe to call often."""
    if is_paid(order) or order.get("status") != order_status.AWAITING_PAYMENT:
        return False
    detail = _detail(order)
    try:
        until = float(detail.get("reservationExpiresAtEpoch") or 0)
    except (TypeError, ValueError):
        return False
    if not until or now_epoch() < until:
        return False
    moved = await db.update_order_status(
        order["id"], order_status.CANCELLED, [order_status.AWAITING_PAYMENT]
    )
    if not moved:
        return False
    await release_stock(order, "payment reservation expired")
    await db.release_discount(order["id"])
    await db.add_audit(
        "monnify",
        "payment_reservation_expired",
        order["id"],
        {"reservedUntil": detail.get("reservationExpiresAt"), "note": "Stock released."},
    )
    return True


async def release_stock(order: dict, reason: str) -> bool:
    """Put the order's stock back exactly once, whatever else is happening."""
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
        after = await db.adjust_stock(product_id, qty)
        if after is not None:
            await catalogue.log_stock(product_id, qty, after, "Released", "system", order["id"])
    return True


# ---------- checking a payment ----------


async def sync_status(order: dict, *, throttle: bool = False) -> dict:
    """Ask Monnify for the truth about the current attempt. Never settles on its own word alone."""
    attempt = _attempt(order)
    reference = str(attempt.get("paymentReference") or "")
    if not reference or is_paid(order):
        return attempt
    if throttle:
        _prune_last_sync()
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


def classify(
    data: dict, expected: int, previous_status: str = "", previous_paid=0
) -> tuple[str, int]:
    """Turn Monnify's record into one of our payment states, plus what was actually paid.

    A recorded part payment is never downgraded back to "pending": once money is in, the evidence
    stays until it is fully paid, refunded or reversed.
    """
    raw = str(data.get("paymentStatus") or "").upper()
    paid = _amount(data.get("amountPaid"))
    if raw in (FAILED, EXPIRED, REVERSED):
        return raw, paid
    if paid <= 0:
        if previous_status == PARTIALLY_PAID:
            return PARTIALLY_PAID, _amount(previous_paid)
        return PENDING, paid
    if paid > expected:
        return OVERPAID, paid
    if paid == expected:
        return PAID, paid
    return PARTIALLY_PAID, paid


def _contract_of(data: dict) -> str:
    product = data.get("product")
    if isinstance(product, dict):
        return str(product.get("contractCode") or product.get("contract") or "")
    return ""


def _meta_order_id(data: dict) -> str:
    meta = data.get("metaData")
    if isinstance(meta, dict):
        return str(meta.get("orderId") or "")
    if isinstance(meta, str):
        try:
            parsed = json.loads(meta)
        except ValueError:
            return ""
        if isinstance(parsed, dict):
            return str(parsed.get("orderId") or "")
    return ""


async def _flag_reconciliation(
    order: dict, reference: str, data: dict, reason: str, extra: dict | None = None
) -> None:
    """Keep the money visible for a human instead of guessing what it was for."""
    payload = {
        "reason": reason,
        "paymentReference": reference,
        "paymentStatus": data.get("paymentStatus"),
        "amountPaid": _amount(data.get("amountPaid")),
        "transactionReference": str(data.get("transactionReference") or ""),
        "seenAt": now_iso(),
        **(extra or {}),
    }
    await db.merge_payment_detail(order["id"], {"needsReconciliation": payload})
    await db.add_audit("monnify", reason, order["id"], payload)


def _with_history_status(attempt: dict, reference: str, patch: dict) -> list[dict]:
    updated: list[dict] = []
    for entry in history_of(attempt):
        if str(entry.get("paymentReference") or "") == reference:
            updated.append({**entry, **patch, "historical": True})
        else:
            updated.append(entry)
    return updated


async def reconcile(order: dict, data: dict, *, source: str) -> dict:
    """Apply Monnify's record to the order. Idempotent, and never downgrades a paid order."""
    attempt = _attempt(order)
    total = _amount(order.get("total"))
    seen_reference = str(data.get("paymentReference") or "")
    seen_transaction = str(data.get("transactionReference") or "")
    currency = str(data.get("currency") or data.get("currencyCode") or "").upper()
    method = str(data.get("paymentMethod") or "").upper()

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

    matched, historical = attempt_for_reference(attempt, seen_reference)
    if matched is None:
        await _flag_reconciliation(
            order,
            seen_reference or "(none)",
            data,
            "payment_reference_unknown",
            {"source": source, "known": str(attempt.get("paymentReference") or "")},
        )
        return attempt

    expected = _amount(matched.get("amount") or total) or total
    stored_transaction = str(matched.get("transactionReference") or "")

    # Everything below is a reason to stop and let a human look, never to guess.
    if currency != "NGN":
        await _flag_reconciliation(
            order,
            seen_reference,
            data,
            "payment_currency_mismatch",
            {"source": source, "currency": currency or "(missing)"},
        )
        return attempt
    if method and method != "ACCOUNT_TRANSFER":
        await _flag_reconciliation(
            order,
            seen_reference,
            data,
            "payment_method_mismatch",
            {"source": source, "method": method},
        )
        return attempt
    contract = _contract_of(data)
    if contract and config.MONNIFY_CONTRACT_CODE and contract != config.MONNIFY_CONTRACT_CODE:
        await _flag_reconciliation(
            order,
            seen_reference,
            data,
            "payment_contract_mismatch",
            {"source": source, "contract": contract},
        )
        return attempt
    meta_order = _meta_order_id(data)
    if meta_order and meta_order != order["id"]:
        await _flag_reconciliation(
            order,
            seen_reference,
            data,
            "payment_order_mismatch",
            {"source": source, "orderId": meta_order},
        )
        return attempt
    if stored_transaction and seen_transaction and stored_transaction != seen_transaction:
        await _flag_reconciliation(
            order,
            seen_reference,
            data,
            "payment_transaction_reference_mismatch",
            {
                "source": source,
                "expectedTransactionReference": stored_transaction,
                "receivedTransactionReference": seen_transaction,
            },
        )
        return attempt

    state, paid = classify(
        data, expected, str(matched.get("status") or ""), matched.get("amountPaid")
    )
    patch = {"status": state, "amountPaid": paid, "checkedAt": now_iso(), "lastSource": source}
    if seen_transaction:
        patch["transactionReference"] = seen_transaction
    if data.get("paidOn"):
        patch["paidOn"] = data.get("paidOn")
    if state == OVERPAID:
        patch["overpaidBy"] = paid - expected

    if historical:
        merged = {
            **attempt,
            "history": _with_history_status(attempt, seen_reference, patch),
            "checkedAt": now_iso(),
        }
        if state in SETTLED_STATES:
            merged.update(
                {"status": state, "amountPaid": paid, "settledFromHistorical": seen_reference}
            )
        await db.add_audit(
            "monnify",
            "payment_matched_historical_attempt",
            order["id"],
            {
                "source": source,
                "paymentReference": seen_reference,
                "currentReference": attempt.get("paymentReference"),
                "paymentStatus": state,
                "amountPaid": paid,
            },
        )
    else:
        merged = {**attempt, **patch}

    if state in SETTLED_STATES:
        record = {
            "paid": True,
            "paidAmount": paid,
            "paidMethod": "monnify",
            "paidReference": seen_transaction or seen_reference,
            "paidAt": data.get("paidOn") or now_iso(),
            "confirmedBy": f"monnify ({source})",
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
                    "paymentReference": seen_reference,
                    "transactionReference": merged.get("transactionReference"),
                    "amountPaid": paid,
                    "orderTotal": total,
                    "overpaid": state == OVERPAID,
                    "historicalAttempt": historical,
                },
            )
        else:
            fresh = await db.get_order(order["id"]) or order
            if is_paid(fresh):
                # Another notification got there first. Nothing is wrong; say so plainly.
                await db.add_audit(
                    "monnify",
                    "payment_already_settled",
                    order["id"],
                    {"source": source, "paymentReference": seen_reference, "amountPaid": paid},
                )
            else:
                await db.merge_payment_detail(
                    order["id"],
                    {
                        "monnify": merged,
                        "needsReconciliation": {
                            "reason": "payment_received_unmatched",
                            "paymentReference": seen_reference,
                            "amountPaid": paid,
                            "orderStatus": fresh.get("status"),
                            "seenAt": now_iso(),
                        },
                    },
                )
                await db.add_audit(
                    "monnify",
                    "payment_received_unmatched",
                    order["id"],
                    {
                        "source": source,
                        "paymentReference": seen_reference,
                        "amountPaid": paid,
                        "orderStatus": fresh.get("status"),
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
                "paymentReference": seen_reference,
                "amountPaid": paid,
                "orderTotal": expected,
            },
        )
    order.setdefault("paymentDetail", {})["monnify"] = merged
    return merged


# ---------- webhook ----------

_HANDLED_EVENTS = {
    "SUCCESSFUL_TRANSACTION",
    "FAILED_TRANSACTION",
    "REVERSED_TRANSACTION",
    "PENDING_TRANSACTION",
}


async def handle_webhook(raw_body: bytes, signature: str | None) -> tuple[int, dict]:
    """Validate, re-verify server side, then settle. Safe to receive twice.

    Cheap checks come first: a bad or missing signature is refused before any database or
    outbound call, so unsigned traffic cannot be used to make us talk to Monnify.
    """
    if not monnify.is_ready():
        return 503, {"error": "Payments are not configured."}

    signed = monnify.verify_signature(raw_body, signature)
    if not signed:
        if signature:
            return 401, {"error": "Invalid signature."}
        # Sandbox deliveries can arrive unsigned. The payment is still re-verified below, and
        # this branch cannot be reached outside the sandbox.
        if not config.MONNIFY_IS_SANDBOX:
            return 401, {"error": "Missing signature."}

    try:
        payload = json.loads(raw_body or b"{}")
    except ValueError:
        return 400, {"error": "Malformed notification."}
    if not isinstance(payload, dict):
        return 400, {"error": "Malformed notification."}

    event = str(payload.get("eventType") or "").upper()
    data = payload.get("eventData") or {}
    if not isinstance(data, dict):
        return 400, {"error": "Malformed notification."}
    reference = str(data.get("paymentReference") or "").strip()
    if not reference:
        return 400, {"error": "Malformed notification."}

    order = await db.get_order_by_payment_reference(reference)
    if not order:
        # Answer 200 so Monnify stops retrying a notification we can never match, but leave a
        # trail: this is exactly the case a human has to reconcile.
        await db.add_audit(
            "monnify",
            "payment_reference_unknown",
            reference,
            {
                "source": "monnify-webhook",
                "paymentReference": reference,
                "amountPaid": _amount(data.get("amountPaid")),
                "note": "Notification for a reference no order knows about.",
            },
        )
        return 200, {"status": "ignored"}

    if event and event not in _HANDLED_EVENTS:
        return 200, {"status": "ignored"}

    try:
        verified = await monnify.query_transaction(reference)
    except monnify.MonnifyError:
        return 502, {"error": "Could not verify the payment right now."}

    await reconcile(order, verified, source="monnify-webhook")
    return 200, {"status": "ok"}
