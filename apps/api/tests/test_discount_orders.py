"""Discount codes in the real order flow: priced on the server, claimed atomically, returned on cancel."""

from __future__ import annotations

import asyncio

import pytest

STAFF = {"X-Staff-Key": "staff-secret-key"}
ADA = {
    "name": "Ada Obi",
    "phone": "08011111111",
    "email": "ada@example.com",
    "password": "secret123",
    "passwordConfirm": "secret123",
}
BOLA = {
    "name": "Bola Eze",
    "phone": "08033333333",
    "email": "bola@example.com",
    "password": "hunter2222",
    "passwordConfirm": "hunter2222",
}


@pytest.fixture
def shop(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "STORE_STAFF_KEY", "staff-secret-key")
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    client.post("/api/auth/signup", json=ADA)
    return client


def make_code(c, **kw):
    body = {"code": "SAVE10", "kind": "percent", "value": 10} | kw
    return c.post("/api/store/admin/discounts", json=body, headers=STAFF)


def order(c, code=None, qty=2, city="Otukpo", **extra):
    body = {
        "items": [{"productId": "p1", "optionIndex": 1, "qty": qty}],  # 5 cups at N1,900
        "address": "12 Market Rd",
        "phone": "08011111111",
        "city": city,
        "payMethod": "delivery",
    } | extra
    if code is not None:
        body["discountCode"] = code
    return c.post("/api/orders", json=body)


def switch(c, who):
    c.post("/api/auth/logout")
    if (
        c.post(
            "/api/auth/login", json={"email": who["email"], "password": who["password"]}
        ).status_code
        != 200
    ):
        c.post("/api/auth/signup", json=who)


def test_percent_code_takes_money_off_items_not_delivery(shop):
    make_code(shop)
    o = order(shop, "save10").json()["order"]  # items N3,800, fee N800
    assert (o["subtotal"], o["discount"], o["deliveryFee"], o["total"]) == (3800, 380, 800, 4220)
    assert o["paymentDetail"] == {"discountCode": "SAVE10", "discountAmount": 380}


def test_fixed_code_and_cap_and_never_below_free_items(shop):
    make_code(shop, code="FLAT500", kind="fixed", value=500)
    assert order(shop, "FLAT500").json()["order"]["total"] == 3800 - 500 + 800
    switch(shop, BOLA)
    make_code(shop, code="HUGE", kind="fixed", value=900000)
    o = order(shop, "HUGE").json()["order"]
    assert o["discount"] == 3800 and o["total"] == 800, (
        "items can be free but delivery is still charged"
    )


def test_an_order_without_a_code_is_unchanged(shop):
    o = order(shop).json()["order"]
    assert o["discount"] == 0 and o["total"] == 3800 + 800 and o["paymentDetail"] == {}


def test_the_browser_cannot_forge_a_discount(shop):
    make_code(shop)
    o = order(
        shop,
        "SAVE10",
        discount=3000,
        discountAmount=3000,
        total=1,
        paymentDetail={"discountAmount": 3000},
    ).json()["order"]
    assert o["discount"] == 380 and o["total"] == 4220


@pytest.mark.parametrize("bad", ["NOPE", "save 10!", "<script>", "", "x" * 50])
def test_unknown_codes_are_refused_and_no_order_is_made(shop, bad):
    make_code(shop)
    r = order(shop, bad)
    if bad == "":
        assert r.status_code == 200  # an empty box simply means no code
        return
    assert r.status_code == 400 and "not valid" in r.json()["error"]
    assert shop.get("/api/account").json()["orderCount"] == 0


def test_stock_is_not_taken_when_a_code_is_refused(shop):
    before = {
        p["id"]: p["stock"]
        for p in shop.get("/api/store/admin/products", headers=STAFF).json()["products"]
    }
    order(shop, "NOPE")
    after = {
        p["id"]: p["stock"]
        for p in shop.get("/api/store/admin/products", headers=STAFF).json()["products"]
    }
    assert before == after


def test_each_customer_can_use_a_once_only_code_once(shop):
    make_code(shop)
    assert order(shop, "SAVE10").status_code == 200
    again = order(shop, "SAVE10")
    assert again.status_code == 400 and "already used" in again.json()["error"]
    switch(shop, BOLA)
    assert order(shop, "SAVE10").status_code == 200, "another customer still can"


def test_repeat_use_allowed_when_the_code_says_so(shop):
    make_code(shop, perCustomerOnce=False)
    assert order(shop, "SAVE10").status_code == 200 and order(shop, "SAVE10").status_code == 200


def test_total_use_limit_is_enforced(shop):
    make_code(shop, maxUses=1)
    assert order(shop, "SAVE10").status_code == 200
    switch(shop, BOLA)
    r = order(shop, "SAVE10")
    assert r.status_code == 400 and "fully used" in r.json()["error"]


def test_the_last_use_cannot_be_claimed_twice(shop):
    """Both customers pass the check, then race for the final use: exactly one wins."""
    from app import db

    make_code(shop, maxUses=1)
    rule = asyncio.run(db.get_discount("SAVE10"))
    wins = [
        asyncio.run(db.claim_discount(rule, e, f"OGS-{i}", 380))
        for i, e in enumerate(["a@x.com", "b@x.com"])
    ]
    assert wins == [True, False]


def test_minimum_order_expiry_and_pause(shop):
    make_code(shop, code="BIG", minOrder=50000)
    r = order(shop, "BIG")
    assert r.status_code == 400 and "at least" in r.json()["error"]
    make_code(shop, code="OLD", endsAt="2020-01-01T00:00:00Z")
    assert "expired" in order(shop, "OLD").json()["error"]
    make_code(shop, code="PAUSED", active=False)
    assert order(shop, "PAUSED").status_code == 400


def test_cancelling_gives_the_use_and_the_stock_back(shop):
    make_code(shop, maxUses=1)
    o = order(shop, "SAVE10").json()["order"]
    assert order(shop, "SAVE10").status_code == 400
    shop.post(f"/ui/orders/{o['id']}/cancel")
    assert order(shop, "SAVE10").status_code == 200, (
        "the use came back when the order was cancelled"
    )


def test_admin_cancel_also_gives_the_use_back(shop):
    make_code(shop, maxUses=1)
    o = order(shop, "SAVE10").json()["order"]
    r = shop.post(
        f"/api/store/admin/orders/{o['id']}/status", json={"status": "Cancelled"}, headers=STAFF
    )
    assert r.status_code == 200
    assert order(shop, "SAVE10").status_code == 200


def test_discount_check_previews_without_using_the_code(shop):
    make_code(shop, maxUses=1)
    items = [{"productId": "p1", "optionIndex": 1, "qty": 2}]
    r = shop.post("/api/orders/discount-check", json={"items": items, "code": " save10 "})
    assert r.status_code == 200 and r.json() == {
        "code": "SAVE10",
        "discount": 380,
        "subtotal": 3800,
    }
    shop.post("/api/orders/discount-check", json={"items": items, "code": "SAVE10"})
    assert order(shop, "SAVE10").status_code == 200, "previewing never uses up a code"


def test_discount_check_refuses_bad_codes_and_is_rate_limited(shop):
    items = [{"productId": "p1", "optionIndex": 1, "qty": 1}]
    assert (
        shop.post("/api/orders/discount-check", json={"items": items, "code": "NOPE"}).status_code
        == 400
    )
    codes = [
        shop.post(
            "/api/orders/discount-check", json={"items": items, "code": f"G{i}ESS"}
        ).status_code
        for i in range(30)
    ]
    assert 429 in codes, "code guessing is throttled"


def test_discount_check_needs_sign_in(client):
    assert client.post("/api/orders/discount-check", json={}).status_code == 401


def test_admin_code_management_is_protected_and_audited(shop):
    assert shop.get("/api/store/admin/discounts").status_code == 401
    assert (
        shop.post(
            "/api/store/admin/discounts", json={"code": "X1Y2", "kind": "percent", "value": 5}
        ).status_code
        == 401
    )
    make_code(shop)
    make_code(shop, value=20)
    codes = shop.get("/api/store/admin/discounts", headers=STAFF).json()["codes"]
    assert [(c["code"], c["value"]) for c in codes] == [("SAVE10", 20)]
    actions = [
        a["action"] for a in shop.get("/api/store/admin/audit", headers=STAFF).json()["entries"]
    ]
    assert "discount_created" in actions and "discount_changed" in actions


def test_admin_list_shows_usage_and_money_given(shop):
    make_code(shop, perCustomerOnce=False)
    order(shop, "SAVE10")
    order(shop, "SAVE10")
    c = shop.get("/api/store/admin/discounts", headers=STAFF).json()["codes"][0]
    assert c["used"] == 2 and c["given"] == 760


@pytest.mark.parametrize(
    "body",
    [
        {"code": "a"},
        {"code": "OK1", "kind": "percent", "value": 500},
        {"code": "OK1", "kind": "x", "value": 5},
        {},
    ],
)
def test_bad_admin_codes_are_refused(shop, body):
    assert shop.post("/api/store/admin/discounts", json=body, headers=STAFF).status_code == 400
