"""Monnify behaviour against real PostgreSQL.

The rest of the suite runs on the JSON store, which is why the Postgres SQL (the jsonb merge, the
`?` operator with a bound parameter, the history lookup and the atomic settlement) needs its own
coverage. These tests are skipped when DATABASE_URL is not set, so a normal run stays fast; CI runs
them against a throwaway Postgres service.

Run locally with, for example:
    DATABASE_URL=postgresql://postgres@127.0.0.1:5432/ogs_test pytest tests/test_monnify_postgres.py
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sys
from functools import partial

import pytest

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if not DATABASE_URL:
    pytest.skip(
        "DATABASE_URL is not set: Postgres integration tests skipped.", allow_module_level=True
    )

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
    "payMethod": "before",
    "name": "Ada Okwudiri",
}
SECRET = "monnify-test-secret"


class FakeMonnify:
    def __init__(self) -> None:
        self.init_calls: list[dict] = []
        self.query_result: dict | None = None
        self.counter = 0

    async def init_transaction(
        self, *, order_id, payment_reference, amount, customer_name, customer_email
    ):
        self.counter += 1
        self.init_calls.append(
            {"paymentReference": payment_reference, "customerName": customer_name}
        )
        return {
            "transactionReference": f"MNFY|PG|{self.counter}",
            "paymentReference": payment_reference,
        }

    async def init_payment(self, transaction_reference):
        return {
            "accountNumber": f"9000000{len(self.init_calls):03d}",
            "accountName": "OGS Test-OGS",
            "bankName": "Sterling bank",
            "bankCode": "232",
            "accountDurationSeconds": 2400,
            "expiresOn": "2026-11-26T17:03:06",
        }

    async def query_transaction(self, payment_reference):
        return self.query_result or {
            "paymentReference": payment_reference,
            "paymentStatus": "PENDING",
        }


def _reset_schema() -> None:
    import asyncpg

    async def run() -> None:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        finally:
            await conn.close()

    asyncio.new_event_loop().run_until_complete(run())


@pytest.fixture()
def pg_client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    # A throwaway local/service Postgres has no certificate; production keeps PGSSLMODE=require.
    monkeypatch.setenv("PGSSLMODE", "disable")
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("STORE_STAFF_KEY", "staff-test-key")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("MONNIFY_API_KEY", "MK_TEST_key")
    monkeypatch.setenv("MONNIFY_SECRET_KEY", SECRET)
    monkeypatch.setenv("MONNIFY_CONTRACT_CODE", "9115568354")
    monkeypatch.setenv("MONNIFY_BASE_URL", "https://sandbox.monnify.com")
    for m in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[m]

    _reset_schema()

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


def run(client, fn, *args):
    """Run a database helper in the app's own event loop.

    The pool belongs to the loop the TestClient started, so a private loop would hand us
    connections bound to a different one. portal.call keeps every call on that loop.
    """
    return client.portal.call(fn, *args)


def webhook(client, reference: str, amount: int, status: str = "PAID"):
    payload = {
        "eventType": "SUCCESSFUL_TRANSACTION",
        "eventData": {
            "paymentReference": reference,
            "transactionReference": "MNFY|PG|1",
            "paymentStatus": status,
            "amountPaid": amount,
            "currency": "NGN",
            "paymentMethod": "ACCOUNT_TRANSFER",
        },
    }
    raw = json.dumps(payload).encode()
    signature = hmac.new(SECRET.encode(), raw, hashlib.sha512).hexdigest()
    return client.post(
        "/api/webhooks/monnify",
        content=raw,
        headers={"Content-Type": "application/json", "monnify-signature": signature},
    )


def test_postgres_stores_the_account_and_serves_it_back(pg_client):
    c = pg_client
    r = c.post("/api/orders", json=ORDER)
    assert r.status_code == 200, r.text
    payment = r.json()["payment"]
    assert payment["accountNumber"]
    assert c.fake.init_calls[-1]["customerName"] == "Ada Okwudiri"

    from app import db

    stored = run(c, db.get_order, r.json()["order"]["id"])
    assert stored["paymentDetail"]["monnify"]["paymentReference"] == payment["paymentReference"]


def test_postgres_only_if_absent_claim_is_atomic(pg_client):
    """Proves the jsonb `?` operator works with a bound parameter, which the lock depends on."""
    c = pg_client
    order = c.post("/api/orders", json=ORDER).json()["order"]

    from app import db

    claim = partial(
        db.merge_payment_detail, order["id"], {"probeLock": {"at": 1}}, only_if_absent="probeLock"
    )
    assert run(c, claim) is True
    again = partial(
        db.merge_payment_detail, order["id"], {"probeLock": {"at": 2}}, only_if_absent="probeLock"
    )
    assert run(c, again) is False
    assert run(c, db.drop_payment_detail_keys, order["id"], ["probeLock"]) is True
    after_drop = partial(
        db.merge_payment_detail, order["id"], {"probeLock": {"at": 3}}, only_if_absent="probeLock"
    )
    assert run(c, after_drop) is True


def test_postgres_finds_a_historical_payment_reference(pg_client):
    c = pg_client
    order = c.post("/api/orders", json=ORDER).json()["order"]
    old_reference = order["paymentDetail"]["monnify"]["paymentReference"]

    from app import db

    attempt = order["paymentDetail"]["monnify"]
    run(c, db.merge_payment_detail, order["id"], {"monnify": {**attempt, "expiresAtEpoch": 1}})
    fresh = c.post(f"/api/payments/{order['id']}/new-account")
    assert fresh.status_code == 200
    assert fresh.json()["payment"]["paymentReference"] != old_reference

    assert run(c, db.get_order_by_payment_reference, old_reference)["id"] == order["id"]
    current = fresh.json()["payment"]["paymentReference"]
    assert run(c, db.get_order_by_payment_reference, current)["id"] == order["id"]


def test_postgres_settles_a_late_payment_to_a_replaced_account(pg_client):
    c = pg_client
    order = c.post("/api/orders", json=ORDER).json()["order"]
    old_reference = order["paymentDetail"]["monnify"]["paymentReference"]

    from app import db

    attempt = order["paymentDetail"]["monnify"]
    run(c, db.merge_payment_detail, order["id"], {"monnify": {**attempt, "expiresAtEpoch": 1}})
    c.post(f"/api/payments/{order['id']}/new-account")

    c.fake.query_result = {
        "paymentReference": old_reference,
        "transactionReference": "MNFY|PG|1",
        "paymentStatus": "PAID",
        "amountPaid": order["total"],
        "currency": "NGN",
        "paymentMethod": "ACCOUNT_TRANSFER",
    }
    assert webhook(c, old_reference, order["total"]).status_code == 200

    stored = run(c, db.get_order, order["id"])
    assert stored["status"] == "Payment confirmed"
    assert stored["paymentDetail"]["paidAmount"] == order["total"]
    audit = run(c, db.get_audit, order["id"])
    assert any(a["action"] == "payment_matched_historical_attempt" for a in audit)


def test_postgres_settlement_is_atomic(pg_client):
    """Two settlements cannot both win, which is what makes a duplicate webhook harmless."""
    c = pg_client
    order = c.post("/api/orders", json=ORDER).json()["order"]

    from app import db

    record = {"paid": True, "paidAmount": order["total"], "paidMethod": "monnify"}
    assert (
        run(c, db.mark_paid_verified, order["id"], "Awaiting payment", "Payment confirmed", record)
        is True
    )
    assert (
        run(c, db.mark_paid_verified, order["id"], "Awaiting payment", "Payment confirmed", record)
        is False
    )
    assert run(c, db.get_order, order["id"])["status"] == "Payment confirmed"
