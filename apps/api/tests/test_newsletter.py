"""Newsletter: valid emails only, no duplicates, no enumeration, signed unsubscribe, staff-only list."""

from __future__ import annotations

import csv
import io

import pytest

STAFF = {"X-Staff-Key": "staff-secret-key"}


@pytest.fixture
def shop(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "STORE_STAFF_KEY", "staff-secret-key")
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    return client


def helpers():
    """Import after the client fixture ran: it reloads every app module, so a top-level import
    would hold a stale copy with a different signing secret."""
    from app.emails import clean_email
    from app.routes.newsletter import token_for, unsubscribe_path

    return clean_email, token_for, unsubscribe_path


def sub(c, email):
    return c.post("/api/newsletter", json={"email": email})


@pytest.mark.parametrize(
    "good",
    [
        "ada@example.com",
        "  Ada.Obi+shop@Example.COM ",
        "a_b-c@mail.co.ng",
        "x@sub.domain.example.org",
    ],
)
def test_valid_addresses_are_accepted_and_normalised(good):
    clean_email, _, _ = helpers()
    assert clean_email(good) == good.strip().lower()


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "ada",
        "ada@",
        "@example.com",
        "ada@example",
        "ada@@example.com",
        "a da@example.com",
        "ada@exa mple.com",
        "ada@example..com",
        ".ada@example.com",
        "ada.@example.com",
        "<script>@x.com",
        'ada"@example.com',
        "ada@example.com\nBcc: x@y.com",
        "a" * 300 + "@example.com",
        None,
        123,
        ["a@b.co"],
        {"e": 1},
    ],
)
def test_invalid_addresses_are_refused(bad):
    clean_email, _, _ = helpers()
    assert clean_email(bad) is None


def test_subscribe_stores_once_and_replies_the_same_for_duplicates(shop):
    first, second = sub(shop, "Ada@Example.com"), sub(shop, "ada@example.com")
    assert first.status_code == second.status_code == 200 and first.json() == second.json()
    rows = shop.get("/api/store/admin/subscribers", headers=STAFF).json()
    assert rows["count"] == 1 and rows["subscribers"][0]["email"] == "ada@example.com"


def test_bad_email_is_a_clear_400_and_nothing_is_stored(shop):
    for bad in ("nope", "", None):
        r = shop.post("/api/newsletter", json={"email": bad})
        assert r.status_code == 400 and "valid email" in r.json()["error"]
    assert shop.post("/api/newsletter", data="not json").status_code == 400
    assert shop.get("/api/store/admin/subscribers", headers=STAFF).json()["count"] == 0


def test_signup_is_rate_limited(shop):
    codes = [sub(shop, f"user{i}@example.com").status_code for i in range(9)]
    assert 429 in codes and codes[0] == 200


def test_unsubscribe_needs_the_signed_link_and_is_one_click(shop):
    sub(shop, "ada@example.com")
    assert shop.get("/newsletter/unsubscribe?email=ada@example.com&t=wrong").status_code == 400
    assert shop.get("/newsletter/unsubscribe?email=ada@example.com").status_code == 400
    assert (
        shop.get("/api/store/admin/subscribers", headers=STAFF).json()["count"] == 1
    )  # a guess did nothing
    _, _, unsubscribe_path = helpers()
    r = shop.get(unsubscribe_path("ada@example.com"))
    assert r.status_code == 200 and "unsubscribed" in r.text
    assert shop.get("/api/store/admin/subscribers", headers=STAFF).json()["count"] == 0


def test_a_token_only_works_for_its_own_address():
    _, token_for, _ = helpers()
    assert token_for("a@example.com") != token_for("b@example.com")


def test_resubscribing_after_leaving_works(shop):
    sub(shop, "ada@example.com")
    _, _, unsubscribe_path = helpers()
    shop.get(unsubscribe_path("ada@example.com"))
    sub(shop, "ada@example.com")
    assert shop.get("/api/store/admin/subscribers", headers=STAFF).json()["count"] == 1


def test_unsubscribe_page_escapes_everything(shop):
    r = shop.get("/newsletter/unsubscribe?email=%3Cscript%3Ealert(1)%3C/script%3E&t=x")
    assert "<script>alert(1)" not in r.text


def test_only_staff_can_see_or_export_subscribers(shop):
    sub(shop, "ada@example.com")
    for url in ("/api/store/admin/subscribers", "/api/store/admin/subscribers.csv"):
        assert shop.get(url).status_code == 401
        assert shop.get(url, headers={"X-Staff-Key": "wrong"}).status_code == 401


def test_csv_export_lists_subscribers_and_is_audited(shop):
    sub(shop, "ada@example.com")
    sub(shop, "bola@example.com")
    r = shop.get("/api/store/admin/subscribers.csv", headers=STAFF)
    assert r.status_code == 200 and r.text.startswith("\ufeffEmail")
    rows = list(csv.reader(io.StringIO(r.text.lstrip("\ufeff"))))
    assert sorted(x[0] for x in rows[1:]) == ["ada@example.com", "bola@example.com"]
    assert any(
        e["action"] == "subscribers_exported"
        for e in shop.get("/api/store/admin/audit", headers=STAFF).json()["entries"]
    )


def test_admin_list_says_no_email_service_is_connected(shop):
    assert (
        shop.get("/api/store/admin/subscribers", headers=STAFF).json()["emailConfigured"] is False
    )
