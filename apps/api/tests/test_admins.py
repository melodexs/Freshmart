"""Named admin accounts: owners above staff, forced first-password change, lockout, honest audit."""

from __future__ import annotations

import asyncio

import pytest

KEY = {"X-Staff-Key": "staff-secret-key"}
OWNER = {
    "name": "Onwe Christian Okwudiri",
    "email": "onwechristian02@gmail.com",
    "phone": "8130055678",
}
FIRST = "Temp-Start-1"
NEW = "A-Better-Passphrase-9"


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def shop(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "STORE_STAFF_KEY", "staff-secret-key")
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    monkeypatch.setattr(config, "FIRST_OWNER_NAME", OWNER["name"])
    monkeypatch.setattr(config, "FIRST_OWNER_EMAIL", OWNER["email"])
    monkeypatch.setattr(config, "FIRST_OWNER_PHONE", OWNER["phone"])
    monkeypatch.setattr(config, "FIRST_OWNER_PASSWORD", FIRST)
    from app.routes import admins

    run(admins.seed_first_owner())
    return client


def sign_in(c, email=OWNER["email"], password=FIRST):
    return c.post("/api/store/admin-login", json={"email": email, "password": password})


def owner_session(c):
    """Sign in as the owner and finish the forced password change."""
    assert sign_in(c).status_code == 200
    r = c.post("/api/store/change-password", json={"current": FIRST, "new": NEW})
    assert r.status_code == 200, r.text
    return c


def test_first_owner_is_created_once_with_nigerian_number_and_hashed_password(shop):
    from app import db
    from app.routes import admins

    a = run(db.get_admin(OWNER["email"]))
    assert a["role"] == "owner" and a["phone"] == "08130055678" and a["mustChange"] is True
    assert FIRST not in a["passHash"] and a["passHash"].startswith("$2")
    assert run(admins.seed_first_owner()) == "an owner already exists"
    assert len(run(db.list_admins())) == 1


def test_seed_does_nothing_without_settings_and_rejects_bad_phone(client, monkeypatch):
    from app import config, db
    from app.routes import admins

    assert run(admins.seed_first_owner()) == "no first owner configured"
    monkeypatch.setattr(config, "FIRST_OWNER_NAME", "Someone Real")
    monkeypatch.setattr(config, "FIRST_OWNER_EMAIL", "a@b.com")
    monkeypatch.setattr(config, "FIRST_OWNER_PHONE", "12345")
    monkeypatch.setattr(config, "FIRST_OWNER_PASSWORD", "longenough1")
    assert "incomplete or invalid" in run(admins.seed_first_owner())
    assert run(db.list_admins()) == []


def test_sign_in_works_and_must_change_flag_is_reported(shop):
    r = sign_in(shop)
    assert r.status_code == 200
    j = r.json()
    assert j["role"] == "owner" and j["mustChange"] is True and "passHash" not in r.text
    me = shop.get("/api/store/me").json()
    assert me["email"] == OWNER["email"] and me["level"] == "owner" and me["mustChange"] is True


def test_wrong_password_and_unknown_email_get_the_same_reply(shop):
    a = sign_in(shop, password="wrong-wrong-1")
    b = sign_in(shop, email="nobody@example.com", password="wrong-wrong-1")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()
    assert shop.get("/api/store/me").status_code == 401


def test_account_locks_after_five_wrong_passwords_even_for_the_right_one(shop):
    for _ in range(5):
        assert sign_in(shop, password="wrong-wrong-1").status_code == 401
    r = sign_in(shop)  # the correct password, but the account is locked
    assert r.status_code == 401 and r.json()["error"] == "Email or password is incorrect."


def test_successful_sign_in_resets_the_wrong_password_count(shop):
    from app import db

    for _ in range(3):
        sign_in(shop, password="wrong-wrong-1")
    assert sign_in(shop).status_code == 200
    assert run(db.get_admin(OWNER["email"]))["fails"] == 0


def test_change_password_rules(shop):
    sign_in(shop)
    bad = [
        ("short1A", "at least 10"),
        ("1234567890123", "not just a number"),
        ("Onwe-Christian-1", "name or email"),
        ("xx-okwudiri-77", "name or email"),
        ("onwechristian02-pw", "name or email"),
        ("abc-8130055678-xyz", "phone number"),
        (FIRST, "different"),
    ]
    for pw, word in bad:
        r = shop.post("/api/store/change-password", json={"current": FIRST, "new": pw})
        assert r.status_code == 400 and word in r.json()["error"], (pw, r.text)
    wrong = shop.post("/api/store/change-password", json={"current": "nope-nope-1", "new": NEW})
    assert wrong.status_code == 401
    ok = shop.post("/api/store/change-password", json={"current": FIRST, "new": NEW})
    assert ok.status_code == 200
    assert shop.get("/api/store/me").json()["mustChange"] is False
    shop.cookies.clear()
    assert sign_in(shop, password=FIRST).status_code == 401
    assert sign_in(shop, password=NEW).status_code == 200


def test_phone_number_cannot_be_kept_as_the_permanent_password(shop):
    sign_in(shop, password=FIRST)
    r = shop.post("/api/store/change-password", json={"current": FIRST, "new": "08130055678"})
    assert r.status_code == 400


def test_owner_can_create_staff_and_list_without_hashes(shop):
    owner_session(shop)
    r = shop.post(
        "/api/store/admin/admins",
        json={
            "name": "Ngozi Eze",
            "email": "ngozi@example.com",
            "phone": "0803 111 2222",
            "role": "staff",
            "password": "Start-Pass-1",
        },
    )
    assert r.status_code == 201
    listing = shop.get("/api/store/admin/admins")
    assert (
        listing.status_code == 200
        and "passHash" not in listing.text
        and "pass_hash" not in listing.text
    )
    people = listing.json()["admins"]
    assert [p["role"] for p in people] == ["owner", "staff"]
    assert people[1]["phone"] == "08031112222" and people[1]["mustChange"] is True
    dup = shop.post(
        "/api/store/admin/admins",
        json={
            "name": "Ngozi Eze",
            "email": "NGOZI@example.com",
            "phone": "0803 111 2222",
            "role": "staff",
            "password": "Start-Pass-1",
        },
    )
    assert dup.status_code == 409


def test_create_admin_validates_everything(shop):
    owner_session(shop)
    base = {
        "name": "Ngozi Eze",
        "email": "ngozi@example.com",
        "phone": "08031112222",
        "role": "staff",
        "password": "Start-Pass-1",
    }
    for patch in (
        {"name": "N"},
        {"email": "not-an-email"},
        {"phone": "12345"},
        {"role": "god"},
        {"password": "short"},
    ):
        r = shop.post("/api/store/admin/admins", json={**base, **patch})
        assert r.status_code == 400, patch


def test_staff_cannot_manage_admins_or_see_the_list(shop):
    owner_session(shop)
    shop.post(
        "/api/store/admin/admins",
        json={
            "name": "Ngozi Eze",
            "email": "ngozi@example.com",
            "phone": "08031112222",
            "role": "staff",
            "password": "Start-Pass-1",
        },
    )
    shop.cookies.clear()
    assert sign_in(shop, "ngozi@example.com", "Start-Pass-1").status_code == 200
    assert (
        shop.post(
            "/api/store/change-password",
            json={"current": "Start-Pass-1", "new": "Mango-Tree-Harvest-19"},
        ).status_code
        == 200
    )
    assert shop.get("/api/store/me").json()["level"] == "staff"
    assert shop.get("/api/store/admin/admins").status_code == 403
    r = shop.post(
        "/api/store/admin/admins",
        json={
            "name": "Sneaky Staff",
            "email": "s@example.com",
            "phone": "08031112222",
            "role": "owner",
            "password": "Start-Pass-1",
        },
    )
    assert r.status_code == 403
    assert (
        shop.post(
            "/api/store/admin/admins/onwechristian02@gmail.com/active", json={"active": False}
        ).status_code
        == 403
    )
    assert (
        shop.post(
            "/api/store/admin/admins/onwechristian02@gmail.com/reset-password",
            json={"password": "Hacked-Pass-1"},
        ).status_code
        == 403
    )
    # but staff can still do ordinary dashboard work
    assert shop.get("/api/store/admin/orders").status_code == 200


def test_the_shared_staff_key_can_never_act_as_owner(shop):
    assert shop.get("/api/store/admin/admins", headers=KEY).status_code == 403
    r = shop.post(
        "/api/store/admin/admins",
        headers=KEY,
        json={
            "name": "Key Holder",
            "email": "k@example.com",
            "phone": "08031112222",
            "role": "owner",
            "password": "Start-Pass-1",
        },
    )
    assert r.status_code == 403
    assert (
        shop.get("/api/store/admin/orders", headers=KEY).status_code == 200
    )  # still works as staff


def test_only_active_owner_cannot_be_deactivated_or_demoted(shop):
    owner_session(shop)
    em = OWNER["email"]
    assert (
        shop.post(f"/api/store/admin/admins/{em}/active", json={"active": False}).status_code == 409
    )
    assert (
        shop.post(f"/api/store/admin/admins/{em}/role", json={"role": "staff"}).status_code == 409
    )
    assert run(__import__("app.db", fromlist=["x"]).get_admin(em))["active"] is True


def test_with_two_owners_one_can_be_demoted_and_deactivated(shop):
    owner_session(shop)
    shop.post(
        "/api/store/admin/admins",
        json={
            "name": "Second Owner",
            "email": "second@example.com",
            "phone": "08031112222",
            "role": "owner",
            "password": "Start-Pass-1",
        },
    )
    assert (
        shop.post(
            "/api/store/admin/admins/second@example.com/role", json={"role": "staff"}
        ).status_code
        == 200
    )
    assert (
        shop.post(
            "/api/store/admin/admins/second@example.com/active", json={"active": False}
        ).status_code
        == 200
    )
    shop.cookies.clear()
    assert sign_in(shop, "second@example.com", "Start-Pass-1").status_code == 401


def test_deactivated_admin_loses_access_immediately_even_with_a_live_session(shop):
    owner_session(shop)
    shop.post(
        "/api/store/admin/admins",
        json={
            "name": "Ngozi Eze",
            "email": "ngozi@example.com",
            "phone": "08031112222",
            "role": "staff",
            "password": "Start-Pass-1",
        },
    )
    owner_cookies = dict(shop.cookies)
    shop.cookies.clear()
    sign_in(shop, "ngozi@example.com", "Start-Pass-1")
    assert shop.get("/api/store/me").status_code == 200
    staff_cookies = dict(shop.cookies)
    shop.cookies.clear()
    shop.cookies.update(owner_cookies)
    shop.post("/api/store/admin/admins/ngozi@example.com/active", json={"active": False})
    shop.cookies.clear()
    shop.cookies.update(staff_cookies)
    assert shop.get("/api/store/me").status_code == 401


def test_owner_reset_forces_a_change_and_clears_lock(shop):
    owner_session(shop)
    shop.post(
        "/api/store/admin/admins",
        json={
            "name": "Ngozi Eze",
            "email": "ngozi@example.com",
            "phone": "08031112222",
            "role": "staff",
            "password": "Start-Pass-1",
        },
    )
    r = shop.post(
        "/api/store/admin/admins/ngozi@example.com/reset-password",
        json={"password": "Another-Temp-2"},
    )
    assert r.status_code == 200
    from app import db

    a = run(db.get_admin("ngozi@example.com"))
    assert a["mustChange"] is True and a["fails"] == 0
    shop.cookies.clear()
    assert sign_in(shop, "ngozi@example.com", "Start-Pass-1").status_code == 401
    assert sign_in(shop, "ngozi@example.com", "Another-Temp-2").json()["mustChange"] is True


def test_audit_log_names_the_real_person_and_never_stores_passwords(shop):
    from app import db

    owner_session(shop)
    shop.post(
        "/api/store/admin/admins",
        json={
            "name": "Ngozi Eze",
            "email": "ngozi@example.com",
            "phone": "08031112222",
            "role": "staff",
            "password": "Start-Pass-1",
        },
    )
    rows = run(db.get_audit(limit=50))
    made = [
        r for r in rows if r["action"] == "admin_created" and r["subject"] == "ngozi@example.com"
    ]
    assert made and made[0]["actor"] == OWNER["name"]
    blob = str(rows)
    for secret in (FIRST, NEW, "Start-Pass-1", "08130055678", "$2b$"):
        assert secret not in blob


def test_confirm_payment_audit_names_the_admin_who_did_it(shop):
    from app import db

    shop.post(
        "/api/auth/signup",
        json={
            "name": "Ada Obi",
            "phone": "08011111111",
            "email": "ada@example.com",
            "password": "secret123",
            "passwordConfirm": "secret123",
        },
    )
    owner_session(shop)
    r = shop.post(
        "/api/orders",
        json={
            "items": [{"productId": "p1", "optionIndex": 1, "qty": 2}],
            "address": "12 Market Rd",
            "phone": "08022222222",
            "city": "Otukpo",
            "payMethod": "before",
        },
    )
    assert r.status_code == 200, r.text
    oid = r.json()["order"]["id"]
    assert r.json()["order"]["status"] == "Awaiting payment"
    c = shop.post(
        f"/api/store/admin/orders/{oid}/confirm-payment",
        json={"amount": 4600, "method": "bank transfer", "reference": "TRF-998877"},
    )
    assert c.status_code == 200, c.text
    rows = [x for x in run(db.get_audit(subject=oid)) if "payment" in x["action"]]
    assert rows and rows[0]["actor"] == OWNER["name"]
    assert rows[0]["actor"] != "admin"
    assert (
        shop.get(f"/api/orders/{oid}").json()["order"]["confirmedBy"] == OWNER["name"]
        if shop.get(f"/api/orders/{oid}").status_code == 200
        else True
    )
    assert run(db.get_order(oid))["paymentDetail"]["confirmedBy"] == OWNER["name"]


def test_admin_login_is_rate_limited(shop):
    codes = [sign_in(shop, "x@example.com", "wrong-wrong-1").status_code for _ in range(12)]
    assert 429 in codes


# ---------- the first password must be changed on the SERVER, not just on the screen ----------

STAFF_ROUTES = [
    ("GET", "/api/store/admin/orders"),
    ("GET", "/api/store/admin/overview"),
    ("GET", "/api/store/admin/customers"),
    ("GET", "/api/store/admin/products"),
    ("GET", "/api/store/admin/settings"),
    ("GET", "/api/store/admin/audit"),
    ("GET", "/api/store/admin/discounts"),
    ("GET", "/api/store/admin/reports"),
    ("GET", "/api/store/admin/orders.csv"),
    ("GET", "/api/store/admin/subscribers"),
    ("GET", "/api/store/admin/subscribers.csv"),
    ("GET", "/api/store/admin/reviews"),
    ("GET", "/api/store/admin/alerts"),
    ("GET", "/api/store/notifications"),
    ("GET", "/api/store/admin/admins"),
]


def test_before_changing_the_first_password_no_staff_route_works(shop):
    assert sign_in(shop).status_code == 200  # first password, not yet changed
    assert shop.get("/api/store/me").json()["mustChange"] is True  # still allowed: who am I
    for method, path in STAFF_ROUTES:
        r = shop.request(method, path)
        assert r.status_code == 403, (path, r.status_code)
        assert "Choose your own password" in r.text, path
    assert (
        shop.post(
            "/api/store/admin/admins",
            json={
                "name": "Sneaky Person",
                "email": "s@example.com",
                "phone": "08031112222",
                "role": "owner",
                "password": "Start-Pass-1",
            },
        ).status_code
        == 403
    )
    assert (
        shop.post(
            "/api/store/admin/orders/FM00000000/confirm-payment",
            json={"amount": 1, "method": "cash", "reference": "x"},
        ).status_code
        == 403
    )
    assert (
        shop.post(
            "/api/store/admin/orders/FM00000000/status", json={"status": "Confirmed"}
        ).status_code
        == 403
    )
    assert shop.get("/api/store/session").json()["staff"] is False


def _place_order(c):
    c.post(
        "/api/auth/signup",
        json={
            "name": "Ada Obi",
            "phone": "08011111111",
            "email": "ada@example.com",
            "password": "secret123",
            "passwordConfirm": "secret123",
        },
    )
    r = c.post(
        "/api/orders",
        json={
            "items": [{"productId": "p1", "optionIndex": 1, "qty": 2}],
            "address": "12 Market Rd",
            "phone": "08022222222",
            "city": "Otukpo",
            "payMethod": "before",
        },
    )
    assert r.status_code == 200, r.text
    c.cookies.clear()  # the customer signs out; the admin session is separate
    return r.json()["order"]["id"]


def test_the_inbox_page_hides_orders_until_the_password_is_changed(shop):
    oid = _place_order(shop)
    sign_in(shop)
    page = shop.get("/api/store/ui")
    assert (
        oid not in page.text and "12 Market Rd" not in page.text and "08022222222" not in page.text
    )
    assert "Staff key" in page.text  # it shows the sign-in box, not the feed
    r = shop.post(f"/ui/orders/{oid}/status", data={"status": "Confirmed"})
    assert oid not in r.text and "12 Market Rd" not in r.text
    shop.post("/api/store/change-password", json={"current": FIRST, "new": NEW})
    assert oid in shop.get("/api/store/ui").text  # after the change the feed opens


def test_after_changing_the_password_the_same_routes_work(shop):
    owner_session(shop)
    for path in (
        "/api/store/admin/orders",
        "/api/store/admin/overview",
        "/api/store/admin/admins",
        "/api/store/notifications",
    ):
        assert shop.get(path).status_code == 200, path
    assert shop.get("/api/store/session").json()["staff"] is True


def test_a_reset_puts_the_account_back_behind_the_password_change(shop):
    owner_session(shop)
    shop.post(
        "/api/store/admin/admins",
        json={
            "name": "Ngozi Eze",
            "email": "ngozi@example.com",
            "phone": "08031112222",
            "role": "staff",
            "password": "Start-Pass-1",
        },
    )
    owner_cookies = dict(shop.cookies)
    shop.cookies.clear()
    sign_in(shop, "ngozi@example.com", "Start-Pass-1")
    shop.post(
        "/api/store/change-password",
        json={"current": "Start-Pass-1", "new": "Mango-Tree-Harvest-19"},
    )
    assert shop.get("/api/store/admin/orders").status_code == 200
    staff_cookies = dict(shop.cookies)
    shop.cookies.clear()
    shop.cookies.update(owner_cookies)
    shop.post(
        "/api/store/admin/admins/ngozi@example.com/reset-password",
        json={"password": "Another-Temp-2"},
    )
    shop.cookies.clear()
    shop.cookies.update(staff_cookies)  # her old live session
    assert (
        shop.get("/api/store/admin/orders").status_code == 403
    )  # now blocked until she changes it again


def test_the_shared_key_is_not_affected_by_the_password_rule(shop):
    for method, path in STAFF_ROUTES[:3]:
        assert shop.request(method, path, headers=KEY).status_code == 200, path


def test_session_tells_the_dashboard_who_is_signed_in_without_an_error(shop):
    s = shop.get("/api/store/session").json()
    assert s["staff"] is False and s["signedIn"] is False  # signed out: no 401 needed to find out
    sign_in(shop)
    s = shop.get("/api/store/session").json()
    assert s["staff"] is False and s["signedIn"] is True  # signed in, must still change password
    shop.post("/api/store/change-password", json={"current": FIRST, "new": NEW})
    s = shop.get("/api/store/session").json()
    assert s["staff"] is True and s["signedIn"] is True
    shop.cookies.clear()
    assert (
        shop.get("/api/store/session", headers=KEY).json()["signedIn"] is False
    )  # shared key has no account
