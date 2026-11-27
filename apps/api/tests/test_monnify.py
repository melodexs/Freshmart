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
        self.fail_init_transient = False
        self.init_delay = 0.0
        self.query_result: dict | None = None
        self.results: dict[str, dict] = {}
        self.counter = 0

    async def init_transaction(
        self, *, order_id, payment_reference, amount, customer_name, customer_email
    ):
        import asyncio

        from app.monnify import MonnifyError

        if self.init_delay:
            await asyncio.sleep(self.init_delay)
        if self.fail_init_transient:
            raise MonnifyError("Monnify is unreachable.", transient=True)
        if self.fail_init:
            raise MonnifyError("Monnify is having a bad day.")
        self.counter += 1
        self.init_calls.append(
            {
                "orderId": order_id,
                "paymentReference": payment_reference,
                "amount": amount,
                "customerEmail": customer_email,
                "customerName": customer_name,
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
        if payment_reference in self.results:
            return self.results[payment_reference]
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
    import asyncio

    from app import db

    c = monnify_client
    r = webhook(c, webhook_payload("OGS-NOT-OURS-000000", amount=100))
    # 200 stops Monnify retrying a reference we can never match; the audit keeps the money visible.
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"
    trail = asyncio.new_event_loop().run_until_complete(db.get_audit("OGS-NOT-OURS-000000"))
    assert any(a["action"] == "payment_reference_unknown" for a in trail)


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


# ---------- correction round: history, validation, resilience ----------


def _expire(client, order):
    """Pretend the account's 40 minutes are up."""
    import asyncio

    from app import db

    loop = asyncio.new_event_loop()
    # Read the attempt back first: a stale copy would quietly drop what it has already received.
    fresh = loop.run_until_complete(db.get_order(order["id"]))
    attempt = ((fresh.get("paymentDetail") or {}).get("monnify")) or {}
    loop.run_until_complete(
        db.merge_payment_detail(order["id"], {"monnify": {**attempt, "expiresAtEpoch": 1}})
    )
    return attempt["paymentReference"]


def _audit(order_id):
    import asyncio

    from app import db

    return asyncio.new_event_loop().run_until_complete(db.get_audit(order_id))


def _paid_result(reference, amount, **over):
    """What Monnify's query returns for a settled transfer. The webhook settles on this, not the
    event body, so every test that expects settlement sets it."""
    # The transaction reference is only included when a test asks for one: a default value
    # would look like a mismatch to an attempt that legitimately has a different reference.
    return {
        "paymentReference": reference,
        "paymentStatus": "PAID",
        "amountPaid": amount,
        "currency": "NGN",
        "paymentMethod": "ACCOUNT_TRANSFER",
        **over,
    }


def test_late_payment_to_a_replaced_account_still_settles(monnify_client):
    """The reviewer's H1: money sent to an account we replaced must still find its order."""
    c = monnify_client
    order = place(c).json()["order"]
    old_reference = _expire(c, order)

    fresh = c.post(f"/api/payments/{order['id']}/new-account")
    assert fresh.status_code == 200
    assert fresh.json()["payment"]["paymentReference"] != old_reference

    c.fake.results[old_reference] = _paid_result(old_reference, order["total"])
    r = webhook(c, webhook_payload(old_reference, amount=order["total"]))
    assert r.status_code == 200

    stored = order_of(c, order["id"])
    assert stored["status"] == "Payment confirmed"
    assert stored["paymentDetail"]["paid"] is True
    assert stored["paymentDetail"]["paidAmount"] == order["total"]
    actions = [a["action"] for a in _audit(order["id"])]
    assert "payment_matched_historical_attempt" in actions
    assert "payment_confirmed" in actions


def test_history_keeps_the_replaced_attempt(monnify_client):
    c = monnify_client
    order = place(c).json()["order"]
    old_reference = _expire(c, order)
    c.post(f"/api/payments/{order['id']}/new-account")

    stored = order_of(c, order["id"])["paymentDetail"]["monnify"]
    history = stored["history"]
    assert len(history) == 1
    assert history[0]["paymentReference"] == old_reference
    assert history[0]["closedReason"] == "replaced"
    assert history[0]["accountNumber"]
    assert history[0]["amount"] == order["total"]


def test_historical_reference_is_findable_in_the_json_store(monnify_client):
    import asyncio

    from app import db

    c = monnify_client
    order = place(c).json()["order"]
    old_reference = _expire(c, order)
    c.post(f"/api/payments/{order['id']}/new-account")

    loop = asyncio.new_event_loop()
    assert (
        loop.run_until_complete(db.get_order_by_payment_reference(old_reference))["id"]
        == order["id"]
    )
    current = order_of(c, order["id"])["paymentDetail"]["monnify"]["paymentReference"]
    assert loop.run_until_complete(db.get_order_by_payment_reference(current))["id"] == order["id"]


def test_concurrent_account_requests_create_one_attempt(monnify_client):
    """Two clicks must not mint two Monnify transactions."""
    import asyncio

    from app import payments

    c = monnify_client
    order = place(c).json()["order"]
    _expire(c, order)
    c.fake.init_delay = 0.05
    before = len(c.fake.init_calls)
    loaded = order_of(c, order["id"])

    async def both():
        return await asyncio.gather(
            payments.attach_account(loaded, force_new=True),
            payments.attach_account(loaded, force_new=True),
            return_exceptions=True,
        )

    results = asyncio.new_event_loop().run_until_complete(both())
    assert len(c.fake.init_calls) == before + 1
    assert any(isinstance(r, payments.PaymentSetupError) for r in results)


def test_contract_mismatch_is_not_settled(monnify_client):
    c = monnify_client
    order = place(c).json()["order"]
    reference = order["paymentDetail"]["monnify"]["paymentReference"]
    c.fake.query_result = _paid_result(
        reference, order["total"], product={"contractCode": "9999999999"}
    )
    assert webhook(c, webhook_payload(reference, amount=order["total"])).status_code == 200

    stored = order_of(c, order["id"])
    assert stored["status"] == "Awaiting payment"
    assert stored["paymentDetail"]["needsReconciliation"]["reason"] == "payment_contract_mismatch"


def test_payment_method_mismatch_is_not_settled(monnify_client):
    c = monnify_client
    order = place(c).json()["order"]
    reference = order["paymentDetail"]["monnify"]["paymentReference"]
    c.fake.query_result = _paid_result(reference, order["total"], paymentMethod="CARD")
    webhook(c, webhook_payload(reference, amount=order["total"]))

    stored = order_of(c, order["id"])
    assert stored["status"] == "Awaiting payment"
    assert stored["paymentDetail"]["needsReconciliation"]["reason"] == "payment_method_mismatch"


def test_transaction_reference_mismatch_is_not_settled(monnify_client):
    c = monnify_client
    order = place(c).json()["order"]
    reference = order["paymentDetail"]["monnify"]["paymentReference"]
    c.fake.query_result = _paid_result(
        reference, order["total"], transactionReference="MNFY|SOMETHING|ELSE"
    )
    webhook(c, webhook_payload(reference, amount=order["total"]))

    stored = order_of(c, order["id"])
    assert stored["status"] == "Awaiting payment"
    reason = stored["paymentDetail"]["needsReconciliation"]["reason"]
    assert reason == "payment_transaction_reference_mismatch"


def test_json_store_sends_the_customer_name(monnify_client):
    """M3: the JSON store kept the name at the top level, so Monnify got 'OGS customer'."""
    c = monnify_client
    place(c, name="Ada Okwudiri")
    assert c.fake.init_calls[-1]["customerName"] == "Ada Okwudiri"


def test_transient_outage_keeps_the_order_and_its_stock(monnify_client):
    import asyncio

    from app import db, payments

    payments.RETRY_DELAY_SECONDS = 0
    c = monnify_client
    loop = asyncio.new_event_loop()
    product = loop.run_until_complete(db.get_product("p1"))
    loop.run_until_complete(db.save_product({**product, "stock": 10}))
    c.fake.fail_init_transient = True

    r = place(c)
    assert r.status_code == 502
    assert "did not answer" in r.json()["error"]

    order = loop.run_until_complete(db.get_all_orders())[0]
    assert order["status"] == "Awaiting payment"
    assert order["paymentDetail"]["monnify"]["status"] == "FAILED"
    assert order["paymentDetail"]["monnify"]["transient"] is True
    assert order["paymentDetail"]["reservationExpiresAtEpoch"] > 0
    assert order["paymentDetail"].get("stockReleased") is None
    assert loop.run_until_complete(db.get_product("p1"))["stock"] == 8

    # The customer tries again once the bank is back.
    c.fake.fail_init_transient = False
    again = c.post(f"/api/payments/{order['id']}/new-account")
    assert again.status_code == 200
    assert again.json()["payment"]["status"] == "PENDING"
    assert again.json()["payment"]["accountNumber"]


def test_expired_reservation_releases_stock_and_cancels(monnify_client):
    import asyncio

    from app import db, payments

    payments.RETRY_DELAY_SECONDS = 0
    c = monnify_client
    loop = asyncio.new_event_loop()
    product = loop.run_until_complete(db.get_product("p1"))
    loop.run_until_complete(db.save_product({**product, "stock": 10}))
    c.fake.fail_init_transient = True
    place(c)
    order = loop.run_until_complete(db.get_all_orders())[0]
    loop.run_until_complete(db.merge_payment_detail(order["id"], {"reservationExpiresAtEpoch": 1}))

    loaded = order_of(c, order["id"])
    assert loop.run_until_complete(payments.expire_stale_reservation(loaded)) is True
    after = order_of(c, order["id"])
    assert after["status"] == "Cancelled"
    assert after["paymentDetail"]["stockReleased"] is True
    assert loop.run_until_complete(db.get_product("p1"))["stock"] == 10


def test_partial_payment_then_balance_settles(monnify_client):
    c = monnify_client
    order = place(c).json()["order"]
    reference = order["paymentDetail"]["monnify"]["paymentReference"]
    half = order["total"] // 2

    c.fake.query_result = _paid_result(reference, half, paymentStatus="PARTIALLY_PAID")
    webhook(c, webhook_payload(reference, amount=half))
    stored = order_of(c, order["id"])
    assert stored["status"] == "Awaiting payment"
    assert stored["paymentDetail"]["monnify"]["status"] == "PARTIALLY_PAID"
    assert not stored["paymentDetail"].get("paid")

    c.fake.query_result = _paid_result(reference, order["total"])
    webhook(c, webhook_payload(reference, amount=order["total"]))
    stored = order_of(c, order["id"])
    assert stored["status"] == "Payment confirmed"
    assert stored["paymentDetail"]["paidAmount"] == order["total"]


def test_part_payment_is_never_downgraded_to_pending(monnify_client):
    """L3: an empty later record must not erase a part payment we already recorded."""
    import asyncio

    from app import payments

    c = monnify_client
    order = place(c).json()["order"]
    reference = order["paymentDetail"]["monnify"]["paymentReference"]
    c.fake.query_result = _paid_result(
        reference, order["total"] // 2, paymentStatus="PARTIALLY_PAID"
    )
    webhook(c, webhook_payload(reference, amount=order["total"] // 2))

    loaded = order_of(c, order["id"])
    loop = asyncio.new_event_loop()
    merged = loop.run_until_complete(
        payments.reconcile(
            loaded,
            {
                "paymentReference": reference,
                "paymentStatus": "PENDING",
                "amountPaid": 0,
                "currency": "NGN",
            },
            source="monnify-poll",
        )
    )
    assert merged["status"] == "PARTIALLY_PAID"
    assert merged["amountPaid"] == order["total"] // 2


def test_duplicate_settlement_is_not_mislabelled(monnify_client):
    """L2: the loser of a settlement race is a duplicate, not an unmatched payment."""
    c = monnify_client
    order = place(c).json()["order"]
    reference = order["paymentDetail"]["monnify"]["paymentReference"]
    c.fake.query_result = _paid_result(reference, order["total"])
    webhook(c, webhook_payload(reference, amount=order["total"]))
    webhook(c, webhook_payload(reference, amount=order["total"]))

    actions = [a["action"] for a in _audit(order["id"])]
    assert "payment_received_unmatched" not in actions
    assert actions.count("payment_confirmed") == 1
    assert "payment_already_settled" in actions


def test_webhook_is_rate_limited(monnify_client):
    """M6: junk traffic is refused before it can cost a database or Monnify call."""
    c = monnify_client
    statuses = []
    for _ in range(61):
        statuses.append(
            webhook(c, webhook_payload("OGS-JUNK", amount=1), signature="bad").status_code
        )
    assert statuses[0] == 401
    assert statuses[-1] == 429


def test_payment_instructions_appear_in_the_order_history(monnify_client):
    """M9: the account number must survive the checkout modal being closed."""
    c = monnify_client
    order = place(c).json()["order"]
    number = order["paymentDetail"]["monnify"]["accountNumber"]

    page = c.get("/ui/orders")
    assert page.status_code == 200
    assert number in page.text
    assert "Copy account number" in page.text
    assert "Sterling bank" in page.text


def test_unavailable_monnify_cleans_up_the_order(monnify_client, monkeypatch):
    """L8: if Monnify goes away between checkout and account creation, nothing is left dangling."""
    import asyncio

    from app import db, monnify

    c = monnify_client
    loop = asyncio.new_event_loop()
    product = loop.run_until_complete(db.get_product("p1"))
    loop.run_until_complete(db.save_product({**product, "stock": 10}))
    order = place(c).json()["order"]
    _expire(c, order)

    monkeypatch.setattr(monnify, "is_ready", lambda: False)
    r = c.post(f"/api/payments/{order['id']}/new-account")
    assert r.status_code == 502

    after = order_of(c, order["id"])
    assert after["status"] == "Cancelled"
    assert after["paymentDetail"]["stockReleased"] is True
    assert loop.run_until_complete(db.get_product("p1"))["stock"] == 10


def test_last_sync_map_is_pruned():
    """L5: the per-process throttle map must not grow forever."""
    import time

    from app import payments

    payments._LAST_SYNC.clear()
    stale = time.monotonic() - payments._LAST_SYNC_TTL - 60
    for i in range(payments._LAST_SYNC_LIMIT + 50):
        payments._LAST_SYNC[f"old-{i}"] = stale
    payments._prune_last_sync()
    assert len(payments._LAST_SYNC) == 0

    # A fresh entry is kept: pruning must never forget an order that was just checked.
    payments._LAST_SYNC.clear()
    for i in range(payments._LAST_SYNC_LIMIT + 50):
        payments._LAST_SYNC[f"old-{i}"] = stale
    payments._LAST_SYNC["just-now"] = time.monotonic()
    payments._prune_last_sync()
    assert list(payments._LAST_SYNC) == ["just-now"]


def test_token_is_refreshed_after_a_401(monkeypatch):
    """M1: a 401 must throw the cached token away, sign in again and retry with the new one."""
    import asyncio
    import sys

    for m in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[m]
    monkeypatch.setenv("MONNIFY_API_KEY", "MK_TEST_key")
    monkeypatch.setenv("MONNIFY_SECRET_KEY", SECRET)
    monkeypatch.setenv("MONNIFY_CONTRACT_CODE", "9115568354")
    monkeypatch.setenv("MONNIFY_BASE_URL", "https://sandbox.monnify.com")
    monkeypatch.setenv("JWT_SECRET", "test-secret")

    from app import monnify

    sent: list[str] = []
    logins = {"n": 0}

    def fake_request(method, url, payload, headers):
        auth = headers.get("Authorization", "")
        if url.endswith("/api/v1/auth/login"):
            logins["n"] += 1
            return 200, {
                "requestSuccessful": True,
                "responseBody": {"accessToken": f"FRESH{logins['n']}", "expiresIn": 3599},
            }
        sent.append(auth)
        if auth == "Bearer STALE":
            return 401, {"requestSuccessful": False, "responseMessage": "token expired"}
        return 200, {"requestSuccessful": True, "responseBody": {"paymentStatus": "PENDING"}}

    monkeypatch.setattr(monnify, "_request_sync", fake_request)
    monnify._TOKEN["value"] = "STALE"
    import time

    monnify._TOKEN["expires_at"] = time.monotonic() + 3000

    body = asyncio.new_event_loop().run_until_complete(monnify.query_transaction("REF"))
    assert body == {"paymentStatus": "PENDING"}
    assert sent == ["Bearer STALE", "Bearer FRESH1"]
    assert logins["n"] == 1


def test_token_lock_survives_a_second_event_loop(monkeypatch):
    """L10: the lock must belong to the loop in use, not to whichever loop imported first."""
    import asyncio
    import sys

    for m in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[m]
    monkeypatch.setenv("MONNIFY_API_KEY", "MK_TEST_key")
    monkeypatch.setenv("MONNIFY_SECRET_KEY", SECRET)
    monkeypatch.setenv("MONNIFY_CONTRACT_CODE", "9115568354")
    monkeypatch.setenv("MONNIFY_BASE_URL", "https://sandbox.monnify.com")
    monkeypatch.setenv("JWT_SECRET", "test-secret")

    from app import monnify

    calls = {"n": 0}

    def fake_request(method, url, payload, headers):
        calls["n"] += 1
        return 200, {
            "requestSuccessful": True,
            "responseBody": {"accessToken": f"T{calls['n']}", "expiresIn": 3599},
        }

    monkeypatch.setattr(monnify, "_request_sync", fake_request)

    def token_in_fresh_loop():
        monnify.reset_token_cache()
        return asyncio.new_event_loop().run_until_complete(monnify.access_token())

    first = token_in_fresh_loop()
    second = token_in_fresh_loop()
    assert first == "T1"
    assert second == "T2"


def test_poll_keeps_working_after_a_part_payment(monnify_client):
    """M8: a part payment is still an open payment, so polling and refresh stay available."""
    c = monnify_client
    order = place(c).json()["order"]
    reference = order["paymentDetail"]["monnify"]["paymentReference"]
    c.fake.query_result = _paid_result(
        reference, order["total"] // 2, paymentStatus="PARTIALLY_PAID"
    )
    webhook(c, webhook_payload(reference, amount=order["total"] // 2))

    view = c.get(f"/api/payments/{order['id']}").json()["payment"]
    assert view["status"] == "PARTIALLY_PAID"
    assert view["accountNumber"]

    # The same live account is kept: no churn, no second Monnify transaction.
    before = len(c.fake.init_calls)
    again = c.post(f"/api/payments/{order['id']}/new-account")
    assert again.status_code == 200
    assert again.json()["payment"]["paymentReference"] == reference
    assert len(c.fake.init_calls) == before


# ---------- second correction round: cumulative money, history, sweeps ----------


def _half(order):
    return order["total"] // 2


def test_partial_on_old_account_then_full_on_new_flags_the_excess(monnify_client):
    """N2: the reproduced failure. 2,300 on the old account plus 4,600 on the new one."""
    c = monnify_client
    order = place(c).json()["order"]
    total = order["total"]
    first = _expire(c, order)

    c.fake.results[first] = _paid_result(first, total // 2, paymentStatus="PARTIALLY_PAID")
    assert webhook(c, webhook_payload(first, amount=total // 2)).status_code == 200
    assert order_of(c, order["id"])["paymentDetail"]["monnify"]["status"] == "PARTIALLY_PAID"

    fresh = c.post(f"/api/payments/{order['id']}/new-account").json()["payment"]
    second = fresh["paymentReference"]
    c.fake.results[second] = _paid_result(second, total)
    assert webhook(c, webhook_payload(second, amount=total)).status_code == 200

    stored = order_of(c, order["id"])
    detail = stored["paymentDetail"]
    assert stored["status"] == "Payment confirmed", detail
    assert detail["paidAmount"] == total + total // 2
    assert detail["needsReconciliation"]["reason"] == "payment_overpaid"
    assert detail["needsReconciliation"]["overpaidBy"] == total // 2
    actions = [a["action"] for a in _audit(order["id"])]
    assert "payment_overpaid" in actions


def test_two_partial_payments_across_attempts_settle_the_order(monnify_client):
    c = monnify_client
    order = place(c).json()["order"]
    total = order["total"]
    first = _expire(c, order)

    c.fake.results[first] = _paid_result(first, 2000, paymentStatus="PARTIALLY_PAID")
    webhook(c, webhook_payload(first, amount=2000))
    second = c.post(f"/api/payments/{order['id']}/new-account").json()["payment"][
        "paymentReference"
    ]
    c.fake.results[second] = _paid_result(second, total - 2000, paymentStatus="PARTIALLY_PAID")
    webhook(c, webhook_payload(second, amount=total - 2000))

    stored = order_of(c, order["id"])
    assert stored["status"] == "Payment confirmed"
    assert stored["paymentDetail"]["paidAmount"] == total
    assert not stored["paymentDetail"].get("needsReconciliation")


def test_duplicate_webhook_does_not_double_count_a_receipt(monnify_client):
    c = monnify_client
    order = place(c).json()["order"]
    reference = order["paymentDetail"]["monnify"]["paymentReference"]
    c.fake.results[reference] = _paid_result(reference, order["total"])
    payload = webhook_payload(reference, amount=order["total"])
    assert webhook(c, payload).status_code == 200
    assert webhook(c, payload).status_code == 200

    detail = order_of(c, order["id"])["paymentDetail"]
    assert detail["paidAmount"] == order["total"]
    assert not detail.get("needsReconciliation")


def test_replaced_attempt_that_received_money_is_not_labelled_failed(monnify_client):
    c = monnify_client
    order = place(c).json()["order"]
    first = _expire(c, order)
    c.fake.results[first] = _paid_result(first, 1500, paymentStatus="PARTIALLY_PAID")
    webhook(c, webhook_payload(first, amount=1500))
    c.post(f"/api/payments/{order['id']}/new-account")

    history = order_of(c, order["id"])["paymentDetail"]["monnify"]["history"]
    assert history[0]["paymentReference"] == first
    assert history[0]["status"] == "PARTIALLY_PAID"
    assert history[0]["amountPaid"] == 1500


def test_unpaid_replaced_attempt_stays_failed(monnify_client):
    c = monnify_client
    order = place(c).json()["order"]
    _expire(c, order)
    c.post(f"/api/payments/{order['id']}/new-account")
    history = order_of(c, order["id"])["paymentDetail"]["monnify"]["history"]
    assert history[0]["status"] == "FAILED"
    assert history[0]["amountPaid"] in (None, 0)


def test_late_payment_is_found_by_the_customer_check_without_a_webhook(monnify_client):
    """N1: no notification arrives, the customer presses Check payment."""
    c = monnify_client
    order = place(c).json()["order"]
    first = _expire(c, order)
    c.post(f"/api/payments/{order['id']}/new-account")
    c.fake.results[first] = _paid_result(first, order["total"])

    r = c.get(f"/api/payments/{order['id']}?check=1")
    assert r.status_code == 200
    assert first in c.fake.queries
    stored = order_of(c, order["id"])
    assert stored["status"] == "Payment confirmed"
    assert stored["paymentDetail"]["paidAmount"] == order["total"]


def test_polling_alone_still_checks_only_on_its_own_cadence(monnify_client):
    """A plain poll must not hammer Monnify with the history reference every time."""
    c = monnify_client
    order = place(c).json()["order"]
    first = _expire(c, order)
    c.post(f"/api/payments/{order['id']}/new-account")
    c.fake.results[first] = _paid_result(first, order["total"])

    c.get(f"/api/payments/{order['id']}")  # first poll: current attempt only
    before = c.fake.queries.count(first)
    c.get(f"/api/payments/{order['id']}")  # second poll within the 60s history window
    assert c.fake.queries.count(first) == before


def test_order_history_offers_a_new_account_only_when_it_can_help(monnify_client):
    """N4: the action exists where the customer reads the instructions."""
    c = monnify_client
    order = place(c).json()["order"]
    html = c.get("/ui/orders").text
    assert order["paymentDetail"]["monnify"]["accountNumber"] in html
    assert "data-reissue-account" not in html  # a live account needs no replacement

    _expire(c, order)
    html = c.get("/ui/orders").text
    assert f'data-reissue-account="{order["id"]}"' in html

    fresh = c.post(f"/api/payments/{order['id']}/new-account")
    assert fresh.status_code == 200
    assert (
        fresh.json()["payment"]["paymentReference"]
        != order["paymentDetail"]["monnify"]["paymentReference"]
    )
    assert "data-reissue-account" not in c.get("/ui/orders").text


def test_paid_orders_never_offer_a_new_account(monnify_client):
    c = monnify_client
    order = place(c).json()["order"]
    reference = order["paymentDetail"]["monnify"]["paymentReference"]
    c.fake.results[reference] = _paid_result(reference, order["total"])
    webhook(c, webhook_payload(reference, amount=order["total"]))
    assert "data-reissue-account" not in c.get("/ui/orders").text


def test_sweeper_expires_an_abandoned_reservation(monnify_client):
    """N5: nobody revisits the order, the stock still comes back."""
    import asyncio

    from app import db, payments

    c = monnify_client
    loop = asyncio.new_event_loop()
    product = loop.run_until_complete(db.get_product("p1"))
    loop.run_until_complete(db.save_product({**product, "stock": 10}))
    c.fake.fail_init_transient = True
    payments.RETRY_DELAY_SECONDS = 0
    assert place(c).status_code == 502
    order = loop.run_until_complete(db.get_all_orders())[0]
    assert loop.run_until_complete(db.get_product("p1"))["stock"] == 8

    loop.run_until_complete(
        db.merge_payment_detail(
            order["id"],
            {
                "reservationExpiresAtEpoch": payments.now_epoch() - 1,
                "reservationExpiresAt": "2026-01-01T00:00:00Z",
            },
        )
    )
    assert loop.run_until_complete(payments.sweep_stale_reservations()) == 1
    stored = loop.run_until_complete(db.get_order(order["id"]))
    assert stored["status"] == "Cancelled"
    assert loop.run_until_complete(db.get_product("p1"))["stock"] == 10
    actions = [a["action"] for a in loop.run_until_complete(db.get_audit(order["id"]))]
    assert "payment_reservation_expired" in actions


def test_sweeper_is_idempotent_and_safe_when_run_twice_at_once(monnify_client):
    import asyncio

    from app import db, payments

    c = monnify_client
    loop = asyncio.new_event_loop()
    product = loop.run_until_complete(db.get_product("p1"))
    loop.run_until_complete(db.save_product({**product, "stock": 10}))
    c.fake.fail_init_transient = True
    payments.RETRY_DELAY_SECONDS = 0
    place(c)
    order = loop.run_until_complete(db.get_all_orders())[0]
    loop.run_until_complete(
        db.merge_payment_detail(
            order["id"], {"reservationExpiresAtEpoch": payments.now_epoch() - 1}
        )
    )

    async def twice():
        return await asyncio.gather(
            payments.sweep_stale_reservations(), payments.sweep_stale_reservations()
        )

    results = loop.run_until_complete(twice())
    assert sum(results) == 1
    assert loop.run_until_complete(db.get_product("p1"))["stock"] == 10
    actions = [
        a["action"]
        for a in loop.run_until_complete(db.get_audit(order["id"]))
        if a["action"] == "payment_reservation_expired"
    ]
    assert len(actions) == 1


def test_sweeper_never_cancels_a_verified_payment(monnify_client):
    import asyncio

    from app import db, payments

    c = monnify_client
    order = place(c).json()["order"]
    reference = order["paymentDetail"]["monnify"]["paymentReference"]
    c.fake.results[reference] = _paid_result(reference, order["total"])
    webhook(c, webhook_payload(reference, amount=order["total"]))

    loop = asyncio.new_event_loop()
    loop.run_until_complete(
        db.merge_payment_detail(
            order["id"], {"reservationExpiresAtEpoch": payments.now_epoch() - 1}
        )
    )
    assert loop.run_until_complete(payments.sweep_stale_reservations()) == 0
    assert loop.run_until_complete(db.get_order(order["id"]))["status"] == "Payment confirmed"


def test_throttle_map_keeps_a_hard_upper_bound():
    """N6: fresh entries must not let the map grow past its limit."""
    import time

    from app import payments

    payments._LAST_SYNC.clear()
    now = time.monotonic()
    for i in range(payments._LAST_SYNC_LIMIT + 120):
        payments._LAST_SYNC[f"fresh-{i}"] = now
    payments._prune_last_sync()
    assert len(payments._LAST_SYNC) == payments._LAST_SYNC_LIMIT


def test_existing_discrepancy_survives_a_later_setup_failure(monnify_client):
    """N7: a flagged discrepancy must not be erased by an unrelated failure."""
    import asyncio

    from app import db

    c = monnify_client
    order = place(c).json()["order"]
    loop = asyncio.new_event_loop()
    loop.run_until_complete(
        db.merge_payment_detail(
            order["id"],
            {"needsReconciliation": {"reason": "payment_overpaid", "overpaidBy": 2300}},
        )
    )
    _expire(c, order)
    c.fake.fail_init = True
    assert c.post(f"/api/payments/{order['id']}/new-account").status_code == 502

    detail = loop.run_until_complete(db.get_order(order["id"]))["paymentDetail"]
    assert detail["needsReconciliation"]["reason"] == "payment_overpaid"


def test_two_contenders_cannot_take_over_the_same_stale_lock(monnify_client):
    """N8: the takeover is a compare-and-set, so exactly one contender wins."""
    import asyncio

    from app import db, payments

    c = monnify_client
    order = place(c).json()["order"]
    loop = asyncio.new_event_loop()
    stale = {"token": "dead-holder", "epoch": payments.now_epoch() - 999}
    loop.run_until_complete(db.merge_payment_detail(order["id"], {"paymentAttemptLock": stale}))

    async def contend():
        fresh = await db.get_order(order["id"])
        return await payments._claim_attempt(fresh)

    async def both():
        return await asyncio.gather(contend(), contend())

    results = loop.run_until_complete(both())
    assert sum(1 for r in results if r) == 1


def test_admin_resolves_the_overpayment_before_fulfilment(monnify_client):
    """N2.6: the excess is recorded, blocks progression, and a human closes it."""
    c = monnify_client
    order = place(c).json()["order"]
    total = order["total"]
    reference = order["paymentDetail"]["monnify"]["paymentReference"]
    c.fake.results[reference] = _paid_result(reference, total + 500)
    webhook(c, webhook_payload(reference, amount=total + 500))
    assert order_of(c, order["id"])["paymentDetail"]["needsReconciliation"]["overpaidBy"] == 500

    staff = {"x-staff-key": "staff-test-key"}
    assert (
        c.post(f"/api/store/admin/orders/{order['id']}/resolve-payment", json={}, headers=staff)
    ).status_code == 400
    r = c.post(
        f"/api/store/admin/orders/{order['id']}/resolve-payment",
        json={"note": "Refunded the extra 500"},
        headers=staff,
    )
    assert r.status_code == 200
    detail = order_of(c, order["id"])["paymentDetail"]
    assert not detail.get("needsReconciliation")
    assert detail["reconciliationResolved"]["note"] == "Refunded the extra 500"
    actions = [a["action"] for a in _audit(order["id"])]
    assert "payment_discrepancy_resolved" in actions


def test_resolve_needs_staff_and_an_actual_discrepancy(monnify_client):
    c = monnify_client
    order = place(c).json()["order"]
    r = c.post(
        f"/api/store/admin/orders/{order['id']}/resolve-payment",
        json={"note": "nothing to do"},
        headers={"x-staff-key": "staff-test-key"},
    )
    assert r.status_code == 409
    assert c.post(
        f"/api/store/admin/orders/{order['id']}/resolve-payment", json={}
    ).status_code in (
        401,
        403,
    )
