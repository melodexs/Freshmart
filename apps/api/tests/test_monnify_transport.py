"""The Monnify HTTP transport: our own client identity, and honest failure diagnostics.

Monnify's sandbox sits behind Cloudflare, which answers Python's default client with HTTP 403
``error code: 1010`` before the request ever reaches the API. These tests pin the fix (an explicit
application User-Agent on every call) and the diagnostics that make the next failure readable
without leaking a key, a secret or a header.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import urllib.error

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
API_KEY = "MK_TEST_key"
CLOUDFLARE_BODY = "error code: 1010\n"


class FakeResponse:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body.encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc) -> bool:
        return False


class FakeNetwork:
    """Stands in for urllib. Records each request and replays queued replies."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.queue: list[tuple[int, object]] = []
        # A sticky reply repeats for every call, which is how a persistent block behaves.
        self.sticky: tuple[int, object] | None = None

    def reply(self, status: int, body: object) -> None:
        self.queue.append((status, body))

    def __call__(self, req, timeout=None):
        self.requests.append(
            {
                "url": req.full_url,
                "method": req.get_method(),
                "headers": {k.lower(): v for k, v in req.header_items()},
                "body": req.data,
            }
        )
        if self.queue:
            status, body = self.queue.pop(0)
        elif self.sticky is not None:
            status, body = self.sticky
        else:
            status, body = (200, {"requestSuccessful": True})
        raw = body if isinstance(body, str) else json.dumps(body)
        if status >= 400:
            raise urllib.error.HTTPError(
                req.full_url, status, "error", {}, io.BytesIO(raw.encode())
            )
        return FakeResponse(status, raw)


def _load(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_FILE", str(tmp_path / "db.json"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("STORE_STAFF_KEY", "staff-test-key")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("MONNIFY_API_KEY", API_KEY)
    monkeypatch.setenv("MONNIFY_SECRET_KEY", SECRET)
    monkeypatch.setenv("MONNIFY_CONTRACT_CODE", "9115568354")
    monkeypatch.setenv("MONNIFY_BASE_URL", "https://sandbox.monnify.com")
    for m in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[m]
    from app import monnify

    monnify.reset_token_cache()
    return monnify


@pytest.fixture()
def transport(tmp_path, monkeypatch):
    monnify = _load(monkeypatch, tmp_path)
    net = FakeNetwork()
    monkeypatch.setattr("urllib.request.urlopen", net)
    return monnify, net


@pytest.fixture()
def blocked_client(tmp_path, monkeypatch):
    """A full app whose Monnify calls are answered by Cloudflare instead of Monnify."""
    _load(monkeypatch, tmp_path)
    net = FakeNetwork()
    net.sticky = (403, CLOUDFLARE_BODY)
    monkeypatch.setattr("urllib.request.urlopen", net)

    from fastapi.testclient import TestClient

    from app import db, ratelimit
    from app.main import app

    ratelimit.reset()
    with TestClient(app) as c:
        asyncio.new_event_loop().run_until_complete(
            db.set_setting(
                "bank_details",
                {"bank": "Test Bank", "accountName": "OGS Test", "accountNumber": "0123456789"},
            )
        )
        c.post("/api/auth/signup", json=SIGNUP)
        c.post("/api/auth/login", json={"email": SIGNUP["email"], "password": SIGNUP["password"]})
        c.net = net
        yield c


def login_ok(token: str = "TOKEN1") -> dict:
    return {
        "requestSuccessful": True,
        "responseBody": {"accessToken": token, "expiresIn": 3599},
    }


# ---------- 1, 2 and 3: identity and headers ----------


def test_requests_carry_our_own_application_identity(transport):
    monnify, net = transport
    net.reply(200, {"requestSuccessful": True, "responseBody": {}})

    monnify._request_sync("GET", "https://sandbox.monnify.com/api/v1/x", None, {})

    sent = net.requests[-1]["headers"]
    assert sent["user-agent"] == monnify.USER_AGENT
    assert "Freshmart" in monnify.USER_AGENT
    assert "Mozilla" not in monnify.USER_AGENT
    assert "Python-urllib" not in monnify.USER_AGENT


def test_all_four_calls_use_the_same_identity_and_json_headers(transport):
    monnify, net = transport
    net.reply(200, login_ok())
    net.reply(
        200,
        {
            "requestSuccessful": True,
            "responseBody": {"transactionReference": "MNFY|TEST|1"},
        },
    )
    net.reply(
        200,
        {
            "requestSuccessful": True,
            "responseBody": {"accountNumber": "9000000001", "bankName": "Sterling bank"},
        },
    )
    net.reply(200, {"requestSuccessful": True, "responseBody": {"paymentStatus": "PENDING"}})

    async def drive():
        await monnify.init_transaction(
            order_id="FM1",
            payment_reference="OGS-FM1-abc",
            amount=1200,
            customer_name="Ada",
            customer_email="ada@example.com",
        )
        await monnify.init_payment("MNFY|TEST|1")
        await monnify.query_transaction("OGS-FM1-abc")

    asyncio.new_event_loop().run_until_complete(drive())

    assert len(net.requests) == 4
    urls = [r["url"] for r in net.requests]
    assert urls[0].endswith("/api/v1/auth/login")
    assert urls[1].endswith("/api/v1/merchant/transactions/init-transaction")
    assert urls[2].endswith("/api/v1/merchant/bank-transfer/init-payment")
    assert urls[3].startswith("https://sandbox.monnify.com/api/v2/merchant/transactions/query")

    for request in net.requests:
        assert request["headers"]["user-agent"] == monnify.USER_AGENT
        assert request["headers"]["content-type"] == "application/json"
        assert request["headers"]["accept"] == "application/json"


def test_post_bodies_stay_json(transport):
    monnify, net = transport
    net.reply(200, login_ok())
    net.reply(200, {"requestSuccessful": True, "responseBody": {"transactionReference": "T"}})

    asyncio.new_event_loop().run_until_complete(
        monnify.init_transaction(
            order_id="FM1",
            payment_reference="REF",
            amount=1200,
            customer_name="Ada",
            customer_email="ada@example.com",
        )
    )

    payload = json.loads(net.requests[-1]["body"].decode())
    assert payload["currencyCode"] == "NGN"
    assert payload["paymentReference"] == "REF"


# ---------- 4: an edge block ----------


def test_cloudflare_403_is_a_transient_edge_block(transport):
    monnify, net = transport
    net.reply(200, login_ok())
    net.reply(403, CLOUDFLARE_BODY)

    with pytest.raises(monnify.MonnifyError) as caught:
        asyncio.new_event_loop().run_until_complete(
            monnify.init_transaction(
                order_id="FM1",
                payment_reference="REF",
                amount=1200,
                customer_name="Ada",
                customer_email="ada@example.com",
            )
        )

    error = caught.value
    assert error.transient is True, "an edge block must not cancel a customer's order"
    assert error.status == 403
    assert "1010" in error.upstream_message
    assert error.stage == "start the payment"
    assert "gateway" in str(error)


# ---------- 5: Monnify's own rejection ----------


def test_monnify_401_keeps_its_own_message_and_code(transport):
    monnify, net = transport
    net.reply(
        401,
        {
            "requestSuccessful": False,
            "responseCode": "99",
            "responseMessage": "Invalid authentication credentials. Please check the environment.",
        },
    )

    with pytest.raises(monnify.MonnifyError) as caught:
        asyncio.new_event_loop().run_until_complete(monnify.access_token())

    error = caught.value
    assert error.transient is False
    assert error.status == 401
    assert error.response_code == "99"
    assert error.stage == "authenticate"
    assert str(error).startswith("Invalid authentication credentials")


# ---------- 6: the happy path ----------


def test_successful_sign_in_continues_and_is_cached(transport):
    monnify, net = transport
    net.reply(200, login_ok("TOKEN1"))
    net.reply(200, {"requestSuccessful": True, "responseBody": {"paymentStatus": "PENDING"}})
    net.reply(200, {"requestSuccessful": True, "responseBody": {"paymentStatus": "PENDING"}})

    async def drive():
        await monnify.query_transaction("REF-1")
        await monnify.query_transaction("REF-2")

    asyncio.new_event_loop().run_until_complete(drive())

    logins = [r for r in net.requests if r["url"].endswith("/api/v1/auth/login")]
    assert len(logins) == 1, "the token must be reused, not re-fetched"
    assert net.requests[-1]["headers"]["authorization"] == "Bearer TOKEN1"


# ---------- 7: what the shop records, and what it must never record ----------


def test_edge_block_keeps_the_order_alive_and_records_safe_diagnostics(blocked_client):
    c = blocked_client
    response = c.post("/api/orders", json={**ORDER, "payMethod": "before"})
    assert response.status_code == 502

    from app import db

    orders = asyncio.new_event_loop().run_until_complete(db.get_all_orders())
    order = orders[-1]
    detail = order["paymentDetail"]
    attempt = detail["monnify"]

    assert order["status"] == "Awaiting payment", "an edge block must not cancel the order"
    assert attempt["status"] == "FAILED"
    assert attempt["transient"] is True
    assert attempt["lastErrorStatus"] == 403
    assert "1010" in attempt["lastErrorUpstream"]
    assert attempt["lastErrorStage"] == "authenticate"
    assert detail.get("reservationExpiresAtEpoch"), "stock must be held, not released"
    assert not detail.get("stockReleased")

    blob = json.dumps(detail)
    assert SECRET not in blob
    assert API_KEY not in blob
    assert "Bearer" not in blob
    assert "Authorization" not in blob

    audit = asyncio.new_event_loop().run_until_complete(db.get_audit(order["id"]))
    audit_blob = json.dumps(audit)
    assert SECRET not in audit_blob
    assert API_KEY not in audit_blob
    assert "Bearer" not in audit_blob


def test_monnify_json_rejection_is_permanent_and_still_cancels(tmp_path, monkeypatch):
    _load(monkeypatch, tmp_path)
    net = FakeNetwork()
    net.reply(200, login_ok())
    net.reply(
        400,
        {
            "requestSuccessful": False,
            "responseCode": "99",
            "responseMessage": "Invalid contract code",
        },
    )
    monkeypatch.setattr("urllib.request.urlopen", net)

    from fastapi.testclient import TestClient

    from app import db, ratelimit
    from app.main import app

    ratelimit.reset()
    with TestClient(app) as c:
        asyncio.new_event_loop().run_until_complete(
            db.set_setting(
                "bank_details",
                {"bank": "Test Bank", "accountName": "OGS Test", "accountNumber": "0123456789"},
            )
        )
        c.post("/api/auth/signup", json=SIGNUP)
        c.post("/api/auth/login", json={"email": SIGNUP["email"], "password": SIGNUP["password"]})
        response = c.post("/api/orders", json={**ORDER, "payMethod": "before"})
        assert response.status_code == 502

        orders = asyncio.new_event_loop().run_until_complete(db.get_all_orders())
        order = orders[-1]
        attempt = order["paymentDetail"]["monnify"]

        assert order["status"] == "Cancelled"
        assert attempt["transient"] is False
        assert attempt["lastErrorStatus"] == 400
        assert attempt["lastErrorUpstream"] == "Invalid contract code"
        assert order["paymentDetail"].get("stockReleased") is True
