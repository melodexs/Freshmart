"""Verified-purchase reviews: only real, received purchases; honest numbers; staff can hide, never edit."""

from __future__ import annotations

import pytest

from app.routes.reviews import bought_and_received, clean_body, public, summarise

STAFF = {"X-Staff-Key": "staff-secret-key"}
ADA = {
    "name": "Ada Obi",
    "phone": "08011111111",
    "email": "ada@example.com",
    "password": "secret123",
    "passwordConfirm": "secret123",
}
BOLA = {
    "name": "Bola Ade",
    "phone": "08022222222",
    "email": "bola@example.com",
    "password": "secret123",
    "passwordConfirm": "secret123",
}


@pytest.fixture
def shop(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "STORE_STAFF_KEY", "staff-secret-key")
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    return client


def signup(c, who):
    assert c.post("/api/auth/signup", json=who).status_code in (200, 201)


def login(c, who):
    c.post("/api/auth/logout")
    assert (
        c.post(
            "/api/auth/login", json={"email": who["email"], "password": who["password"]}
        ).status_code
        == 200
    )


def place(c, pid="p1", phone="08011111111"):
    r = c.post(
        "/api/orders",
        json={
            "items": [{"productId": pid, "optionIndex": 0, "qty": 1}],
            "address": "12 Market Rd",
            "phone": phone,
            "city": "Otukpo",
            "payMethod": "delivery",
            "name": "Ada Obi",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["order"]["id"]


def set_status(c, oid, status):
    assert (
        c.post(
            f"/api/store/admin/orders/{oid}/status", json={"status": status}, headers=STAFF
        ).status_code
        == 200
    )


def deliver(c, oid):
    """Walk an order through the real staff steps to Delivered. Fails loudly if a step is refused."""
    from app import order_status as os_

    for st in (os_.PREPARING, os_.READY, os_.OUT, os_.DELIVERED):
        r = c.post(f"/api/store/admin/orders/{oid}/status", json={"status": st}, headers=STAFF)
        assert r.status_code == 200, (st, r.text)


def review(c, pid="p1", rating=5, body="Lovely rice"):
    return c.post(f"/api/products/{pid}/reviews", json={"rating": rating, "body": body})


# ---- pure rules ----
def test_only_delivered_orders_containing_the_product_count():
    items = [{"productId": "p1"}]
    assert bought_and_received([{"status": "Delivered", "items": items}], "p1")
    assert not bought_and_received([{"status": "Delivered", "items": items}], "p2")
    for st in ("Cancelled", "Out for delivery", "Awaiting payment", "Confirmed"):
        assert not bought_and_received([{"status": st, "items": items}], "p1")
    assert not bought_and_received(
        [{"status": "Delivered", "items": [{"name": "Old order with no product id"}]}], "p1"
    )
    assert not bought_and_received([], "p1")


def test_summary_is_exact_and_empty_means_no_stars():
    assert summarise([]) == {
        "count": 0,
        "average": None,
        "stars": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0},
    }
    s = summarise([{"rating": 5}, {"rating": 4}, {"rating": 4}])
    assert s["count"] == 3 and s["average"] == 4.3 and s["stars"]["4"] == 2 and s["stars"]["5"] == 1


def test_public_review_never_shows_the_email_or_last_name():
    p = public(
        {
            "email": "ada@example.com",
            "productId": "p1",
            "name": "Ada Obi",
            "rating": 5,
            "body": "x",
            "updated": "2026-11-21T10:00:00Z",
        }
    )
    assert p["name"] == "Ada" and "email" not in p and "ada@example.com" not in str(p)


def test_body_is_trimmed_and_capped():
    assert clean_body("  hello   world  ") == "hello world"
    assert len(clean_body("x" * 5000)) == 600 and clean_body(None) == "" and clean_body(12) == ""


# ---- HTTP ----
def test_no_reviews_means_no_stars_and_no_testimonials(shop):
    d = shop.get("/api/products/p1/reviews").json()
    assert (
        d["summary"]["count"] == 0
        and d["summary"]["average"] is None
        and d["reviews"] == []
        and d["canReview"] is False
    )
    assert shop.get("/api/reviews/recent").json() == {"reviews": []}


def test_signed_out_cannot_review(shop):
    assert review(shop).status_code == 401


def test_cannot_review_without_buying(shop):
    signup(shop, ADA)
    r = review(shop)
    assert r.status_code == 403 and "received" in r.json()["error"]


def test_cannot_review_while_the_order_is_not_delivered(shop):
    signup(shop, ADA)
    oid = place(shop)
    assert review(shop).status_code == 403
    set_status(shop, oid, "Cancelled")
    assert review(shop).status_code == 403


def test_delivered_customer_can_review_once_and_edit(shop):
    signup(shop, ADA)
    deliver(shop, place(shop))
    assert shop.get("/api/products/p1/reviews").json()["canReview"] is True
    assert review(shop, rating=4, body="Good").status_code == 200
    assert review(shop, rating=5, body="Actually great").status_code == 200
    d = shop.get("/api/products/p1/reviews").json()
    assert d["summary"]["count"] == 1 and d["summary"]["average"] == 5.0
    assert d["reviews"][0]["body"] == "Actually great" and d["reviews"][0]["name"] == "Ada"
    assert d["mine"]["rating"] == 5


def test_reviewing_a_different_product_is_refused(shop):
    signup(shop, ADA)
    deliver(shop, place(shop, "p1"))
    assert review(shop, "p2").status_code == 403


def test_one_customer_cannot_review_on_anothers_purchase(shop):
    signup(shop, ADA)
    deliver(shop, place(shop))
    shop.post("/api/auth/logout")
    signup(shop, BOLA)
    assert review(shop).status_code == 403


def test_rating_must_be_a_whole_number_from_1_to_5(shop):
    signup(shop, ADA)
    deliver(shop, place(shop))
    for bad in (0, 6, -1, 3.5, "5", None, True):
        assert (
            shop.post("/api/products/p1/reviews", json={"rating": bad, "body": "x"}).status_code
            == 400
        ), bad


def test_unknown_product_is_a_404(shop):
    signup(shop, ADA)
    assert shop.get("/api/products/nope/reviews").status_code == 404
    assert review(shop, "nope").status_code == 404


def test_markup_in_a_review_is_stored_as_text_and_never_exposes_the_email(shop):
    signup(shop, ADA)
    deliver(shop, place(shop))
    review(shop, body="<script>alert(1)</script> nice")
    raw = shop.get("/api/products/p1/reviews").text
    assert "ada@example.com" not in raw
    page = shop.get("/product/p1").text
    assert "<script>alert(1)</script>" not in page


def test_recent_shows_only_written_reviews(shop):
    signup(shop, ADA)
    deliver(shop, place(shop))
    review(shop, rating=5, body="")
    assert shop.get("/api/reviews/recent").json()["reviews"] == []
    review(shop, rating=5, body="Fresh and quick")
    got = shop.get("/api/reviews/recent").json()["reviews"]
    assert len(got) == 1 and got[0]["body"] == "Fresh and quick" and got[0]["product"]


def test_staff_can_hide_and_restore_and_it_is_audited(shop):
    signup(shop, ADA)
    deliver(shop, place(shop))
    review(shop)
    r = shop.post(
        "/api/store/admin/reviews/hide",
        json={"email": "ada@example.com", "productId": "p1", "hidden": True},
        headers=STAFF,
    )
    assert r.status_code == 200
    d = shop.get("/api/products/p1/reviews").json()
    assert d["summary"]["count"] == 0 and d["reviews"] == [] and d["mine"]["hidden"] is True
    assert shop.get("/api/reviews/recent").json()["reviews"] == []
    assert (
        len(shop.get("/api/store/admin/reviews", headers=STAFF).json()["reviews"]) == 1
    )  # staff still see it
    shop.post(
        "/api/store/admin/reviews/hide",
        json={"email": "ada@example.com", "productId": "p1", "hidden": False},
        headers=STAFF,
    )
    assert shop.get("/api/products/p1/reviews").json()["summary"]["count"] == 1
    actions = [
        e["action"] for e in shop.get("/api/store/admin/audit", headers=STAFF).json()["entries"]
    ]
    assert "review_hidden" in actions and "review_shown" in actions


def test_editing_a_hidden_review_does_not_unhide_it(shop):
    signup(shop, ADA)
    deliver(shop, place(shop))
    review(shop)
    shop.post(
        "/api/store/admin/reviews/hide",
        json={"email": "ada@example.com", "productId": "p1", "hidden": True},
        headers=STAFF,
    )
    review(shop, body="Trying to sneak back in")
    assert shop.get("/api/products/p1/reviews").json()["summary"]["count"] == 0


def test_only_staff_can_moderate(shop):
    signup(shop, ADA)
    for url, method in (
        ("/api/store/admin/reviews", "get"),
        ("/api/store/admin/reviews/hide", "post"),
    ):
        assert getattr(shop, method)(url).status_code == 401
        assert getattr(shop, method)(url, headers={"X-Staff-Key": "wrong"}).status_code == 401
    assert (
        shop.post(
            "/api/store/admin/reviews/hide", json={"email": "a", "productId": "p1", "hidden": True}
        ).status_code
        == 401
    )


def test_hide_validates_its_input(shop):
    for bad in (
        {},
        {"email": "x", "productId": "p1"},
        {"email": "x", "productId": "p1", "hidden": "yes"},
    ):
        assert (
            shop.post("/api/store/admin/reviews/hide", json=bad, headers=STAFF).status_code == 400
        )
    assert (
        shop.post(
            "/api/store/admin/reviews/hide",
            json={"email": "no@x.com", "productId": "p1", "hidden": True},
            headers=STAFF,
        ).status_code
        == 404
    )
