"""Sales reports and CSV export: exact money maths, Lagos days, staff-only, spreadsheet-safe."""

from __future__ import annotations

import csv
import io

import pytest

from app.routes.reports import build_report, lagos_day, orders_csv, safe_cell

STAFF = {"X-Staff-Key": "staff-secret-key"}


@pytest.fixture(autouse=True)
def staff_on(client, monkeypatch):
    """Run the HTTP tests the way production does: staff access needs the key."""
    from app import config

    monkeypatch.setattr(config, "STORE_STAFF_KEY", "staff-secret-key")
    monkeypatch.setattr(config, "IS_PRODUCTION", True)


def order(
    oid,
    total,
    status="Delivered",
    date="2026-11-20T10:00:00+00:00",
    pay="delivery",
    city="Otukpo",
    items=None,
    fee=800,
    disc=0,
):
    items = items or [{"name": "Local Rice", "qty": 1, "price": total - fee}]
    return {"id": oid, "date": date, "status": status, "payMethod": pay, "city": city, "total": total, "deliveryFee": fee,
            "discount": disc, "items": items, "phone": "08011111111", "user": "a@x.com", "address": "12 Market Rd",
            "customerName": "Ada Obi", "subtotal": total - fee + disc, "paymentDetail": {}}  # fmt: skip


def test_revenue_excludes_cancelled_and_unpaid_pay_ahead():
    orders = [
        order("A", 1800),
        order("B", 2800, status="Out for delivery"),
        order("C", 9999, status="Cancelled"),
        order("D", 7777, status="Awaiting payment", pay="before"),
        order("E", 1300, status="Payment confirmed", pay="before"),
    ]
    r = build_report(orders, 7, "2026-11-21")
    assert r["revenue"] == 1800 + 2800 + 1300
    assert r["orders"] == 3 and r["cancelled"] == 1
    assert r["averageOrder"] == round(5900 / 3)


def test_orders_are_grouped_by_lagos_day_not_utc():
    late = order("L", 1800, date="2026-11-20T23:30:00+00:00")  # 00:30 on the 21st in Lagos (UTC+1)
    assert lagos_day(late["date"]) == "2026-11-21"
    r = build_report([late], 7, "2026-11-21")
    assert r["series"][-1] == {"date": "2026-11-21", "orders": 1, "revenue": 1800}
    assert next(s for s in r["series"] if s["date"] == "2026-11-20")["orders"] == 0


def test_series_has_one_row_per_day_and_old_orders_fall_outside():
    r = build_report([order("O", 1800, date="2026-09-01T10:00:00+00:00")], 30, "2026-11-21")
    assert (
        len(r["series"]) == 30
        and r["series"][0]["date"] == "2026-10-23"
        and r["series"][-1]["date"] == "2026-11-21"
    )
    assert r["revenue"] == 0 and r["orders"] == 0 and r["averageOrder"] == 0  # no divide-by-zero


def test_top_products_units_and_revenue_are_exact():
    a = order(
        "A",
        0,
        items=[{"name": "Rice", "qty": 2, "price": 500}, {"name": "Beans", "qty": 1, "price": 300}],
    )
    a["total"] = 2100
    b = order("B", 0, items=[{"name": "Rice", "qty": 3, "price": 500}])
    b["total"] = 2300
    r = build_report([a, b], 7, "2026-11-21")
    rice = next(p for p in r["topProducts"] if p["name"] == "Rice")
    assert (rice["units"], rice["revenue"], rice["orders"]) == (5, 2500, 2)
    assert r["topProducts"][0]["name"] == "Rice" and r["itemsSold"] == 6


def test_breakdowns_by_payment_and_area_and_fees_and_discounts():
    r = build_report(
        [order("A", 1800, city="Otukpo"), order("B", 1300, pay="before", status="Payment confirmed", city="Ugbokpo", fee=300, disc=100)],
        7, "2026-11-21",
    )  # fmt: skip
    assert {p["label"]: p["revenue"] for p in r["byPayment"]} == {
        "Pay on delivery": 1800,
        "Pay before delivery": 1300,
    }
    assert {a["label"]: a["orders"] for a in r["byArea"]} == {"Otukpo": 1, "Ugbokpo": 1}
    assert r["deliveryFees"] == 1100 and r["discountsGiven"] == 100


def test_csv_neutralises_spreadsheet_formulas():
    assert safe_cell('=HYPERLINK("http://evil")') == '\'=HYPERLINK("http://evil")'
    for bad in ("+1", "-2", "@x", "\t=1"):
        assert safe_cell(bad).startswith("'")
    assert safe_cell("Ada Obi") == "Ada Obi" and safe_cell(None) == ""
    o = order("A", 1800)
    o["customerName"] = "=cmd|' /C calc'!A0"
    row = list(csv.reader(io.StringIO(orders_csv([o]))))[1]
    assert row[4].startswith("'=")


def test_csv_has_every_column_and_correct_values():
    o = order("FM1", 1800, items=[{"name": "Rice", "qty": 2, "price": 500}], disc=0)
    o["paymentDetail"] = {"discountCode": "WELCOME10"}
    rows = list(csv.reader(io.StringIO(orders_csv([o]))))
    head, row = rows
    assert head[0] == "Order number" and head[-1] == "Total" and len(head) == len(row)
    rec = dict(zip(head, row, strict=True))
    assert rec["Order number"] == "FM1" and rec["Items"] == "2 x Rice" and rec["Total"] == "1800"
    assert rec["Date (Lagos)"] == "2026-11-20 11:00" and rec["Discount code"] == "WELCOME10"


# ---- HTTP: staff only ----
def test_reports_and_export_need_the_staff_key(client):
    for url in ("/api/store/admin/reports", "/api/store/admin/orders.csv"):
        assert client.get(url).status_code == 401
        assert client.get(url, headers={"X-Staff-Key": "wrong"}).status_code == 401


def test_reports_endpoint_validates_range(client):
    ok = client.get("/api/store/admin/reports?days=30", headers=STAFF)
    assert ok.status_code == 200 and len(ok.json()["series"]) == 30
    for bad in ("0", "5", "365", "-1"):
        assert client.get(f"/api/store/admin/reports?days={bad}", headers=STAFF).status_code == 400


def test_export_downloads_a_csv_and_is_audited(client):
    r = client.get("/api/store/admin/orders.csv", headers=STAFF)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert (
        "attachment" in r.headers["content-disposition"]
        and r.headers["cache-control"] == "no-store"
    )
    assert r.text.startswith("\ufeffOrder number")
    log = client.get("/api/store/admin/audit", headers=STAFF).json()["entries"]
    assert any(e["action"] == "orders_exported" for e in log)


def test_customers_cannot_reach_reports(client):
    client.post(
        "/api/auth/signup",
        json={
            "name": "Ada Obi",
            "phone": "08011111111",
            "email": "ada@example.com",
            "password": "secret123",
            "passwordConfirm": "secret123",
        },
    )
    assert client.get("/api/store/admin/reports").status_code == 401
    assert client.get("/api/store/admin/orders.csv").status_code == 401
