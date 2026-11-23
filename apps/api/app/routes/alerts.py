"""New-order alerts inside the admin dashboard.

What this is, honestly: a counter and a list of orders placed since staff last looked at the Orders
screen. It is shown only while someone has the admin open. It does not email or message anyone,
because no email, SMS or WhatsApp service is connected. `channels` reports exactly that, so the
dashboard never suggests a notification went out that did not.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from .. import auth, db, mailer, order_status

router = APIRouter(dependencies=[Depends(auth.require_active_staff)])

SEEN_KEY = "orders_seen_at"
# An order the customer can no longer change by cancelling yet still needs staff attention.
NEEDS_ATTENTION = (order_status.AWAITING_PAYMENT, order_status.PAID, order_status.AWAITING)


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def new_orders(orders: list[dict], seen_at: str) -> list[dict]:
    """Orders placed after `seen_at` that are still live (cancelled ones are not news)."""
    return [o for o in orders if o["date"] > seen_at and o["status"] != order_status.CANCELLED]


@router.get("/alerts")
async def alerts():
    seen = await db.get_setting(SEEN_KEY, "") or ""
    orders = await db.get_all_orders()
    fresh = new_orders(orders, seen)
    waiting = [o for o in orders if o["status"] in NEEDS_ATTENTION]
    return {
        "newCount": len(fresh),
        "newest": [
            {
                "id": o["id"],
                "total": o["total"],
                "date": o["date"],
                "status": o["status"],
                "city": o["city"],
            }
            for o in fresh[:5]
        ],
        "newIds": [o["id"] for o in fresh[:200]],
        "waitingCount": len(waiting),
        "seenAt": seen,
        # The truth about delivery outside the dashboard.
        "channels": {
            "dashboard": True,
            "email": mailer.configured(),
            "whatsapp": False,
            "sms": False,
        },
    }


@router.post("/alerts/seen")
async def mark_seen():
    """Staff have looked at the orders. Everything up to now stops counting as new."""
    await db.set_setting(SEEN_KEY, now_iso())
    return {"ok": True}
