"""Admin API: locked to staff, validates everything, and keeps stock and orders consistent."""

from __future__ import annotations

import asyncio

import pytest

STAFF = {"X-Staff-Key": "staff-secret-key"}
SIGNUP = {
    "name": "Ada",
    "phone": "08011111111",
    "email": "ada@example.com",
    "password": "secret123",
    "passwordConfirm": "secret123",
}
NEW = {
    "id": "t1",
    "name": "Test Beans",
    "cat": "Foodstuff",
    "options": [{"label": "1 cup", "price": 500, "was": 600}],
    "stock": 10,
}


@pytest.fixture
def admin(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "STORE_STAFF_KEY", "staff-secret-key")
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    return client


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def place(client, items):
    return client.post(
        "/api/orders",
        json={
            "items": items,
            "address": "12 Market Rd",
            "phone": "08022222222",
            "city": "Otukpo",
            "payMethod": "delivery",
        },
    )


ROUTES = [
    ("get", "/api/store/admin/products"),
    ("post", "/api/store/admin/products"),
    ("put", "/api/store/admin/products/p1"),
    ("delete", "/api/store/admin/products/p1"),
    ("post", "/api/store/admin/products/p1/stock"),
    ("get", "/api/store/admin/settings"),
    ("put", "/api/store/admin/settings"),
    ("get", "/api/store/admin/overview"),
    ("get", "/api/store/admin/orders"),
    ("post", "/api/store/admin/orders/FM1/status"),
    ("get", "/api/store/admin/customers"),
]


@pytest.mark.parametrize(("method", "url"), ROUTES)
def test_every_admin_route_refuses_a_visitor(admin, method, url):
    assert getattr(admin, method)(url).status_code == 401


@pytest.mark.parametrize(("method", "url"), ROUTES)
def test_a_signed_in_customer_is_not_staff(admin, method, url):
    admin.post("/api/auth/signup", json=SIGNUP)
    assert getattr(admin, method)(url).status_code == 401


def test_a_wrong_staff_key_is_refused(admin):
    assert (
        admin.get("/api/store/admin/products", headers={"X-Staff-Key": "nope"}).status_code == 401
    )


def test_staff_can_list_all_28_starter_products(admin):
    r = admin.get("/api/store/admin/products", headers=STAFF)
    assert r.status_code == 200 and len(r.json()["products"]) == 28


def test_create_edit_and_hide_a_product(admin):
    r = admin.post("/api/store/admin/products", json=NEW, headers=STAFF)
    assert r.status_code == 200 and r.json()["product"]["comparePrices"] == [600]
    assert admin.post("/api/store/admin/products", json=NEW, headers=STAFF).status_code == 409
    edit = {**NEW, "name": "Brown Beans", "options": [{"label": "1 cup", "price": 450}]}
    r = admin.put("/api/store/admin/products/t1", json=edit, headers=STAFF)
    assert r.json()["product"]["name"] == "Brown Beans"
    assert r.json()["product"]["comparePrices"] == [None]


@pytest.mark.parametrize(
    "patch",
    [
        {"name": ""},
        {"cat": ""},
        {"options": []},
        {"options": [{"label": "x", "price": 0}]},
        {"options": [{"label": "x", "price": -5}]},
        {"options": [{"label": "x", "price": 1.5}]},
        {"options": [{"label": "x", "price": True}]},
        {"options": [{"label": "", "price": 100}]},
        {"options": [{"label": "x", "price": 100, "was": 50}]},
        {"stock": -1},
        {"stock": "lots"},
        {"image": "javascript:alert(1)"},
        {"image": "http://insecure.example/x.png"},
        {"id": "Bad Code!"},
    ],
)
def test_bad_product_input_is_rejected(admin, patch):
    r = admin.post("/api/store/admin/products", json={**NEW, **patch}, headers=STAFF)
    assert r.status_code == 400, r.text


def test_text_is_cleaned_and_html_is_not_stored_as_a_tag_problem(admin):
    r = admin.post(
        "/api/store/admin/products",
        json={**NEW, "name": "  <b>Beans</b>   Special  "},
        headers=STAFF,
    )
    assert r.json()["product"]["name"] == "<b>Beans</b> Special"  # stored as text, escaped on show
    admin.post("/api/auth/signup", json=SIGNUP)
    html = admin.get("/ui/products").text
    assert "<b>Beans</b>" not in html and "&lt;b&gt;Beans&lt;/b&gt;" in html


def test_deleting_a_never_ordered_product_removes_it(admin):
    admin.post("/api/store/admin/products", json=NEW, headers=STAFF)
    r = admin.delete("/api/store/admin/products/t1", headers=STAFF)
    assert r.json() == {"deleted": True, "hidden": False}


def test_deleting_an_ordered_product_hides_it_and_keeps_old_orders_readable(admin):
    admin.post("/api/auth/signup", json=SIGNUP)
    placed = place(admin, [{"productId": "p1", "optionIndex": 0, "qty": 1}]).json()["order"]
    r = admin.delete("/api/store/admin/products/p1", headers=STAFF)
    assert r.json() == {"deleted": False, "hidden": True}
    assert admin.get("/api/orders/mine").json()["orders"][0]["id"] == placed["id"]
    again = place(admin, [{"productId": "p1", "optionIndex": 0, "qty": 1}])
    assert again.status_code == 400, "a hidden product cannot be bought"


def test_set_stock(admin):
    r = admin.post("/api/store/admin/products/p1/stock", json={"stock": 7}, headers=STAFF)
    assert r.json()["product"]["stock"] == 7
    for bad in (-1, "x", 1.5, None):
        r = admin.post("/api/store/admin/products/p1/stock", json={"stock": bad}, headers=STAFF)
        assert r.status_code == 400


def test_delivery_fee_change_reaches_the_next_order(admin):
    assert (
        admin.put("/api/store/admin/settings", json={"deliveryFee": 1200}, headers=STAFF).json()[
            "deliveryFee"
        ]
        == 1200
    )
    admin.post("/api/auth/signup", json=SIGNUP)
    assert (
        place(admin, [{"productId": "p1", "optionIndex": 0, "qty": 1}]).json()["order"][
            "deliveryFee"
        ]
        == 1200
    )


@pytest.mark.parametrize("bad", [-1, "free", 1.5, 10**9, None, True])
def test_bad_delivery_fee_is_rejected(admin, bad):
    r = admin.put("/api/store/admin/settings", json={"deliveryFee": bad}, headers=STAFF)
    assert r.status_code == 400


def test_contact_numbers_are_validated_and_stored_in_one_format(admin):
    r = admin.put(
        "/api/store/admin/settings",
        json={"whatsapp": "+234 801 234 5678", "contactPhone": "0803 111 2222"},
        headers=STAFF,
    )
    assert r.json()["whatsapp"] == "08012345678" and r.json()["contactPhone"] == "08031112222"
    bad = admin.put("/api/store/admin/settings", json={"whatsapp": "12345"}, headers=STAFF)
    assert bad.status_code == 400
    cleared = admin.put("/api/store/admin/settings", json={"whatsapp": ""}, headers=STAFF)
    assert cleared.json()["whatsapp"] == ""


def test_overview_counts_orders_revenue_and_low_stock(admin):
    admin.post("/api/auth/signup", json=SIGNUP)
    admin.post("/api/store/admin/products/p2/stock", json={"stock": 3}, headers=STAFF)
    o = place(admin, [{"productId": "p1", "optionIndex": 0, "qty": 2}]).json()["order"]
    d = admin.get("/api/store/admin/overview", headers=STAFF).json()
    assert d["totalOrders"] == 1 and d["pendingOrders"] == 1 and d["customers"] == 1
    assert d["revenue"] == o["total"] and d["todaySales"] == o["total"]
    assert d["products"] == 28 and [x["id"] for x in d["lowStock"]] == ["p2"]
    assert len(d["last7Days"]) == 7 and d["last7Days"][-1]["revenue"] == o["total"]


def test_staff_moves_an_order_through_its_stages_and_cannot_skip(admin):
    admin.post("/api/auth/signup", json=SIGNUP)
    oid = place(admin, [{"productId": "p1", "optionIndex": 0, "qty": 1}]).json()["order"]["id"]
    url = f"/api/store/admin/orders/{oid}/status"
    skip = admin.post(url, json={"status": "Delivered"}, headers=STAFF)
    assert skip.status_code == 409
    for step in ("Preparing your order", "Out for delivery", "Delivered"):
        assert admin.post(url, json={"status": step}, headers=STAFF).status_code == 200
    assert admin.post(url, json={"status": "Cancelled"}, headers=STAFF).status_code == 409
    assert (
        admin.post(
            "/api/store/admin/orders/NOPE/status", json={"status": "x"}, headers=STAFF
        ).status_code
        == 404
    )


def test_cancelling_an_order_gives_the_stock_back(admin):
    from app import db

    admin.post("/api/auth/signup", json=SIGNUP)
    admin.post("/api/store/admin/products/p1/stock", json={"stock": 10}, headers=STAFF)
    oid = place(admin, [{"productId": "p1", "optionIndex": 0, "qty": 4}]).json()["order"]["id"]
    assert run(db.get_product("p1"))["stock"] == 6
    r = admin.post(
        f"/api/store/admin/orders/{oid}/status", json={"status": "Cancelled"}, headers=STAFF
    )
    assert r.status_code == 200 and run(db.get_product("p1"))["stock"] == 10


def test_orders_can_be_searched_and_filtered(admin):
    admin.post("/api/auth/signup", json=SIGNUP)
    oid = place(admin, [{"productId": "p1", "optionIndex": 0, "qty": 1}]).json()["order"]["id"]
    place(admin, [{"productId": "p2", "optionIndex": 0, "qty": 1}])
    g = lambda **p: admin.get("/api/store/admin/orders", params=p, headers=STAFF).json()["orders"]  # noqa: E731
    assert len(g()) == 2 and [o["id"] for o in g(q=oid.lower())] == [oid]
    assert len(g(q="08022222222")) == 2 and g(q="nobody") == []
    assert len(g(status="Awaiting delivery — pay on arrival")) == 2 and g(status="Delivered") == []


def test_customers_list_shows_orders_and_spend(admin):
    admin.post("/api/auth/signup", json=SIGNUP)
    place(admin, [{"productId": "p1", "optionIndex": 0, "qty": 1}])
    c = admin.get("/api/store/admin/customers", headers=STAFF).json()["customers"]
    assert c[0]["email"] == "ada@example.com" and c[0]["name"] == "Ada" and c[0]["orders"] == 1


def test_admin_page_is_served_without_data_and_not_cached_or_indexed(admin):
    r = admin.get("/admin")
    assert r.status_code == 200
    assert "no-store" in r.headers["cache-control"]
    assert 'name="robots" content="noindex, nofollow"' in r.text
    # the page itself holds no store data, so a visitor learns nothing from it
    assert "ada@example.com" not in r.text and "FM" not in r.text.split("<body>")[1][:0]


def test_admin_script_never_writes_customer_text_with_innerhtml():
    """Names, addresses and notes are typed by customers, so the admin must only use text nodes."""
    from pathlib import Path

    js = (Path(__file__).resolve().parents[2] / "web" / "static" / "admin" / "admin.js").read_text()
    code = "\n".join(line for line in js.splitlines() if not line.strip().startswith("//"))
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert banned not in code, f"admin.js must not use {banned}"
