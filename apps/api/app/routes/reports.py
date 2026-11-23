"""Sales reports and order export for the admin dashboard.

Money rules (the same ones the overview uses, so the two screens can never disagree):
  * Cancelled orders are never revenue.
  * A pay-ahead order that is still "Awaiting payment" is not revenue yet.
Everything is computed from real orders in the database. Nothing is estimated or invented.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from .. import auth, db, order_status

router = APIRouter(dependencies=[Depends(auth.require_active_staff)])

LAGOS = ZoneInfo("Africa/Lagos")
RANGES = {7, 30, 90}
NOT_REVENUE = (order_status.CANCELLED, order_status.AWAITING_PAYMENT)
PAY_LABEL = {"before": "Pay before delivery", "delivery": "Pay on delivery"}


def lagos_day(iso: str) -> str:
    """The calendar day an order was placed, in Nigerian time (not UTC)."""
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso[:10]
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.astimezone(LAGOS).date().isoformat()


def build_report(orders: list[dict], days: int, today: str) -> dict:
    """Pure function: orders in, report out. `today` is a Lagos date, so tests are deterministic."""
    end = datetime.fromisoformat(today).date()
    series = {}
    for i in range(days - 1, -1, -1):
        d = (end - timedelta(days=i)).isoformat()
        series[d] = {"date": d, "orders": 0, "revenue": 0}
    first = next(iter(series))

    revenue = 0
    counted = 0
    delivery_fees = 0
    discounts = 0
    items_sold = 0
    products: dict[str, dict] = {}
    by_pay: dict[str, dict] = {}
    by_area: dict[str, dict] = {}
    by_status: dict[str, int] = {}
    cancelled = 0

    for o in orders:
        day = lagos_day(o["date"])
        if day < first or day > today:
            continue
        by_status[o["status"]] = by_status.get(o["status"], 0) + 1
        if o["status"] == order_status.CANCELLED:
            cancelled += 1
        if o["status"] in NOT_REVENUE:
            continue
        counted += 1
        revenue += o["total"]
        delivery_fees += o.get("deliveryFee", 0)
        discounts += o.get("discount", 0)
        series[day]["orders"] += 1
        series[day]["revenue"] += o["total"]
        pay = PAY_LABEL.get(o["payMethod"], o["payMethod"])
        p = by_pay.setdefault(pay, {"label": pay, "orders": 0, "revenue": 0})
        p["orders"] += 1
        p["revenue"] += o["total"]
        a = by_area.setdefault(o["city"], {"label": o["city"], "orders": 0, "revenue": 0})
        a["orders"] += 1
        a["revenue"] += o["total"]
        for it in o["items"]:
            items_sold += it["qty"]
            row = products.setdefault(
                it["name"], {"name": it["name"], "units": 0, "revenue": 0, "orders": 0}
            )
            row["units"] += it["qty"]
            row["revenue"] += it["qty"] * it["price"]
            row["orders"] += 1

    def top(rows: dict, key: str, n: int = 10) -> list[dict]:
        return sorted(rows.values(), key=lambda r: (-r[key], r.get("name", r.get("label", ""))))[:n]

    return {
        "days": days,
        "from": first,
        "to": today,
        "revenue": revenue,
        "orders": counted,
        "averageOrder": round(revenue / counted) if counted else 0,
        "itemsSold": items_sold,
        "deliveryFees": delivery_fees,
        "discountsGiven": discounts,
        "cancelled": cancelled,
        "series": list(series.values()),
        "topProducts": top(products, "revenue"),
        "byPayment": top(by_pay, "revenue"),
        "byArea": top(by_area, "revenue"),
        "byStatus": by_status,
    }


def today_lagos() -> str:
    return datetime.now(LAGOS).date().isoformat()


@router.get("/reports")
async def reports(days: int = 30):
    if days not in RANGES:
        return JSONResponse({"error": "Choose 7, 30 or 90 days."}, status_code=400)
    return build_report(await db.get_all_orders(), days, today_lagos())


# A spreadsheet treats a cell starting with = + - @ as a formula. A customer-typed name or address
# could then run something when staff open the export, so such cells are made inert with a quote.
def safe_cell(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


COLUMNS = [
    "Order number", "Date (Lagos)", "Status", "Payment method", "Customer", "Phone", "Email",
    "Area", "Address", "Items", "Subtotal", "Delivery fee", "Discount", "Discount code", "Total",
]  # fmt: skip


def orders_csv(orders: list[dict]) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(COLUMNS)
    for o in orders:
        when = datetime.fromisoformat(o["date"].replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        items = "; ".join(f"{i['qty']} x {i['name']}" for i in o["items"])
        code = (o.get("paymentDetail") or {}).get("discountCode", "")
        row = [
            o["id"], when.astimezone(LAGOS).strftime("%Y-%m-%d %H:%M"), o["status"],
            PAY_LABEL.get(o["payMethod"], o["payMethod"]), o.get("customerName", ""), o["phone"],
            o["user"], o["city"], o["address"], items, o.get("subtotal", ""),
            o.get("deliveryFee", ""), o.get("discount", 0), code, o["total"],
        ]  # fmt: skip
        w.writerow([safe_cell(c) if isinstance(c, str) else c for c in row])
    return out.getvalue()


@router.get("/orders.csv")
async def export_orders(request: Request, status: str = "", days: int = 0):
    orders = await db.get_all_orders()
    if status:
        orders = [o for o in orders if o["status"] == status]
    if days in RANGES:
        first = (
            (datetime.fromisoformat(today_lagos()) - timedelta(days=days - 1)).date().isoformat()
        )
        orders = [o for o in orders if lagos_day(o["date"]) >= first]
    await db.add_audit(
        auth.actor_name(request),
        "orders_exported",
        "orders",
        {"count": len(orders), "status": status, "days": days},
    )
    stamp = datetime.now(LAGOS).strftime("%Y-%m-%d")
    return Response(
        "\ufeff" + orders_csv(orders),  # BOM so Excel reads the naira sign and names correctly
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="ogs-orders-{stamp}.csv"',
            "Cache-Control": "no-store",
        },
    )
