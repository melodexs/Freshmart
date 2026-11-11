import pytest

SIGNUP = {
    "name": "Ada",
    "phone": "08011111111",
    "email": "Ada@Example.com",
    "password": "secret123",
    "passwordConfirm": "secret123",
}
ORDER = {
    "items": [{"productId": "p1", "optionIndex": 1, "qty": 2}],
    "address": "12 Market Rd",
    "phone": "08022222222",
    "city": "Ibadan",
    "payMethod": "delivery",
}


def signup(c, **over):
    return c.post("/api/auth/signup", json={**SIGNUP, **over})


def test_products(client):
    r = client.get("/api/products")
    j = r.json()
    assert r.status_code == 200 and j["deliveryFee"] == 800 and len(j["products"]) == 28


def test_signup_login_me_logout(client):
    r = signup(client)
    assert r.status_code == 200 and r.json() == {"name": "Ada", "email": "ada@example.com"}
    assert "httponly" in r.headers["set-cookie"].lower()
    assert client.get("/api/auth/me").json()["email"] == "ada@example.com"
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    r = client.post("/api/auth/login", json={"email": "ADA@example.com", "password": "secret123"})
    assert r.status_code == 200 and r.json()["name"] == "Ada"


@pytest.mark.parametrize(
    "over,msg",
    [
        ({"name": ""}, "Please add your name and phone number."),
        ({"email": ""}, "Please fill in email and password."),
        (
            {"password": "abc", "passwordConfirm": "abc"},
            "Password should be at least 6 characters.",
        ),
        ({"passwordConfirm": "different"}, "Passwords don't match. Please re-enter them."),
    ],
)
def test_signup_validation(client, over, msg):
    r = signup(client, **over)
    assert r.status_code == 400 and r.json()["error"] == msg


def test_duplicate_email(client):
    signup(client)
    r = signup(client, email="ada@example.com")
    assert r.status_code == 409


def test_bad_login(client):
    signup(client)
    assert (
        client.post(
            "/api/auth/login", json={"email": "ada@example.com", "password": "nope"}
        ).status_code
        == 401
    )
    assert (
        client.post("/api/auth/login", json={"email": "x@y.com", "password": "nope"}).status_code
        == 401
    )
    assert client.post("/api/auth/login", json={}).status_code == 400


def test_lookup(client):
    signup(client)
    assert client.get("/api/auth/lookup/ADA@example.com").json() == {
        "name": "Ada",
        "email": "ada@example.com",
    }
    assert client.get("/api/auth/lookup/ghost@x.com").status_code == 404


def test_order_requires_auth(client):
    assert client.post("/api/orders", json=ORDER).status_code == 401
    assert client.get("/api/orders/mine").status_code == 401


def test_order_prices_come_from_server(client):
    signup(client)
    body = {**ORDER, "items": [{"productId": "p1", "optionIndex": 1, "qty": 2, "price": 1}]}
    r = client.post("/api/orders", json=body)
    o = r.json()["order"]
    assert r.status_code == 200
    assert o["subtotal"] == 3800 and o["total"] == 4600 and o["items"][0]["price"] == 1900
    assert o["status"].startswith("Awaiting delivery")
    assert client.get("/api/orders/mine").json()["orders"][0]["id"] == o["id"]


def test_pay_before_status(client):
    signup(client)
    o = client.post("/api/orders", json={**ORDER, "payMethod": "before"}).json()["order"]
    assert o["status"] == "Payment confirmed"


@pytest.mark.parametrize(
    "patch,code",
    [
        ({"items": []}, 400),
        ({"items": [{"productId": "zzz", "optionIndex": 0, "qty": 1}]}, 400),
        ({"items": [{"productId": "p1", "optionIndex": 99, "qty": 1}]}, 400),
        ({"items": [{"productId": "p1", "optionIndex": 0, "qty": 0}]}, 400),
        ({"items": [{"productId": "p1", "optionIndex": 0, "qty": -3}]}, 400),
        ({"items": [{"productId": "p1", "optionIndex": 0, "qty": 1.5}]}, 400),
        ({"address": ""}, 400),
        ({"payMethod": "bitcoin"}, 400),
    ],
)
def test_order_validation(client, patch, code):
    signup(client)
    assert client.post("/api/orders", json={**ORDER, **patch}).status_code == code


def test_order_ids_unique(client):
    signup(client)
    ids = {client.post("/api/orders", json=ORDER).json()["order"]["id"] for _ in range(15)}
    assert len(ids) == 15


def test_orders_are_per_user(client):
    signup(client)
    client.post("/api/orders", json=ORDER)
    client.post("/api/auth/logout")
    signup(client, email="bob@example.com", name="Bob")
    assert client.get("/api/orders/mine").json()["orders"] == []


def test_store_feed_open_in_dev(client):
    signup(client)
    client.post("/api/orders", json=ORDER)
    n = client.get("/api/store/notifications").json()["notifications"]
    assert len(n) == 1 and "New order" in n[0]["text"]


def test_store_feed_needs_key_when_configured(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "STORE_STAFF_KEY", "s3cret")
    assert client.get("/api/store/notifications").status_code == 401
    assert (
        client.get("/api/store/notifications", headers={"X-Staff-Key": "wrong"}).status_code == 401
    )
    assert (
        client.get("/api/store/notifications", headers={"X-Staff-Key": "s3cret"}).status_code == 200
    )


def test_store_feed_disabled_in_production_without_key(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    assert client.get("/api/store/notifications").status_code == 403
    assert client.post("/api/store/login", json={"key": "x"}).status_code == 403
    assert client.get("/api/store/session").json() == {"enabled": False, "staff": False}


def test_staff_login_flow(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "STORE_STAFF_KEY", "s3cret")
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    assert client.get("/api/store/session").json() == {"enabled": True, "staff": False}
    bad = client.post("/api/store/login", json={"key": "nope"})
    assert bad.status_code == 401 and bad.json()["error"]
    assert client.get("/api/store/notifications").status_code == 401
    ok = client.post("/api/store/login", json={"key": "s3cret"})
    assert ok.status_code == 200
    sc = ok.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=strict" in sc and "path=/api/store" in sc
    assert client.get("/api/store/session").json() == {"enabled": True, "staff": True}
    assert client.get("/api/store/notifications").status_code == 200
    client.post("/api/store/logout")
    assert client.get("/api/store/notifications").status_code == 401


def test_customer_cookie_is_not_staff(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "STORE_STAFF_KEY", "s3cret")
    signup(client)
    assert client.get("/api/store/notifications").status_code == 401


def test_staff_login_rate_limited(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "STORE_STAFF_KEY", "s3cret")
    codes = [
        client.post("/api/store/login", json={"key": f"guess{i}"}).status_code for i in range(8)
    ]
    assert codes[:5] == [401] * 5 and 429 in codes


def test_login_rate_limit(client):
    codes = [
        client.post("/api/auth/login", json={"email": "a@b.com", "password": "x"}).status_code
        for _ in range(12)
    ]
    assert 429 in codes


def test_unknown_api_route_is_json_404(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json() == {"error": "Not found."}


def test_production_requires_jwt_secret(monkeypatch):
    import importlib
    import sys

    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    for m in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[m]
    with pytest.raises(RuntimeError):
        importlib.import_module("app.config")


def test_extra_security_headers_are_sent(client):
    h = client.get("/api/health").headers
    assert "camera=()" in h["permissions-policy"]
    assert h["cross-origin-opener-policy"] == "same-origin"


def test_csp_forbids_inline_and_foreign_scripts(client):
    csp = client.get("/").headers["content-security-policy"]
    assert "script-src 'self'" in csp and "'unsafe-inline'" not in csp.split("style-src")[0]
    assert "object-src 'none'" in csp and "frame-ancestors 'none'" in csp


def test_static_is_cacheable_but_pages_and_api_are_not(client):
    assert "max-age=86400" in client.get("/static/styles.css").headers["cache-control"]
    assert client.get("/").headers["cache-control"] == "no-store"
    assert client.get("/api/health").headers["cache-control"] == "no-store"


def test_ready_endpoint_checks_the_data_store(client, monkeypatch):
    assert client.get("/api/ready").json() == {"ok": True}
    from app import db

    async def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "get_all_orders", boom)
    r = client.get("/api/ready")
    assert r.status_code == 503 and r.json()["ok"] is False


def test_unexpected_error_hides_details_and_returns_json_for_api(client):
    from fastapi.testclient import TestClient

    from app.main import app

    async def boom():
        raise RuntimeError("secret internal detail")

    # Insert ahead of the /api catch-all so this route is the one that matches.
    app.router.add_api_route("/api/_boom_test", boom, methods=["GET"])
    app.router.routes.insert(0, app.router.routes.pop())

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/_boom_test")
        assert r.status_code == 500 and r.json() == {
            "error": "Something went wrong. Please try again."
        }
        assert "secret" not in r.text and r.headers["x-content-type-options"] == "nosniff"
        page = c.get("/_boom_test_page", headers={"accept": "text/html"})
        assert page.status_code == 404  # unknown page still gets the 404 page, not a crash


def test_order_rejects_invalid_phone_and_stores_the_normalised_one(client):
    signup(client)
    body = {
        "items": [{"productId": "p1", "optionIndex": 0, "qty": 1}],
        "address": "1 Main St",
        "payMethod": "delivery",
    }
    bad = client.post("/api/orders", json={**body, "phone": "12345"})
    assert bad.status_code == 400 and "valid Nigerian mobile" in bad.json()["error"]
    ok = client.post("/api/orders", json={**body, "phone": "+234 801 234 5678"})
    assert ok.status_code == 200 and ok.json()["order"]["phone"] == "08012345678"
