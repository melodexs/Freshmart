"""Password reset: honest when email is off, no enumeration, single-use hashed expiring tokens, old sessions die."""

from __future__ import annotations

import hashlib
import time

import pytest

ADA = {
    "name": "Ada Obi",
    "phone": "08011111111",
    "email": "ada@example.com",
    "password": "oldsecret1",
    "passwordConfirm": "oldsecret1",
}


@pytest.fixture
def shop(client):
    client.post("/api/auth/signup", json=ADA)
    client.cookies.clear()
    return client


@pytest.fixture
def email_on(monkeypatch):
    """Pretend an email provider is connected, and capture what would have been sent.

    Only the final network call is replaced (a test double). The token logic runs for real.
    """
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("EMAIL_FROM", "OGS <shop@example.com>")
    monkeypatch.setenv("PUBLIC_URL", "https://shop.example.com")
    sent = []

    from app import mailer

    def fake_post(payload):
        sent.append(payload)
        return True

    monkeypatch.setattr(mailer, "_post", fake_post)
    return sent


def token_from(sent):
    text = sent[-1]["text"]
    return text.split("token=")[1].split()[0]


def login(c, password):
    return c.post("/api/auth/login", json={"email": "ada@example.com", "password": password})


# ---- honesty while no email service is connected ----
def test_without_email_the_page_says_so_and_never_claims_a_send(shop):
    assert shop.get("/api/auth/reset/status").json() == {"emailAvailable": False}
    r = shop.post("/api/auth/forgot", json={"email": "ada@example.com"})
    assert r.status_code == 503
    assert "not switched on" in r.json()["error"] and "sent" not in r.json()[
        "error"
    ].lower().replace("not sent", "")


def test_a_half_configured_service_still_counts_as_off(shop, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "k")  # no sender, no public address
    assert shop.get("/api/auth/reset/status").json()["emailAvailable"] is False
    monkeypatch.setenv("EMAIL_FROM", "a@b.com")
    monkeypatch.setenv("PUBLIC_URL", "http://insecure.example.com")  # must be https
    assert shop.get("/api/auth/reset/status").json()["emailAvailable"] is False


# ---- asking for a link ----
def test_the_reply_is_identical_for_known_and_unknown_emails(shop, email_on):
    known = shop.post("/api/auth/forgot", json={"email": "ada@example.com"})
    unknown = shop.post("/api/auth/forgot", json={"email": "nobody@example.com"})
    junk = shop.post("/api/auth/forgot", json={"email": "not an email"})
    assert known.status_code == unknown.status_code == junk.status_code == 200
    assert known.json() == unknown.json() == junk.json()
    assert len(email_on) == 1  # only the real account got a message


def test_the_emailed_link_uses_the_configured_address_not_the_request_host(shop, email_on):
    shop.post(
        "/api/auth/forgot", json={"email": "ada@example.com"}, headers={"Host": "evil.example.net"}
    )
    text = email_on[0]["text"]
    assert "https://shop.example.com/reset-password?token=" in text and "evil" not in text
    assert email_on[0]["to"] == ["ada@example.com"]


def test_only_the_hash_of_the_token_is_stored(shop, email_on):
    import asyncio

    from app import db

    shop.post("/api/auth/forgot", json={"email": "ada@example.com"})
    tok = token_from(email_on)
    loop = asyncio.new_event_loop()
    rows = (
        loop.run_until_complete(db._impl._read_tokens())
        if hasattr(db._impl, "_read_tokens")
        else None
    )
    if rows is None:
        import json

        from app import db_file

        rows = json.loads(db_file._path().read_text("utf8"))["reset_tokens"]
    assert len(rows) == 1 and rows[0]["hash"] == hashlib.sha256(tok.encode()).hexdigest()
    assert tok not in str(rows)


# ---- using a link ----
def test_the_link_resets_the_password_once(shop, email_on):
    shop.post("/api/auth/forgot", json={"email": "ada@example.com"})
    tok = token_from(email_on)
    assert shop.get(f"/api/auth/reset/check?token={tok}").json() == {"valid": True}
    assert (
        shop.post("/api/auth/reset", json={"token": tok, "password": "newsecret9"}).status_code
        == 200
    )
    assert login(shop, "newsecret9").status_code == 200
    shop.cookies.clear()
    assert login(shop, "oldsecret1").status_code != 200
    again = shop.post("/api/auth/reset", json={"token": tok, "password": "another99"})
    assert again.status_code == 400 and shop.get(f"/api/auth/reset/check?token={tok}").json() == {
        "valid": False
    }


def test_a_newer_request_replaces_the_older_link(shop, email_on):
    shop.post("/api/auth/forgot", json={"email": "ada@example.com"})
    first = token_from(email_on)
    shop.post("/api/auth/forgot", json={"email": "ada@example.com"})
    second = token_from(email_on)
    assert first != second
    assert (
        shop.post("/api/auth/reset", json={"token": first, "password": "newsecret9"}).status_code
        == 400
    )
    assert (
        shop.post("/api/auth/reset", json={"token": second, "password": "newsecret9"}).status_code
        == 200
    )


def test_an_expired_link_is_refused(shop, email_on, monkeypatch):
    shop.post("/api/auth/forgot", json={"email": "ada@example.com"})
    tok = token_from(email_on)
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 31 * 60)
    assert shop.get(f"/api/auth/reset/check?token={tok}").json() == {"valid": False}
    assert (
        shop.post("/api/auth/reset", json={"token": tok, "password": "newsecret9"}).status_code
        == 400
    )
    monkeypatch.setattr(time, "time", real)
    assert login(shop, "oldsecret1").status_code == 200  # the old password still works


@pytest.mark.parametrize("bad", ["", "nope", "a" * 500, None, 123])
def test_guessed_or_malformed_tokens_are_refused(shop, email_on, bad):
    assert (
        shop.post("/api/auth/reset", json={"token": bad, "password": "newsecret9"}).status_code
        == 400
    )


def test_a_weak_or_oversized_password_does_not_use_up_the_link(shop, email_on):
    shop.post("/api/auth/forgot", json={"email": "ada@example.com"})
    tok = token_from(email_on)
    assert shop.post("/api/auth/reset", json={"token": tok, "password": "abc"}).status_code == 400
    assert (
        shop.post("/api/auth/reset", json={"token": tok, "password": "x" * 500}).status_code == 400
    )
    assert (
        shop.post("/api/auth/reset", json={"token": tok, "password": "goodenough1"}).status_code
        == 200
    )


# ---- aftermath ----
def test_a_reset_signs_out_older_sessions(shop, email_on):
    login(shop, "oldsecret1")
    assert shop.get("/api/auth/me").status_code == 200
    stolen = dict(shop.cookies)
    shop.post("/api/auth/forgot", json={"email": "ada@example.com"})
    time.sleep(1.1)  # sessions are timestamped to the second
    shop.post("/api/auth/reset", json={"token": token_from(email_on), "password": "newsecret9"})
    shop.cookies.clear()
    for k, v in stolen.items():
        shop.cookies.set(k, v)
    assert shop.get("/api/auth/me").status_code == 401  # the old session is dead
    assert login(shop, "newsecret9").status_code == 200
    assert shop.get("/api/auth/me").status_code == 200  # a fresh sign-in works


def test_a_reset_is_recorded_in_the_audit_log(shop, email_on, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "STORE_STAFF_KEY", "staff-secret-key")
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    shop.post("/api/auth/forgot", json={"email": "ada@example.com"})
    shop.post("/api/auth/reset", json={"token": token_from(email_on), "password": "newsecret9"})
    log = shop.get("/api/store/admin/audit", headers={"X-Staff-Key": "staff-secret-key"}).json()[
        "entries"
    ]
    hit = [e for e in log if e["action"] == "password_reset"]
    assert hit and "newsecret9" not in str(hit)


def test_asking_for_links_is_rate_limited(shop, email_on):
    codes = [
        shop.post("/api/auth/forgot", json={"email": "ada@example.com"}).status_code
        for _ in range(8)
    ]
    assert 429 in codes
