"""Order lifecycle: one place that defines every status and which moves are allowed.

Statuses are plain text in the database (no migration needed). Orders placed
before this module existed keep their original text, so those two values are
mapped into the lifecycle below.
"""

from __future__ import annotations

PAID = "Payment confirmed"
AWAITING = "Awaiting delivery — pay on arrival"
PREPARING = "Preparing your order"
OUT = "Out for delivery"
DELIVERED = "Delivered"
CANCELLED = "Cancelled"

# Statuses an order can start with (set by orders.place_order).
INITIAL = {"before": PAID, "delivery": AWAITING}

# What staff may move an order to, from each current status.
STAFF_NEXT: dict[str, list[str]] = {
    PAID: [PREPARING, CANCELLED],
    AWAITING: [PREPARING, CANCELLED],
    PREPARING: [OUT, CANCELLED],
    OUT: [DELIVERED],
    DELIVERED: [],
    CANCELLED: [],
}

# Customers may cancel only before the order leaves the store.
CUSTOMER_CAN_CANCEL_FROM = [PAID, AWAITING, PREPARING]

ALL = [PAID, AWAITING, PREPARING, OUT, DELIVERED, CANCELLED]

# Rough progress for the tracking bar (0 to 100). Cancelled has none.
PROGRESS = {PAID: 20, AWAITING: 20, PREPARING: 45, OUT: 75, DELIVERED: 100, CANCELLED: 0}


def staff_options(current: str) -> list[str]:
    return STAFF_NEXT.get(current, [])


def staff_may_move(current: str, target: str) -> bool:
    return target in STAFF_NEXT.get(current, [])


def customer_may_cancel(current: str) -> bool:
    return current in CUSTOMER_CAN_CANCEL_FROM


def progress(current: str) -> int:
    return PROGRESS.get(current, 0)


def refund_note(order: dict) -> str | None:
    """Prepaid orders need a manual refund when cancelled. Payments are simulated
    here, so this is a reminder for staff, not an automatic refund."""
    if order.get("payMethod") == "before":
        return "This order was paid ahead. Arrange a refund with the customer."
    return None
