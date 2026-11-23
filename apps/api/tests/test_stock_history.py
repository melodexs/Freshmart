"""Every change to stock leaves a record saying why, so the numbers can always be explained."""

from __future__ import annotations

import pytest

STAFF = {"X-Staff-Key": "staff-secret-key"}
ADA = {
    "name": "Ada Obi",
    "phone": "08011111111",
    "email": "ada@example.com",
    "password": "secret123",
    "passwordConfirm": "secret123",
}


@pytest.fixture
def shop(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "STORE_STAFF_KEY", "staff-secret-key")
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    client.post("/api/auth/signup", json=ADA)
    return client


def stock_of(c, pid="p1"):
    ps = c.get("/api/store/admin/products", headers=STAFF).json()["products"]
    return next(p["stock"] for p in ps if p["id"] == pid)


def moves(c, pid="p1"):
    return c.get(f"/api/store/admin/stock-history?product={pid}", headers=STAFF).json()["moves"]


def place(c, qty=2, pid="p1"):
    return c.post(
        "/api/orders",
        json={
            "items": [{"productId": pid, "optionIndex": 0, "qty": qty}],
            "address": "12 Market Rd",
            "phone": "08011111111",
            "city": "Otukpo",
            "payMethod": "delivery",
        },
    )


def tracked(c, n=10):
    assert (
        c.post("/api/store/admin/products/p1/stock", json={"stock": n}, headers=STAFF).status_code
        == 200
    )


def test_a_sale_is_recorded_with_the_order_and_the_stock_left(shop):
    tracked(shop, 10)
    o = place(shop, 3).json()["order"]
    m = moves(shop)[0]
    assert (m["change"], m["after"], m["reason"], m["orderId"], m["actor"]) == (
        -3,
        7,
        "Sold",
        o["id"],
        "customer",
    )
    assert stock_of(shop) == 7


def test_customer_cancel_puts_it_back_and_says_so(shop):
    tracked(shop, 10)
    o = place(shop, 4).json()["order"]
    shop.post(f"/ui/orders/{o['id']}/cancel")
    m = moves(shop)[0]
    assert (m["change"], m["after"], m["reason"], m["orderId"]) == (
        4,
        10,
        "Order cancelled",
        o["id"],
    )


def test_admin_cancel_is_recorded_as_admin(shop):
    tracked(shop, 10)
    o = place(shop, 2).json()["order"]
    shop.post(
        f"/api/store/admin/orders/{o['id']}/status", json={"status": "Cancelled"}, headers=STAFF
    )
    m = moves(shop)[0]
    assert (m["change"], m["reason"], m["actor"]) == (
        2,
        "Order cancelled by admin",
        "Shared staff key",
    )


def test_admin_correction_records_the_difference(shop):
    tracked(shop, 10)
    shop.post("/api/store/admin/products/p1/stock", json={"stock": 6}, headers=STAFF)
    m = moves(shop)[0]
    assert (m["change"], m["after"], m["reason"], m["actor"]) == (
        -4,
        6,
        "Stock corrected by admin",
        "Shared staff key",
    )


def test_starting_to_track_stock_is_recorded(shop):
    first = moves(shop)
    tracked(shop, 25)
    m = moves(shop)[0]
    assert len(moves(shop)) == len(first) + 1 and (m["change"], m["after"]) == (25, 25)


def test_editing_the_product_form_records_a_stock_change_but_not_other_edits(shop):
    tracked(shop, 10)
    p = next(
        p
        for p in shop.get("/api/store/admin/products", headers=STAFF).json()["products"]
        if p["id"] == "p1"
    )
    body = {k: p[k] for k in ("name", "cat", "description")} | {
        "options": [{"label": o["label"], "price": o["price"]} for o in p["options"]]
    }
    n = len(moves(shop))
    shop.put("/api/store/admin/products/p1", json=body | {"stock": 10}, headers=STAFF)
    assert len(moves(shop)) == n, "nothing changed, so nothing is recorded"
    shop.put("/api/store/admin/products/p1", json=body | {"stock": 15}, headers=STAFF)
    m = moves(shop)[0]
    assert (m["change"], m["after"], m["reason"]) == (5, 15, "Stock edited by admin")


def test_a_new_product_with_stock_is_recorded(shop):
    new = {
        "id": "newitem",
        "name": "Test Item",
        "cat": "Foodstuff",
        "options": [{"label": "1", "price": 500}],
        "stock": 12,
    }
    assert shop.post("/api/store/admin/products", json=new, headers=STAFF).status_code == 200
    m = moves(shop, "newitem")[0]
    assert (m["change"], m["after"], m["reason"]) == (12, 12, "New product added")


def test_untracked_products_leave_no_noise(shop):
    pid = next(
        p["id"]
        for p in shop.get("/api/store/admin/products", headers=STAFF).json()["products"]
        if p["stock"] is None
    )
    place(shop, 1, pid)
    assert moves(shop, pid) == []


def test_a_refused_order_leaves_no_record_and_no_stock_change(shop):
    tracked(shop, 2)
    n = len(moves(shop))
    assert place(shop, 5).status_code == 409
    assert len(moves(shop)) == n and stock_of(shop) == 2


def test_history_adds_up_to_the_current_stock(shop):
    tracked(shop, 20)
    a = place(shop, 3).json()["order"]
    place(shop, 5)
    shop.post(f"/ui/orders/{a['id']}/cancel")
    shop.post("/api/store/admin/products/p1/stock", json={"stock": 30}, headers=STAFF)
    place(shop, 4)
    assert sum(m["change"] for m in moves(shop)) == stock_of(shop) == 26


def test_newest_first_and_all_products_view(shop):
    tracked(shop, 10)
    place(shop, 1)
    allm = shop.get("/api/store/admin/stock-history", headers=STAFF).json()["moves"]
    assert allm[0]["reason"] == "Sold" and allm[0]["name"] == "Local Rice"


def test_limit_is_clamped(shop):
    assert shop.get("/api/store/admin/stock-history?limit=999999", headers=STAFF).status_code == 200
    assert shop.get("/api/store/admin/stock-history?limit=-5", headers=STAFF).status_code == 200


def test_history_is_staff_only(shop):
    assert shop.get("/api/store/admin/stock-history").status_code == 401
    assert (
        shop.get("/api/store/admin/stock-history", headers={"X-Staff-Key": "bad"}).status_code
        == 401
    )
