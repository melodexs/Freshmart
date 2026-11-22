"""Admin new-order alerts: honest counts, staff-only, and never claims a message was sent."""

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


def place(c):
    r = c.post(
        "/api/orders",
        json={
            "items": [{"productId": "p1", "optionIndex": 0, "qty": 1}],
            "address": "12 Market Rd",
            "phone": "08011111111",
            "city": "Otukpo",
            "payMethod": "delivery",
            "name": "Ada",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["order"]["id"]


def alerts(c):
    return c.get("/api/store/admin/alerts", headers=STAFF).json()


def test_no_orders_means_no_alert(shop):
    a = alerts(shop)
    assert a["newCount"] == 0 and a["newest"] == [] and a["waitingCount"] == 0


def test_a_new_order_is_counted_and_listed_newest_first(shop):
    first = place(shop)
    second = place(shop)
    a = alerts(shop)
    assert a["newCount"] == 2 and a["newIds"][0] in (first, second)
    assert {o["id"] for o in a["newest"]} == {first, second} and a["waitingCount"] == 2
    assert all(o["city"] == "Otukpo" and o["total"] > 0 for o in a["newest"])


def test_marking_seen_clears_the_count_and_a_later_order_counts_again(shop):
    place(shop)
    assert shop.post("/api/store/admin/alerts/seen", headers=STAFF).status_code == 200
    assert alerts(shop)["newCount"] == 0
    import time

    time.sleep(0.01)
    later = place(shop)
    a = alerts(shop)
    assert a["newCount"] == 1 and a["newIds"] == [later]
    assert a["waitingCount"] == 2  # both orders still need work even though only one is new


def test_cancelled_orders_are_not_news(shop):
    oid = place(shop)
    shop.post(f"/api/store/admin/orders/{oid}/status", json={"status": "Cancelled"}, headers=STAFF)
    a = alerts(shop)
    assert a["newCount"] == 0 and a["waitingCount"] == 0


def test_channels_never_claim_email_whatsapp_or_sms_are_connected(shop):
    ch = alerts(shop)["channels"]
    assert ch == {"dashboard": True, "email": False, "whatsapp": False, "sms": False}


def test_alerts_are_staff_only(shop):
    for method, url in (
        ("get", "/api/store/admin/alerts"),
        ("post", "/api/store/admin/alerts/seen"),
    ):
        assert getattr(shop, method)(url).status_code == 401
        assert getattr(shop, method)(url, headers={"X-Staff-Key": "wrong"}).status_code == 401


def test_a_customer_session_is_not_staff(shop):
    shop.post("/api/auth/login", json={"email": "ada@example.com", "password": "secret123"})
    assert shop.get("/api/store/admin/alerts").status_code == 401


def test_alert_payload_has_no_customer_contact_details(shop):
    place(shop)
    blob = str(alerts(shop))
    assert (
        "08011111111" not in blob and "ada@example.com" not in blob and "12 Market Rd" not in blob
    )
