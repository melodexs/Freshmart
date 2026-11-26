"""Monnify client for the pay-before-delivery bank transfer flow.

Only this module talks to Monnify. Routes and the payments service call in here, so:

* credentials stay in backend environment variables and never reach a browser, a response
  body, a log line or a commit;
* the access token is cached in memory and refreshed shortly before it expires;
* every failure is turned into a ``MonnifyError`` whose message is safe to show a human.

The flow (verified against the sandbox before writing this):

1. ``POST /api/v1/auth/login`` with HTTP Basic ``apiKey:secretKey`` -> ``accessToken``.
2. ``POST /api/v1/merchant/transactions/init-transaction`` -> ``transactionReference``.
3. ``POST /api/v1/merchant/bank-transfer/init-payment`` -> a one-time account number.
4. ``GET  /api/v2/merchant/transactions/query`` -> the authoritative payment status.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi.concurrency import run_in_threadpool

from . import config

TIMEOUT_SECONDS = 30
# Refresh this many seconds before the token Monnify gave us actually expires.
TOKEN_REFRESH_MARGIN = 60

_TOKEN: dict[str, object] = {"value": "", "expires_at": 0.0}
_TOKEN_LOCK = asyncio.Lock()


class MonnifyError(Exception):
    """A Monnify call failed. The message is safe to show to a human, and holds no secrets."""


def is_ready() -> bool:
    """True when payments can be taken. False when Monnify is off, with the reason in config."""
    return bool(config.MONNIFY_READY)


def disabled_reason() -> str:
    return config.MONNIFY_DISABLED_REASON


# ---------- transport ----------


def _request_sync(method: str, url: str, payload: dict | None, headers: dict) -> tuple[int, dict]:
    """One HTTP call, done in a worker thread so the event loop stays free.

    Returns (status, parsed body). HTTP errors are returned, not raised, because Monnify puts a
    useful message in the body of a 4xx.
    """
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    for key, value in headers.items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:  # noqa: S310
            body = resp.read().decode(errors="replace")
            return resp.status, _parse(body)
    except urllib.error.HTTPError as exc:
        return exc.code, _parse(exc.read().decode(errors="replace"))
    except urllib.error.URLError as exc:
        raise MonnifyError("Could not reach Monnify. Please try again.") from exc
    except TimeoutError as exc:
        raise MonnifyError("Monnify did not answer in time. Please try again.") from exc


def _parse(body: str) -> dict:
    try:
        parsed = json.loads(body or "{}")
    except ValueError:
        return {"responseMessage": (body or "")[:200]}
    return parsed if isinstance(parsed, dict) else {"responseBody": parsed}


def _basic_auth_header() -> dict:
    raw = f"{config.MONNIFY_API_KEY}:{config.MONNIFY_SECRET_KEY}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def _url(path: str, params: dict | None = None) -> str:
    url = f"{config.MONNIFY_BASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return url


async def _send(method: str, path: str, payload: dict | None = None, params: dict | None = None):
    return await run_in_threadpool(
        _request_sync, method, _url(path, params), payload, await _auth_header()
    )


# ---------- authentication ----------


async def _auth_header(force: bool = False) -> dict:
    return {"Authorization": f"Bearer {await access_token(force)}"}


async def access_token(force: bool = False) -> str:
    """A cached access token, refreshed before it expires (Monnify gives 3599 seconds)."""
    now = time.monotonic()
    if not force and _TOKEN["value"] and float(_TOKEN["expires_at"]) - TOKEN_REFRESH_MARGIN > now:
        return str(_TOKEN["value"])
    async with _TOKEN_LOCK:
        now = time.monotonic()
        if (
            not force
            and _TOKEN["value"]
            and float(_TOKEN["expires_at"]) - TOKEN_REFRESH_MARGIN > now
        ):
            return str(_TOKEN["value"])
        status, body = await run_in_threadpool(
            _request_sync,
            "POST",
            _url("/api/v1/auth/login"),
            {},
            _basic_auth_header(),
        )
        if status != 200 or not body.get("requestSuccessful"):
            raise MonnifyError(_message(body, "Monnify sign-in failed."))
        data = body.get("responseBody") or {}
        token = str(data.get("accessToken") or "")
        if not token:
            raise MonnifyError("Monnify sign-in returned no access token.")
        try:
            ttl = int(data.get("expiresIn") or 3599)
        except (TypeError, ValueError):
            ttl = 3599
        _TOKEN["value"] = token
        _TOKEN["expires_at"] = now + max(ttl - TOKEN_REFRESH_MARGIN, 30)
        return token


def reset_token_cache() -> None:
    """Forget the cached token (tests and staff-triggered retries)."""
    _TOKEN["value"] = ""
    _TOKEN["expires_at"] = 0.0


# ---------- the four calls we actually use ----------


async def init_transaction(
    *, order_id: str, payment_reference: str, amount: int, customer_name: str, customer_email: str
) -> dict:
    """Create the Monnify side of a payment. Returns its ``responseBody``."""
    payload = {
        "amount": float(amount),
        "customerName": customer_name or "OGS customer",
        "customerEmail": customer_email,
        "paymentReference": payment_reference,
        "paymentDescription": f"OGS order {order_id}",
        "contractCode": config.MONNIFY_CONTRACT_CODE,
        "currencyCode": "NGN",
        "paymentMethods": ["ACCOUNT_TRANSFER"],
        "metaData": {"orderId": order_id},
    }
    body = await _checked(
        "POST", "/api/v1/merchant/transactions/init-transaction", payload, "start the payment"
    )
    data = body.get("responseBody") or {}
    if not data.get("transactionReference"):
        raise MonnifyError("Monnify did not return a transaction reference.")
    return data


async def init_payment(transaction_reference: str) -> dict:
    """Ask for the one-time account number that belongs to this transaction."""
    body = await _checked(
        "POST",
        "/api/v1/merchant/bank-transfer/init-payment",
        {"transactionReference": transaction_reference},
        "create the transfer account",
    )
    data = body.get("responseBody") or {}
    if not data.get("accountNumber"):
        raise MonnifyError("Monnify did not return an account number for this payment.")
    return data


async def query_transaction(payment_reference: str) -> dict:
    """The authoritative record of a payment. Used for polling and before trusting a webhook."""
    body = await _checked(
        "GET",
        "/api/v2/merchant/transactions/query",
        None,
        "check the payment",
        params={"paymentReference": payment_reference},
    )
    return body.get("responseBody") or {}


async def _checked(
    method: str, path: str, payload: dict | None, what: str, params: dict | None = None
) -> dict:
    status, body = await _send(method, path, payload, params)
    if status == 401:
        # A stale or revoked token: refresh once, then try again.
        status, body = await _send(method, path, payload, params)
    if status != 200 or not body.get("requestSuccessful"):
        raise MonnifyError(_message(body, f"Monnify could not {what}."))
    return body


def _message(body: dict, fallback: str) -> str:
    text = str(body.get("responseMessage") or "").strip()
    if not text:
        return fallback
    return text[:200]


# ---------- webhook signature ----------


def verify_signature(raw_body: bytes, signature: str | None) -> bool:
    """Monnify signs the raw request body with HMAC-SHA512, keyed by the secret key.

    Compared in constant time. An unsigned request is never valid here: the caller decides what
    to do about sandbox deliveries that arrive without the header.
    """
    if not signature:
        return False
    expected = hmac.new(
        config.MONNIFY_SECRET_KEY.encode(), raw_body or b"", hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(expected, signature.strip())
