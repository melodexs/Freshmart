"""Order lifecycle: one place that defines every status and which moves are allowed.

Statuses are plain text in the database (no migration needed). Orders placed
before this module existed keep their original text, so those two values are
mapped into the lifecycle below.
"""

from __future__ import annotations

AWAITING_PAYMENT = "Awaiting payment"
PAID = "Payment confirmed"
AWAITING = "Awaiting delivery — pay on arrival"
PREPARING = "Preparing your order"
READY = "Ready for dispatch"
OUT = "Out for delivery"
DELIVERED = "Delivered"
CANCELLED = "Cancelled"

# Statuses an order can start with (set by orders.place_order).
# A pay-ahead order is NOT paid when it is placed. It stays "Awaiting payment" until a payment
# is genuinely verified (Paystack, server side) or an authorised admin confirms receipt.
INITIAL = {"before": AWAITING_PAYMENT, "delivery": AWAITING}

# What staff may move an order to, from each current status.
# "Awaiting payment" -> "Payment confirmed" is deliberately NOT here: confirming payment is its own
# audited action (confirm_payment in the admin API), never a plain status move.
STAFF_NEXT: dict[str, list[str]] = {
    AWAITING_PAYMENT: [CANCELLED],
    PAID: [PREPARING, CANCELLED],
    AWAITING: [PREPARING, CANCELLED],
    PREPARING: [READY, CANCELLED],
    READY: [OUT, CANCELLED],
    OUT: [DELIVERED],
    DELIVERED: [],
    CANCELLED: [],
}

# Customers may cancel only before the order leaves the store.
CUSTOMER_CAN_CANCEL_FROM = [
    AWAITING_PAYMENT,
    PAID,
    AWAITING,
    PREPARING,
]  # not once it is packed and ready

ALL = [AWAITING_PAYMENT, PAID, AWAITING, PREPARING, READY, OUT, DELIVERED, CANCELLED]

# Rough progress for the tracking bar (0 to 100). Cancelled has none.
PROGRESS = {
    AWAITING_PAYMENT: 5,
    PAID: 20,
    AWAITING: 20,
    PREPARING: 45,
    READY: 62,
    OUT: 80,
    DELIVERED: 100,
    CANCELLED: 0,
}


def staff_options(current: str) -> list[str]:
    return STAFF_NEXT.get(current, [])


def staff_may_move(current: str, target: str) -> bool:
    return target in STAFF_NEXT.get(current, [])


def customer_may_cancel(current: str) -> bool:
    return current in CUSTOMER_CAN_CANCEL_FROM


def progress(current: str) -> int:
    return PROGRESS.get(current, 0)


def refund_note(order: dict) -> str | None:
    """A prepaid order that was actually paid needs a manual refund when cancelled."""
    if order.get("payMethod") == "before" and order.get("status") != AWAITING_PAYMENT:
        return "This order was paid ahead. Arrange a refund with the customer."
    return None


def timeline(order: dict) -> list[dict]:
    """The steps a customer sees for an order, each marked done, current or upcoming.

    A pay-on-delivery order has no payment step before delivery, so it is not shown. A cancelled
    order shows a single cancelled step instead of a journey it never took. Times are only shown
    when the system really recorded them (the payment confirmation); nothing is invented.
    """
    status = order.get("status", "")
    if status == CANCELLED:
        return [{"label": "Order cancelled", "state": "cancelled", "when": None}]
    prepaid = order.get("payMethod") == "before"
    detail = order.get("paymentDetail") or {}
    steps = [
        ("Order received", {AWAITING_PAYMENT, PAID, AWAITING, PREPARING, READY, OUT, DELIVERED})
    ]
    if prepaid:
        steps.append(("Payment confirmed", {PAID, PREPARING, READY, OUT, DELIVERED}))
    steps += [
        ("Order processing", {PREPARING, READY, OUT, DELIVERED}),
        ("Ready for dispatch", {READY, OUT, DELIVERED}),
        ("Out for delivery", {OUT, DELIVERED}),
        ("Delivered", {DELIVERED}),
    ]
    # Which step is the current one: the last step whose condition holds, unless delivered.
    reached = [i for i, (_, done_in) in enumerate(steps) if status in done_in]
    current = reached[-1] if reached else 0
    out = []
    for i, (label, _) in enumerate(steps):
        if i < current or (status == DELIVERED and i == current):
            state = "done"
        elif i == current:
            state = "current"
        else:
            state = "upcoming"
        when = None
        if label == "Order received":
            when = order.get("date")
        elif label == "Payment confirmed" and detail.get("paidAt"):
            when = detail["paidAt"]
        out.append({"label": label, "state": state, "when": when})
    if prepaid and status == AWAITING_PAYMENT:
        out[0]["state"] = "done"
        out.insert(1, {"label": "Waiting for your payment", "state": "current", "when": None})
        if len(out) > 2 and out[2]["label"] == "Payment confirmed":
            out[2]["state"] = "upcoming"
    return out
