"""Pay-ahead orders are unpaid until payment is verified or an admin confirms receipt, with an audit trail."""

from __future__ import annotations

import pytest

STAFF = {"X-Staff-Key": "staff-secret-key"}
SIGNUP = {
    "name": "Ada",
    "phone": "08011111111",
    "email": "ada@example.com",
    "password": "secret123",
    "passwordConfirm": "secret123",
}
GOOD = {"amount": 4600, "method": "bank transfer", "reference": "TRF-998877"}


@pytest.fixture
def admin(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "STORE_STAFF_KEY", "staff-secret-key")
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    client.post("/api/auth/signup", json=SIGNUP)
    return client


def place(client, pay="before"):
    r = client.post(
        "/api/orders",
        json={
            "items": [{"productId": "p1", "optionIndex": 1, "qty": 2}],
            "address": "12 Market Rd",
            "phone": "08022222222",
            "city": "Otukpo",
            "payMethod": pay,
        },
    )
    return r.json()["order"]


def confirm(client, oid, body=None, headers=STAFF):
    return client.post(
        f"/api/store/admin/orders/{oid}/confirm-payment", json=body or GOOD, headers=headers
    )


def test_a_pay_ahead_order_is_not_paid_when_placed(admin):
    o = place(admin)
    assert o["status"] == "Awaiting payment" and o["total"] == 4600
    assert not (o.get("paymentDetail") or {}).get("paid")


def test_pay_on_delivery_orders_are_unaffected(admin):
    assert place(admin, "delivery")["status"].startswith("Awaiting delivery")


def test_only_staff_can_confirm_payment(admin):
    oid = place(admin)["id"]
    assert confirm(admin, oid, headers={}).status_code == 401, "a signed-in customer is not staff"
    assert confirm(admin, oid, headers={"X-Staff-Key": "wrong"}).status_code == 401
    assert admin.get("/api/orders/mine").json()["orders"][0]["status"] == "Awaiting payment"


def test_confirming_marks_it_paid_and_records_who_how_and_when(admin):
    oid = place(admin)["id"]
    r = confirm(admin, oid)
    assert r.status_code == 200
    o = r.json()["order"]
    assert o["status"] == "Payment confirmed"
    d = o["paymentDetail"]
    assert d["paid"] is True and d["paidAmount"] == 4600 and d["paidMethod"] == "bank transfer"
    assert d["paidReference"] == "TRF-998877" and d["paidAt"].endswith("Z")
    assert d["confirmedBy"] == "Shared staff key"


def test_every_confirmation_is_written_to_the_audit_log(admin):
    oid = place(admin)["id"]
    confirm(admin, oid)
    entries = admin.get(f"/api/store/admin/audit?subject={oid}", headers=STAFF).json()["entries"]
    e = next(x for x in entries if x["action"] == "payment_confirmed")
    assert e["subject"] == oid and e["actor"] == "Shared staff key" and e["at"].endswith("Z")
    assert e["detail"] == {
        "amount": 4600,
        "method": "bank transfer",
        "reference": "TRF-998877",
        "orderTotal": 4600,
    }


def test_the_audit_log_is_staff_only(admin):
    assert admin.get("/api/store/admin/audit").status_code == 401


@pytest.mark.parametrize("amount", [4599, 4601, 1, 460000])
def test_a_wrong_amount_is_refused_and_changes_nothing(admin, amount):
    oid = place(admin)["id"]
    r = confirm(admin, oid, {**GOOD, "amount": amount})
    assert r.status_code == 409 and "does not match" in r.json()["error"]
    assert admin.get("/api/orders/mine").json()["orders"][0]["status"] == "Awaiting payment"
    assert admin.get(f"/api/store/admin/audit?subject={oid}", headers=STAFF).json()["entries"] == []


@pytest.mark.parametrize(
    "patch",
    [
        {"amount": None},
        {"amount": "lots"},
        {"amount": 0},
        {"amount": -4600},
        {"amount": 4600.5},
        {"amount": True},
        {"method": "magic beans"},
        {"method": ""},
        {"reference": ""},
        {"reference": "   "},
    ],
)
def test_bad_confirmation_input_is_rejected(admin, patch):
    oid = place(admin)["id"]
    r = confirm(admin, oid, {**GOOD, **patch})
    assert r.status_code in (400, 409), r.text
    assert admin.get("/api/orders/mine").json()["orders"][0]["status"] == "Awaiting payment"


def test_an_order_cannot_be_confirmed_twice(admin):
    oid = place(admin)["id"]
    assert confirm(admin, oid).status_code == 200
    again = confirm(admin, oid)
    assert again.status_code == 409
    entries = admin.get(f"/api/store/admin/audit?subject={oid}", headers=STAFF).json()["entries"]
    assert [e["action"] for e in entries].count("payment_confirmed") == 1


def test_pay_on_delivery_and_unknown_orders_cannot_be_confirmed(admin):
    cod = place(admin, "delivery")["id"]
    assert confirm(admin, cod).status_code == 409
    assert confirm(admin, "FMNOPE").status_code == 404


def test_a_plain_status_move_cannot_skip_payment(admin):
    """Staff must not be able to push an unpaid order forward without the audited confirmation."""
    oid = place(admin)["id"]
    url = f"/api/store/admin/orders/{oid}/status"
    for target in ("Payment confirmed", "Preparing your order", "Out for delivery", "Delivered"):
        r = admin.post(url, json={"status": target}, headers=STAFF)
        assert r.status_code == 409, f"{target} must not be reachable without confirming payment"
    assert admin.get("/api/orders/mine").json()["orders"][0]["status"] == "Awaiting payment"


def test_the_old_staff_screen_cannot_skip_payment_either(admin):
    oid = place(admin)["id"]
    r = admin.post(
        f"/api/store/ui/orders/{oid}/status",
        data={"status": "Preparing your order"},
        headers=STAFF,
    )
    assert admin.get("/api/orders/mine").json()["orders"][0]["status"] == "Awaiting payment", r.text


def test_after_confirming_the_order_moves_on_normally(admin):
    oid = place(admin)["id"]
    confirm(admin, oid)
    url = f"/api/store/admin/orders/{oid}/status"
    for step in ("Preparing your order", "Ready for dispatch", "Out for delivery", "Delivered"):
        assert admin.post(url, json={"status": step}, headers=STAFF).status_code == 200


def test_unpaid_orders_are_not_counted_as_revenue_until_confirmed(admin):
    oid = place(admin)["id"]
    d = admin.get("/api/store/admin/overview", headers=STAFF).json()
    assert d["revenue"] == 0 and d["todaySales"] == 0 and d["pendingOrders"] == 1
    confirm(admin, oid)
    d = admin.get("/api/store/admin/overview", headers=STAFF).json()
    assert d["revenue"] == 4600 and d["todaySales"] == 4600


def test_a_customer_cancelling_gives_the_stock_back(admin):
    import asyncio

    from app import db

    loop = asyncio.new_event_loop()
    p = loop.run_until_complete(db.get_product("p1"))
    p["stock"] = 10
    loop.run_until_complete(db.save_product(p))
    oid = place(admin)["id"]
    assert loop.run_until_complete(db.get_product("p1"))["stock"] == 8
    assert admin.post(f"/ui/orders/{oid}/cancel").status_code == 200
    assert admin.get("/api/orders/mine").json()["orders"][0]["status"] == "Cancelled"
    assert loop.run_until_complete(db.get_product("p1"))["stock"] == 10, "stock must go back"
