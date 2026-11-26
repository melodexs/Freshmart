"""Monnify pay-before-delivery: account creation, verification and the webhook.

Every Monnify HTTP call is faked here. The point of these tests is the shop's own behaviour:
what is stored, what a customer sees, what may and may not mark an order paid, and that the
existing pay-on-delivery and manual bank transfer paths are untouched.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys

import pytest

SIGNUP = {
    "name": "Ada",
    "phone": "08011111111",
    "email": "ada@example.com",
    "password": "secret123",
    "passwordConfirm": "secret123",
}
ORDER = {
    "items": [{"productId": "p1", "optionIndex": 1, "qty": 2}],
    "address": "12 Market Rd",
    "phone": "08022222222",
    "city": "Otukpo",
}

SECRET = "monnify-test-secret"


class FakeMonnify:
    """Stands in for the network. Records calls so the tests can prove what was asked for."""

    def __init__(self) -> None:
        self.init_calls: list[dict] = []
        self.payment_calls: list[str] = []
        self.queries: list[str] = []
        self.fail_init = False
        self.query_result: dict | None = None
        self.counter = 0

    async def init_transaction(
        self, *, order_id, payment_reference, amount, customer_name, customer_email
    ):
        if self.fail_init:
            from app.monnify import MonnifyError

            raise MonnifyError("Monnify is having a bad day.")
        self.counter += 1
        self.init_calls.append(
            {
                "orderId": order_id,
                "paymentReference": payment_reference,
                "amount": amount,
                "customerEmail": customer_email,
            }
        )
        return {
            "transactionReference": f"MNFY|TEST|{self.counter}",
            "paymentReference": payment_reference,
        }

    async def init_payment(self, transaction_reference):
        self.payment_calls.append(transaction_reference)
        return {
            "accountNumber": f"90000000{len(self.payment_calls):02d}",
            "accountName": "OGS Test-OGS",
            "bankName": "Sterling bank",
            "bankCode": "232",
            "accountDurationSeconds": 2400,
            "expiresOn": "2026-11-26T17:03:06",
        }

    async def query_transaction(self, payment_reference):
        self.queries.append(payment_reference)
        return self.query_result or {
            "paymentReference": payment_reference,
            "paymentStatus": "PENDING",
        }


@pytest.fixture()
def monnify_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_FILE", str(tmp_path / "db.json"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    # A real staff key, so the dev "everyone is staff" shortcut is off and ownership is tested
    # for real.
    monkeypatch.setenv("STORE_STAFF_KEY", "staff-test-key")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("MONNIFY_API_KEY", "MK_TEST_key")
    monkeypatch.setenv("MONNIFY_SECRET_KEY", SECRET)
    monkeypatch.setenv("MONNIFY_CONTRACT_CODE", "9115568354")
    monkeypatch.setenv("MONNIFY_BASE_URL", "https://sandbox.monnify.com")
    for m in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[m]

    from fastapi.testclient import TestClient

    from app import monnify, payments, ratelimit
    from app.main import app

    fake = FakeMonnify()
    monnify.init_transaction = fake.init_transaction
    monnify.init_payment = fake.init_payment
    monnify.query_transaction = fake.query_transaction
    monnify.reset_token_cache()
    payments._LAST_SYNC.clear()
    ratelimit.reset()
    with TestClient(app) as c:
        c.fake = fake
        c.post("/api/auth/signup", json=SIGNUP)
        yield c


def sign_in(client):
    client.post("/api/auth/login", json={"email": SIGNUP["email"], "password": SIGNUP["password"]})


def place(client, **over):
    body = {**ORDER, "payMethod": "before", **over}
    return client.post("/api/orders", json=body)


def signed(payload: dict) -> tuple[bytes, str]:
    raw = json.dumps(payload).encode()
    signature = hmac.new(SECRET.encode(), raw, hashlib.sha512).hexdigest()
    return raw, signature


def webhook(client, payload: dict, signature: str | None = "__sign__"):
    raw, good = signed(payload)
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["monnify-signature"] = good if signature == "__sign__" else signature
    return client.post("/api/webhooks/monnify", content=raw, headers=headers)


def webhook_payload(reference: str, *, status="PAID", amount=1, event="SUCCESSFUL_TRANSACTION"):
    return {
        "eventType": event,
        "eventData": {
            "paymentReference": reference,
            "transactionReference": "MNFY|TEST|1",
            "paymentStatus": status,
            "amountPaid": amount,
            "currency": "NGN",
        },
    }


def order_of(client, order_id):
    import asyncio

    from app import db

    return asyncio.new_event_loop().run_until_complete(db.get_order(order_id))


# ---------- account creation ----------


def test_pay_before_creates_a_one_time_account(monnify_client):
    c = monnify_client
    r = place(c)
    assert r.status_code == 200, r.text
    order = r.json()["order"]
    payment = r.json()["payment"]

    assert order["status"] == "Awaiting payment"
    assert payment["status"] == "PENDING"
    assert payment["accountNumber"].startswith("90000000")
    assert payment["bank"] == "Sterling bank"
    assert payment["accountName"] == "OGS Test-OGS"
    assert payment["amount"] == order["total"]
    assert payment["secondsLeft"] > 2000
    # The amount we asked Monnify for is the server's total, not anything from the browser.
    assert c.fake.init_calls[-1]["amount"] == order["total"]
    assert c.fake.init_calls[-1]["orderId"] == order["id"]


def test_account_is_stored_on_the_order(monnify_client):
    c = monnify_client
    order = place(c).json()["order"]
    stored = order_of(c, order["id"])["paymentDetail"]["monnify"]
    assert stored["paymentReference"].startswith(f"OGS-{order['id']}-")
    assert stored["status"] == "PENDING"
    assert stored["transactionReference"] == "MNFY|TEST|1"


def test_polling_does_not_create_a_second_account(monnify_client):
    c = monnify_client
    order = place(c).json()["order"]
    before = len(c.fake.init_calls)
    for _ in range(2):
        c.get(f"/api/payments/{order['id']}")
    assert len(c.fake.init_calls) == before


def test_valid_account_is_reused_instead_of_churning_references(monnify_client):
    c = monnify_client
    order = place(c).json()["order"]
    reference = order["paymentDetail"]["monnify"]["paymentReference"]
    before = len(c.fake.init_calls)
    again = c.post(f"/api/payments/{order['id']}/new-account")
    assert again.status_code == 200
    assert again.json()["payment"]["paymentReference"] == reference
    assert len(c.fake.init_calls) == before


def test_expired_account_gets_a_new_payment_reference(monnify_client):
    import asyncio

    from app import db

    c = monnify_client
    order = place(c).json()["order"]
    old = order["paymentDetail"]["monnify"]["paymentReference"]
    loop = asyncio.new_event_loop()
    loop.run_until_complete(
        db.merge_payment_detail(
            order["id"], {"monnify": {**order["paymentDetail"]["monnify"], "expiresAtEpoch": 1}}
        )
    )

    fresh = c.post(f"/api/payments/{order['id']}/new-account")
    assert fresh.status_code == 200
    payment = fresh.json()["payment"]
    assert payment["paymentReference"] != old
    assert payment["status"] == "PENDING"
    assert len(c.fake.init_calls) == 2


def test_setup_failure_cancels_the_order_and_releases_stock(monnify_client):
    import asyncio

    from app import db

    c = monnify_client
    loop = asyncio.new_event_loop()
    product = loop.run_until_complete(db.get_product("p1"))
    loop.run_until_complete(db.save_product({**product, "stock": 10}))
    c.fake.fail_init = True

    r = place(c)
    assert r.status_code == 502
    assert "Nothing was charged" in r.json()["error"]

    orders = loop.run_until_complete(db.get_all_orders())
    assert len(orders) == 1
    order = orders[0]
    assert order["status"] == "Cancelled"
    assert order["paymentDetail"]["monnify"]["status"] == "FAILED"
    assert order["paymentDetail"]["stockReleased"] is True
    assert loop.run_until_complete(db.get_product("p1"))["stock"] == 10
    audit = loop.run_until_complete(db.get_audit(order["id"]))
    assert any(a["action"] == "payment_setup_failed" for a in audit)


def test_stock_is_released_only_once(monnify_client):
    import asyncio

    from app import db, payments

    c = monnify_client
    loop = asyncio.new_event_loop()
    product = loop.run_until_complete(db.get_product("p1"))
    loop.run_until_complete(db.save_product({**product, "stock": 5}))
    order = place(c).json()["order"]
    assert loop.run_until_complete(db.get_product("p1"))["stock"] == 3

    loaded = order_of(c, order["id"])
    assert loop.run_until_complete(payments.release_stock(loaded, "test")) is True
    assert loop.run_until_complete(payments.release_stock(loaded, "test")) is False
    assert loop.run_until_complete(db.get_product("p1"))["stock"] == 5


# ---------- webhook ----------


def test_signed_webhook_confirms_the_order(monnify_client):
    c = monnify_client
    order = place(c).json()["order"]
    reference = order["paymentDetail"]["monnify"]["paymentReference"]
    c.fake.query_result = {
        "paymentReference": reference,
        "transactionReference": "MNFY|TEST|1",
        "paymentStatus": "PAID",
        "amountPaid": order["total"],
        "currency": "NGN",
        "paidOn": "2026-11-26T16:30:00",
    }

    r = webhook(c, webhook_payload(reference, amount=order["total"]))
    assert r.status_code == 200

    fresh = order_of(c, order["id"])
    assert fresh["status"] == "Payment confirmed"
    assert fresh["paymentDetail"]["paid"] is True
    assert fresh["paymentDetail"]["paidAmount"] == order["total"]
    assert fresh["paymentDetail"]["monnify"]["status"] == "PAID"


def test_webhook_trusts_the_query_not_the_event_body(monnify_client):
    """The event says PAID; Monnify's own record says PENDING. Nothing is confirmed."""
    c = monnify_client
    order = place(c).json()["order"]
    reference = order["paymentDetail"]["monnify"]["paymentReference"]
    c.fake.query_result = {
        "paymentReference": reference,
        "paymentStatus": "PENDING",
        "amountPaid": 0,
    }

    r = webhook(c, webhook_payload(reference, status="PAID", amount=order["total"]))
    assert r.status_code == 200
    assert order_of(c, order["id"])["status"] == "Awaiting payment"


def test_bad_signature_is_rejected(monnify_client):
    c = monnify_client
    order = place(c).json()["order"]
    reference = order["paymentDetail"]["monnify"]["paymentReference"]
    r = webhook(c, webhook_payload(reference, amount=order["total"]), signature="not-the-signature")
    assert r.status_code == 401
    assert order_of(c, order["id"])["status"] == "Awaiting payment"


def test_missing_signature_is_rejected_outside_the_sandbox(monnify_client, monkeypatch):
    from app import config

    c = monnify_client
    order = place(c).json()["order"]
    reference = order["paymentDetail"]["monnify"]["paymentReference"]
    monkeypatch.setattr(config, "MONNIFY_IS_SANDBOX", False)
    r = webhook(c, webhook_payload(reference, amount=order["total"]), signature=None)
    assert r.status_code == 401
    assert order_of(c, order["id"])["status"] == "Awaiting payment"


def test_duplicate_webhook_is_idempotent(monnify_client):
    c = monnify_client
    order = place(c).json()["order"]
    reference = order["paymentDetail"]["monnify"]["paymentReference"]
    c.fake.query_result = {
        "paymentReference": reference,
        "paymentStatus": "PAID",
        "amountPaid": order["total"],
        "currency": "NGN",
    }
    payload = webhook_payload(reference, amount=order["total"])
    assert webhook(c, payload).status_code == 200
    assert webhook(c, payload).status_code == 200

    audit = order_of(c, order["id"])
    assert audit["paymentDetail"]["paidAmount"] == order["total"]
    import asyncio

    from app import db

    entries = asyncio.new_event_loop().run_until_complete(db.get_audit(order["id"]))
    assert sum(1 for e in entries if e["action"] == "payment_confirmed") == 1


def test_underpayment_does_not_confirm_the_order(monnify_client):
    c = monnify_client
    order = place(c).json()["order"]
    reference = order["paymentDetail"]["monnify"]["paymentReference"]
    c.fake.query_result = {
        "paymentReference": reference,
        "paymentStatus": "PARTIALLY_PAID",
        "amountPaid": order["total"] - 500,
        "currency": "NGN",
    }
    webhook(c, webhook_payload(reference, status="PARTIALLY_PAID", amount=order["total"] - 500))

    fresh = order_of(c, order["id"])
    assert fresh["status"] == "Awaiting payment"
    assert fresh["paymentDetail"]["monnify"]["status"] == "PARTIALLY_PAID"
    assert not fresh["paymentDetail"].get("paid")


def test_overpayment_confirms_and_records_the_difference(monnify_client):
    c = monnify_client
    order = place(c).json()["order"]
    reference = order["paymentDetail"]["monnify"]["paymentReference"]
    paid = order["total"] + 1000
    c.fake.query_result = {
        "paymentReference": reference,
        "paymentStatus": "OVERPAID",
        "amountPaid": paid,
        "currency": "NGN",
    }
    webhook(c, webhook_payload(reference, status="OVERPAID", amount=paid))

    fresh = order_of(c, order["id"])
    assert fresh["status"] == "Payment confirmed"
    assert fresh["paymentDetail"]["monnify"]["status"] == "OVERPAID"
    assert fresh["paymentDetail"]["monnify"]["overpaidBy"] == 1000


def test_currency_mismatch_is_not_settled(monnify_client):
    c = monnify_client
    order = place(c).json()["order"]
    reference = order["paymentDetail"]["monnify"]["paymentReference"]
    c.fake.query_result = {
        "paymentReference": reference,
        "paymentStatus": "PAID",
        "amountPaid": order["total"],
        "currency": "USD",
    }
    webhook(c, webhook_payload(reference, amount=order["total"]))
    assert order_of(c, order["id"])["status"] == "Awaiting payment"


def test_unknown_reference_is_ignored(monnify_client):
    c = monnify_client
    r = webhook(c, webhook_payload("OGS-NOT-OURS-000000", amount=100))
    assert r.status_code == 404


# ---------- the customer-facing poll ----------


def test_poll_returns_the_account_and_a_countdown(monnify_client):
    c = monnify_client
    order = place(c).json()["order"]
    r = c.get(f"/api/payments/{order['id']}")
    assert r.status_code == 200
    payment = r.json()["payment"]
    assert payment["status"] == "PENDING"
    assert payment["accountNumber"] == order["paymentDetail"]["monnify"]["accountNumber"]
    assert payment["secondsLeft"] > 0


def test_another_customer_cannot_read_the_payment(monnify_client):
    c = monnify_client
    order = place(c).json()["order"]
    c.post("/api/auth/logout")
    other = c.post(
        "/api/auth/signup",
        json={**SIGNUP, "email": "bola@example.com", "phone": "08033333333"},
    )
    assert other.status_code == 200
    r = c.get(f"/api/payments/{order['id']}")
    assert r.status_code == 403


# ---------- what must not change ----------


def test_pay_on_delivery_still_places_an_order(monnify_client):
    c = monnify_client
    r = place(c, payMethod="delivery")
    assert r.status_code == 200
    order = r.json()["order"]
    assert order["status"] == "Awaiting delivery — pay on arrival"
    assert r.json()["payment"] is None
    assert c.fake.init_calls == []


def test_manual_bank_transfer_still_works_without_monnify(tmp_path, monkeypatch):
    """With Monnify switched off, pay-ahead falls back to the store's own bank accounts."""
    import asyncio

    monkeypatch.setenv("DATA_FILE", str(tmp_path / "db.json"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("MONNIFY_API_KEY", raising=False)
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    for m in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[m]

    from fastapi.testclient import TestClient

    from app import db
    from app.main import app

    with TestClient(app) as c:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            db.set_setting(
                "bank_details",
                {"bank": "Test Bank", "accountName": "OGS Test", "accountNumber": "0123456789"},
            )
        )
        c.post("/api/auth/signup", json=SIGNUP)
        r = place(c)
        assert r.status_code == 200
        order = r.json()["order"]
        assert order["status"] == "Awaiting payment"
        assert r.json()["payment"] is None
        assert "monnify" not in order["paymentDetail"]
