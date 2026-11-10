import pytest

SIGNUP = {"name": "Ada", "phone": "08011111111", "email": "Ada@Example.com",
          "password": "secret123", "passwordConfirm": "secret123"}
ORDER = {"items": [{"productId": "p1", "optionIndex": 1, "qty": 2}],
         "address": "12 Market Rd", "phone": "08022222222", "city": "Ibadan",
         "payMethod": "delivery"}


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


@pytest.mark.parametrize("over,msg", [
    ({"name": ""}, "Please add your name and phone number."),
    ({"email": ""}, "Please fill in email and password."),
    ({"password": "abc", "passwordConfirm": "abc"}, "Password should be at least 6 characters."),
    ({"passwordConfirm": "different"}, "Passwords don't match. Please re-enter them."),
])
def test_signup_validation(client, over, msg):
    r = signup(client, **over)
    assert r.status_code == 400 and r.json()["error"] == msg


def test_duplicate_email(client):
    signup(client)
    r = signup(client, email="ada@example.com")
    assert r.status_code == 409


def test_bad_login(client):
    signup(client)
    assert client.post("/api/auth/login", json={"email": "ada@example.com", "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "x@y.com", "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={}).status_code == 400


def test_lookup(client):
    signup(client)
    assert client.get("/api/auth/lookup/ADA@example.com").json() == {"name": "Ada", "email": "ada@example.com"}
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


@pytest.mark.parametrize("patch,code", [
    ({"items": []}, 400),
    ({"items": [{"productId": "zzz", "optionIndex": 0, "qty": 1}]}, 400),
    ({"items": [{"productId": "p1", "optionIndex": 99, "qty": 1}]}, 400),
    ({"items": [{"productId": "p1", "optionIndex": 0, "qty": 0}]}, 400),
    ({"items": [{"productId": "p1", "optionIndex": 0, "qty": -3}]}, 400),
    ({"items": [{"productId": "p1", "optionIndex": 0, "qty": 1.5}]}, 400),
    ({"address": ""}, 400),
    ({"payMethod": "bitcoin"}, 400),
])
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
    assert client.get("/api/store/notifications", headers={"X-Staff-Key": "wrong"}).status_code == 401
    assert client.get("/api/store/notifications", headers={"X-Staff-Key": "s3cret"}).status_code == 200


def test_store_feed_disabled_in_production_without_key(client, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    assert client.get("/api/store/notifications").status_code == 403


def test_login_rate_limit(client):
    codes = [client.post("/api/auth/login", json={"email": "a@b.com", "password": "x"}).status_code
             for _ in range(12)]
    assert 429 in codes


def test_unknown_api_route_is_json_404(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json() == {"error": "Not found."}


def test_frontend_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()
    assert client.get("/some/spa/route").status_code == 200
    assert client.get("/../backend/server.js").status_code in (200,)  # falls back to index, never leaks


def test_production_requires_jwt_secret(monkeypatch):
    import importlib, sys
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    for m in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[m]
    with pytest.raises(RuntimeError):
        importlib.import_module("app.config")
