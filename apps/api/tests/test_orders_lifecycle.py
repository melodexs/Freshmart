"""Order lifecycle: staff status updates, customer cancel, and public tracking."""

from __future__ import annotations

from app import order_status


def signup(c, email="ada@example.com"):
    return c.post(
        "/ui/signup",
        data={
            "name": "Ada Bello",
            "phone": "08011111111",
            "email": email,
            "password": "secret12",
            "password_confirm": "secret12",
        },
    )


def place(c, pay="delivery", phone="08022222222"):
    r = c.post(
        "/api/orders",
        json={
            "items": [{"productId": "p1", "optionIndex": 0, "qty": 2}],
            "address": "1 Main St",
            "phone": phone,
            "city": "Otukpo",
            "payMethod": pay,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["order"]


def staff(c, monkeypatch, key="s3cret"):
    from app import config

    monkeypatch.setattr(config, "STORE_STAFF_KEY", key)
    assert c.post("/api/store/ui/login", data={"key": key}).status_code == 200


def status_of(c, order_id):
    return next(o for o in c.get("/api/orders/mine").json()["orders"] if o["id"] == order_id)[
        "status"
    ]


# ---------- rules ----------


def test_initial_status_comes_from_the_lifecycle(client):
    signup(client)
    assert place(client, "before")["status"] == order_status.PAID
    assert place(client, "delivery")["status"] == order_status.AWAITING


def test_rules_forbid_skipping_steps():
    assert order_status.staff_may_move(order_status.PAID, order_status.PREPARING)
    assert not order_status.staff_may_move(order_status.PAID, order_status.DELIVERED)
    assert not order_status.staff_may_move(order_status.DELIVERED, order_status.CANCELLED)
    assert not order_status.staff_may_move(order_status.CANCELLED, order_status.PREPARING)
    assert not order_status.customer_may_cancel(order_status.OUT)


# ---------- staff ----------


def test_staff_can_walk_an_order_to_delivered(client, monkeypatch):
    signup(client)
    o = place(client)
    staff(client, monkeypatch)
    for target in (order_status.PREPARING, order_status.OUT, order_status.DELIVERED):
        r = client.post(f"/api/store/ui/orders/{o['id']}/status", data={"status": target})
        assert r.status_code == 200 and f"is now: {target}" in r.text
        assert status_of(client, o["id"]) == target


def test_staff_cannot_make_an_invalid_move(client, monkeypatch):
    signup(client)
    o = place(client)
    staff(client, monkeypatch)
    r = client.post(
        f"/api/store/ui/orders/{o['id']}/status", data={"status": order_status.DELIVERED}
    )
    assert "cannot move" in r.text
    assert status_of(client, o["id"]) == order_status.AWAITING


def test_status_update_requires_staff(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "STORE_STAFF_KEY", "s3cret")
    signup(client)  # a customer, not staff
    o = place(client)
    r = client.post(
        f"/api/store/ui/orders/{o['id']}/status", data={"status": order_status.PREPARING}
    )
    assert r.status_code == 401
    assert status_of(client, o["id"]) == order_status.AWAITING


def test_staff_cancelling_a_prepaid_order_shows_a_refund_reminder(client, monkeypatch):
    signup(client)
    o = place(client, "before")
    staff(client, monkeypatch)
    r = client.post(
        f"/api/store/ui/orders/{o['id']}/status", data={"status": order_status.CANCELLED}
    )
    assert "refund" in r.text.lower()


def test_unknown_order_is_reported_not_crashed(client, monkeypatch):
    staff(client, monkeypatch)
    r = client.post(
        "/api/store/ui/orders/FMDOESNOTEXIST/status", data={"status": order_status.PREPARING}
    )
    assert r.status_code == 200 and "not found" in r.text


# ---------- customer cancel ----------


def test_customer_can_cancel_before_it_leaves_the_store(client):
    signup(client)
    o = place(client)
    r = client.post(f"/ui/orders/{o['id']}/cancel")
    assert r.status_code == 200 and "was cancelled" in r.text
    assert status_of(client, o["id"]) == order_status.CANCELLED


def test_customer_cancel_of_prepaid_order_mentions_refund(client):
    signup(client)
    o = place(client, "before")
    assert "refund" in client.post(f"/ui/orders/{o['id']}/cancel").text.lower()


def test_customer_cannot_cancel_once_out_for_delivery(client, monkeypatch):
    signup(client)
    o = place(client)
    staff(client, monkeypatch)
    for target in (order_status.PREPARING, order_status.OUT):
        client.post(f"/api/store/ui/orders/{o['id']}/status", data={"status": target})
    r = client.post(f"/ui/orders/{o['id']}/cancel")
    assert "can no longer be cancelled" in r.text
    assert status_of(client, o["id"]) == order_status.OUT


def test_cancel_button_only_shown_while_cancellable(client, monkeypatch):
    signup(client)
    o = place(client)
    assert "Cancel order" in client.get("/ui/orders").text
    staff(client, monkeypatch)
    for target in (order_status.PREPARING, order_status.OUT):
        client.post(f"/api/store/ui/orders/{o['id']}/status", data={"status": target})
    assert "Cancel order" not in client.get("/ui/orders").text


def test_cannot_cancel_someone_elses_order(client):
    signup(client, "owner@example.com")
    o = place(client)
    client.post("/ui/logout")
    signup(client, "other@example.com")
    r = client.post(f"/ui/orders/{o['id']}/cancel")
    assert "not found" in r.text  # same answer as a missing order
    client.post("/ui/logout")
    client.post("/ui/login", data={"email": "owner@example.com", "password": "secret12"})
    assert status_of(client, o["id"]) == order_status.AWAITING


def test_cancel_requires_sign_in(client):
    assert client.post("/ui/orders/FMX/cancel").status_code == 401


# ---------- public tracking ----------


def test_track_needs_reference_and_matching_phone(client):
    signup(client)
    o = place(client, phone="08022222222")
    client.post("/ui/logout")  # tracking must work without an account
    ok = client.post("/ui/track", data={"order_id": o["id"], "phone": "08022222222"})
    assert o["id"] in ok.text and order_status.AWAITING in ok.text
    wrong = client.post("/ui/track", data={"order_id": o["id"], "phone": "08033333333"})
    assert o["id"] not in wrong.text and "could not find" in wrong.text


def test_track_accepts_international_phone_format(client):
    signup(client)
    o = place(client, phone="08022222222")
    r = client.post("/ui/track", data={"order_id": o["id"].lower(), "phone": "+234 802 222 2222"})
    assert o["id"] in r.text


def test_track_gives_same_answer_for_missing_and_mismatched(client):
    signup(client)
    o = place(client)
    missing = client.post("/ui/track", data={"order_id": "FM00000000", "phone": "08022222222"}).text
    mismatch = client.post("/ui/track", data={"order_id": o["id"], "phone": "08099999999"}).text
    assert "could not find" in missing and "could not find" in mismatch


def test_track_never_reveals_address_or_phone(client):
    signup(client)
    o = place(client)
    r = client.post("/ui/track", data={"order_id": o["id"], "phone": "08022222222"})
    assert "1 Main St" not in r.text and "08022222222" not in r.text


def test_track_is_rate_limited(client):
    codes = [
        client.post(
            "/ui/track", data={"order_id": f"FM{i:08d}", "phone": "08022222222"}
        ).status_code
        for i in range(14)
    ]
    assert 429 in codes
