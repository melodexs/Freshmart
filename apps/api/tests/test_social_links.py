"""Footer social links: only real https links on the named network, shown only when set."""

from __future__ import annotations

import pytest

STAFF = {"X-Staff-Key": "staff-secret-key"}


@pytest.fixture
def shop(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "STORE_STAFF_KEY", "staff-secret-key")
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    return client


def put(c, social):
    return c.put("/api/store/admin/settings", json={"social": social}, headers=STAFF)


@pytest.mark.parametrize(
    ("net", "good"),
    [
        ("facebook", "https://www.facebook.com/okwuigrocery"),
        ("facebook", "facebook.com/okwuigrocery"),
        ("instagram", "https://instagram.com/okwui_grocery"),
        ("x", "https://x.com/okwui"),
        ("x", "https://twitter.com/okwui"),
        ("tiktok", "https://www.tiktok.com/@okwui"),
        ("youtube", "https://youtu.be/abc123"),
    ],
)
def test_real_links_are_accepted(shop, net, good):
    assert put(shop, {net: good}).status_code == 200


@pytest.mark.parametrize(
    ("net", "bad"),
    [
        ("facebook", "javascript:alert(1)"),
        ("facebook", "https://facebook.com.evil.com/x"),
        ("facebook", "https://evilfacebook.com/x"),
        ("facebook", "http://facebook.com/x"),
        ("facebook", "https://facebook.com@evil.com/x"),
        ("facebook", "https://user:pw@facebook.com/x"),
        ("facebook", 'https://facebook.com/x" onclick="alert(1)'),
        ("facebook", "https://facebook.com/<script>"),
        ("instagram", "https://facebook.com/x"),
        ("x", "data:text/html,hi"),
        ("facebook", "https://facebook.com:8443/x"),
        ("facebook", "https://facebook.com/" + "a" * 300),
    ],
)
def test_dangerous_or_wrong_links_are_refused(shop, net, bad):
    r = put(shop, {net: bad})
    assert r.status_code == 400 and "valid" in r.json()["error"]
    assert "social" not in shop.get("/").text.lower() or bad not in shop.get("/").text


def test_footer_shows_only_links_that_are_set(shop):
    assert 'aria-label="Follow us"' not in shop.get("/").text  # nothing invented
    put(shop, {"facebook": "https://facebook.com/okwuigrocery"})
    page = shop.get("/").text
    assert 'href="https://facebook.com/okwuigrocery"' in page and "Instagram" not in page
    assert 'rel="noopener noreferrer"' in page


def test_clearing_a_link_removes_it(shop):
    put(shop, {"facebook": "https://facebook.com/okwuigrocery"})
    put(shop, {"facebook": ""})
    assert "facebook.com/okwuigrocery" not in shop.get("/").text


def test_links_show_on_product_and_account_pages_too(shop):
    put(shop, {"instagram": "https://instagram.com/okwui_grocery"})
    for url in ("/product/p1", "/account"):
        assert "instagram.com/okwui_grocery" in shop.get(url).text, url


def test_only_staff_can_change_links_and_changes_are_audited(shop):
    assert (
        shop.put(
            "/api/store/admin/settings", json={"social": {"facebook": "https://facebook.com/x"}}
        ).status_code
        == 401
    )
    put(shop, {"facebook": "https://facebook.com/okwuigrocery"})
    log = shop.get("/api/store/admin/audit", headers=STAFF).json()["entries"]
    assert any(e["action"] == "social_links_changed" for e in log)


def test_saving_one_network_keeps_the_others(shop):
    put(shop, {"facebook": "https://facebook.com/a"})
    put(shop, {"instagram": "https://instagram.com/b"})
    s = shop.get("/api/store/admin/settings", headers=STAFF).json()["social"]
    assert s == {"facebook": "https://facebook.com/a", "instagram": "https://instagram.com/b"}
