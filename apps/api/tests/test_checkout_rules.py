"""Checkout rules: delivery areas, real bank details only, and nothing about payment is trusted from the browser."""

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


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def order(client, **over):
    body = {
        "items": [{"productId": "p1", "optionIndex": 0, "qty": 1}],
        "name": "Ada Obi",
        "address": "12 Market Rd",
        "phone": "08022222222",
        "city": "Otukpo",
        "payMethod": "delivery",
        **over,
    }
    return client.post("/api/orders", json=body)


@pytest.fixture
def shop(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "STORE_STAFF_KEY", "staff-secret-key")
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    client.post("/api/auth/signup", json=SIGNUP)
    return client


def set_areas(client, areas):
    return client.put("/api/store/admin/settings", json={"areas": areas}, headers=STAFF)


def test_default_area_uses_the_default_fee(shop):
    o = order(shop).json()["order"]
    assert o["city"] == "Otukpo" and o["deliveryFee"] == 800


def test_each_area_has_its_own_fee_looked_up_on_the_server(shop):
    assert (
        set_areas(
            shop, [{"name": "Otukpo", "fee": 800}, {"name": "Ugbokpo", "fee": 1500}]
        ).status_code
        == 200
    )
    assert order(shop, city="Ugbokpo").json()["order"]["deliveryFee"] == 1500
    assert order(shop, city="ugbokpo").json()["order"]["deliveryFee"] == 1500, (
        "area names ignore case"
    )
    assert order(shop, city="Otukpo").json()["order"]["deliveryFee"] == 800


def test_a_fee_sent_by_the_browser_is_ignored(shop):
    o = order(shop, city="Otukpo", deliveryFee=1, fee=1).json()["order"]
    assert o["deliveryFee"] == 800


def test_an_area_we_do_not_deliver_to_is_refused(shop):
    r = order(shop, city="Lagos")
    assert r.status_code == 400 and "do not deliver" in r.json()["error"]
    assert shop.get("/api/orders/mine").json()["orders"] == []


def test_a_free_delivery_area_is_allowed(shop):
    set_areas(shop, [{"name": "Shop pickup", "fee": 0}])
    o = order(shop, city="Shop pickup").json()["order"]
    assert o["deliveryFee"] == 0 and o["total"] == o["subtotal"]


@pytest.mark.parametrize(
    "areas",
    [
        [],
        "Otukpo",
        [{"name": "", "fee": 100}],
        [{"name": "A", "fee": -1}],
        [{"name": "A", "fee": "free"}],
        [{"name": "A", "fee": 1.5}],
        [{"name": "A", "fee": 10**7}],
        [{"name": "A", "fee": 100}, {"name": "a", "fee": 200}],
        ["not a dict"],
    ],
)
def test_bad_delivery_areas_are_rejected(shop, areas):
    assert set_areas(shop, areas).status_code == 400


def test_areas_are_public_so_checkout_can_list_them(shop):
    set_areas(shop, [{"name": "Otukpo", "fee": 800}, {"name": "Ugbokpo", "fee": 1500}])
    d = shop.get("/api/products").json()
    # Exactly these fields and no others: name, fee and the optional delivery time ("" when unset).
    assert d["areas"] == [
        {"name": "Otukpo", "fee": 800, "eta": ""},
        {"name": "Ugbokpo", "fee": 1500, "eta": ""},
    ]


def test_the_customers_name_and_instructions_are_saved(shop):
    o = order(shop, name="  Ada   Obi ", instructions="Call me at the gate").json()["order"]
    assert o["customerName"] == "Ada Obi" and o["instructions"] == "Call me at the gate"
    mine = shop.get("/api/orders/mine").json()["orders"][0]
    assert mine["customerName"] == "Ada Obi" and mine["instructions"] == "Call me at the gate"


def test_a_pay_ahead_order_cannot_claim_to_be_paid(shop):
    """The browser used to be able to send 'paymentDetail'. It is now ignored completely."""
    o = order(
        shop,
        payMethod="before",
        paymentDetail={"paid": True, "paidAmount": 400, "type": "card", "last4": "4242"},
        paid=True,
        status="Payment confirmed",
    ).json()["order"]
    assert o["status"] == "Awaiting payment"
    assert o["paymentDetail"] == {}


def test_pay_ahead_is_refused_when_no_bank_account_is_set(shop):
    run(__import__("app.db", fromlist=["db"]).set_setting("bank_details", {}))
    r = order(shop, payMethod="before")
    assert r.status_code == 409 and "not available" in r.json()["error"]
    assert order(shop, payMethod="delivery").status_code == 200, "pay on delivery still works"


def test_bank_details_are_admin_set_validated_and_audited(shop):
    good = {"bank": "GTBank", "accountName": "Okwui Grocery", "accountNumber": "0123 456 789"}
    r = shop.put("/api/store/admin/settings", json={"bank": good}, headers=STAFF)
    assert r.status_code == 200 and r.json()["bank"]["accountNumber"] == "0123456789"
    assert r.json()["bank"]["ready"] is True
    log = shop.get("/api/store/admin/audit?subject=settings", headers=STAFF).json()["entries"]
    e = next(x for x in log if x["action"] == "bank_details_changed")
    assert e["detail"]["accountNumberEnding"] == "6789"
    assert "0123456789" not in str(e), "the full account number must not be written to the log"


@pytest.mark.parametrize(
    "bank",
    [
        {"bank": "GTBank", "accountName": "X", "accountNumber": "123"},
        {"bank": "GTBank", "accountName": "X", "accountNumber": "12345678901"},
        {"bank": "GTBank", "accountName": "X", "accountNumber": "abcdefghij"},
        {"bank": "GTBank", "accountName": "", "accountNumber": "0123456789"},
        {"bank": "", "accountName": "X", "accountNumber": "0123456789"},
    ],
)
def test_bad_bank_details_are_rejected(shop, bank):
    assert (
        shop.put("/api/store/admin/settings", json={"bank": bank}, headers=STAFF).status_code == 400
    )


def test_clearing_the_bank_details_turns_pay_ahead_off(shop):
    r = shop.put(
        "/api/store/admin/settings",
        json={"bank": {"bank": "", "accountName": "", "accountNumber": ""}},
        headers=STAFF,
    )
    assert r.status_code == 200 and r.json()["bank"]["ready"] is False
    assert order(shop, payMethod="before").status_code == 409


def test_only_staff_can_change_areas_and_bank_details(shop):
    for body in (
        {"areas": [{"name": "X", "fee": 1}]},
        {"bank": {"bank": "B", "accountName": "N", "accountNumber": "0123456789"}},
    ):
        assert shop.put("/api/store/admin/settings", json=body).status_code == 401


def test_the_storefront_has_no_demo_or_simulated_language(shop):
    html = shop.get("/").text.lower()
    for banned in (
        "demo",
        "simulat",
        "not a live store",
        "no real orders",
        "card number",
        "cvv",
        "otp",
    ):
        assert banned not in html, f"customer page still says '{banned}'"


def test_the_storefront_scripts_have_no_simulated_payment_code():
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "web" / "src"
    assert not (src / "payment.ts").exists()
    text = "\n".join(p.read_text() for p in src.glob("*.ts")).lower()
    for banned in (
        "simulated",
        "demo mode",
        "cardnumber",
        "enter any 6 digits",
        "runcardpaymentflow",
    ):
        assert banned not in text, f"front end still contains '{banned}'"
