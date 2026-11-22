"""Delivery time estimates: optional, validated, kept as promised, and never invented."""

from __future__ import annotations

import re

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


def set_areas(c, areas):
    return c.put("/api/store/admin/settings", json={"areas": areas}, headers=STAFF)


def order(c, area="Otukpo"):
    r = c.post(
        "/api/orders",
        json={
            "items": [{"productId": "p1", "optionIndex": 0, "qty": 1}],
            "address": "12 Market Rd",
            "phone": "08011111111",
            "city": area,
            "payMethod": "delivery",
            "name": "Ada Obi",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["order"]


def track(c, o):
    return c.post("/ui/track", data={"order_id": o["id"], "phone": "08011111111"}).text


def test_existing_areas_have_no_estimate_and_none_is_invented(shop):
    areas = shop.get("/api/products/").json()["areas"]
    assert areas and all(a.get("eta", "") == "" for a in areas)
    o = order(shop)
    assert "eta" not in o["paymentDetail"]
    assert "Estimated delivery" not in track(shop, o)


def test_admin_can_set_an_estimate_and_customers_see_it(shop):
    assert (
        set_areas(
            shop,
            [
                {"name": "Otukpo", "fee": 800, "eta": "1-2 hours"},
                {"name": "Ugbokpo", "fee": 1500, "eta": "Same day"},
            ],
        ).status_code
        == 200
    )
    areas = {a["name"]: a["eta"] for a in shop.get("/api/products/").json()["areas"]}
    assert areas == {"Otukpo": "1-2 hours", "Ugbokpo": "Same day"}
    o = order(shop, "Ugbokpo")
    assert o["paymentDetail"]["eta"] == "Same day"
    assert "Estimated delivery: Same day" in track(shop, o)


def test_the_estimate_is_the_one_promised_at_order_time(shop):
    set_areas(shop, [{"name": "Otukpo", "fee": 800, "eta": "1-2 hours"}])
    o = order(shop)
    set_areas(
        shop, [{"name": "Otukpo", "fee": 800, "eta": "Next day"}]
    )  # the store changes its mind later
    page = track(shop, o)
    assert "Estimated delivery: 1-2 hours" in page and "Next day" not in page


def test_estimate_disappears_once_delivered_or_cancelled(shop):
    set_areas(shop, [{"name": "Otukpo", "fee": 800, "eta": "1-2 hours"}])
    o = order(shop)
    assert "Estimated delivery" in track(shop, o)
    shop.post(
        f"/api/store/admin/orders/{o['id']}/status", json={"status": "Cancelled"}, headers=STAFF
    )
    assert "Estimated delivery" not in track(shop, o)


def test_estimate_is_trimmed_limited_and_stored_as_plain_text(shop):
    long = "x" * 200
    set_areas(
        shop,
        [
            {"name": "Otukpo", "fee": 800, "eta": "   2   hours   "},
            {"name": "B", "fee": 100, "eta": long},
        ],
    )
    got = {
        a["name"]: a["eta"]
        for a in shop.get("/api/store/admin/settings", headers=STAFF).json()["areas"]
    }
    assert got["Otukpo"] == "2 hours" and len(got["B"]) == 40


def test_markup_in_an_estimate_is_escaped_on_the_tracking_page(shop):
    set_areas(shop, [{"name": "Otukpo", "fee": 800, "eta": "<script>alert(1)</script>"}])
    o = order(shop)
    page = track(shop, o)
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page


def test_only_staff_can_change_estimates(shop):
    r = shop.put(
        "/api/store/admin/settings",
        json={"areas": [{"name": "Otukpo", "fee": 800, "eta": "5 minutes"}]},
    )
    assert r.status_code == 401
    assert all(a.get("eta", "") != "5 minutes" for a in shop.get("/api/products/").json()["areas"])


def test_estimate_does_not_change_pricing(shop):
    set_areas(shop, [{"name": "Otukpo", "fee": 800, "eta": "1 hour"}])
    o = order(shop)
    assert o["deliveryFee"] == 800 and o["total"] == o["subtotal"] + 800


def test_existing_orders_without_an_estimate_still_render(shop):
    o = order(shop)
    assert re.search(r"Order|FM", track(shop, o))
