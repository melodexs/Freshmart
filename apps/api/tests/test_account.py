"""The customer's own account: profile, saved addresses and password, isolated per customer."""

from __future__ import annotations

import pytest

ADA = {
    "name": "Ada Obi",
    "phone": "08011111111",
    "email": "ada@example.com",
    "password": "secret123",
    "passwordConfirm": "secret123",
}
BOLA = {
    "name": "Bola Eze",
    "phone": "08033333333",
    "email": "bola@example.com",
    "password": "hunter2222",
    "passwordConfirm": "hunter2222",
}
HOME = {"label": "Home", "area": "Otukpo", "address": "12 Market Road", "phone": "0802 222 2222"}


def switch(client, who):
    client.post("/api/auth/logout")
    r = client.post("/api/auth/login", json={"email": who["email"], "password": who["password"]})
    if r.status_code != 200:
        client.post("/api/auth/signup", json=who)


@pytest.fixture
def two(client):
    client.post("/api/auth/signup", json=ADA)
    client.post("/api/auth/logout")
    client.post("/api/auth/signup", json=BOLA)
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": ADA["email"], "password": ADA["password"]})
    return client


ROUTES = [
    ("get", "/api/account"),
    ("put", "/api/account/profile"),
    ("post", "/api/account/addresses"),
    ("put", "/api/account/addresses/x"),
    ("delete", "/api/account/addresses/x"),
    ("post", "/api/account/password"),
]


@pytest.mark.parametrize(("method", "url"), ROUTES)
def test_every_account_route_needs_a_signed_in_customer(client, method, url):
    assert getattr(client, method)(url).status_code == 401


def test_account_summary(two):
    d = two.get("/api/account").json()
    assert d["profile"] == {"name": "Ada Obi", "email": "ada@example.com", "phone": "08011111111"}
    assert d["addresses"] == [] and d["orderCount"] == 0 and d["totalSpent"] == 0


def test_account_summary_counts_orders_and_ignores_cancelled(two):
    def o():
        return two.post(
            "/api/orders",
            json={
                "items": [{"productId": "p1", "optionIndex": 0, "qty": 1}],
                "address": "12 Market Rd",
                "phone": "08022222222",
                "city": "Otukpo",
                "payMethod": "delivery",
            },
        ).json()["order"]

    a, b = o(), o()
    two.post(f"/ui/orders/{b['id']}/cancel")
    d = two.get("/api/account").json()
    assert d["orderCount"] == 2 and d["totalSpent"] == a["total"]


def test_profile_can_be_changed_and_the_session_name_refreshes(two):
    r = two.put(
        "/api/account/profile", json={"name": "  Adaeze   Obi ", "phone": "+234 801 999 8888"}
    )
    assert (
        r.status_code == 200
        and r.json()["profile"]["name"] == "Adaeze Obi"
        and r.json()["profile"]["phone"] == "08019998888"
    )
    assert two.get("/api/auth/me").json()["name"] == "Adaeze Obi", (
        "the cookie must carry the new name"
    )
    assert two.get("/api/account").json()["profile"]["phone"] == "08019998888"
    assert "Adaeze" in two.get("/ui/header").text


@pytest.mark.parametrize(
    "body",
    [
        {"name": "", "phone": "08011111111"},
        {"name": "A", "phone": "08011111111"},
        {"name": "Ada", "phone": "12345"},
        {"name": "Ada"},
        {},
    ],
)
def test_bad_profile_input_is_refused(two, body):
    assert two.put("/api/account/profile", json=body).status_code == 400
    assert two.get("/api/account").json()["profile"]["name"] == "Ada Obi"


def test_the_email_cannot_be_changed_through_the_profile(two):
    two.put(
        "/api/account/profile",
        json={"name": "Ada Obi", "phone": "08011111111", "email": "hacker@example.com"},
    )
    assert two.get("/api/account").json()["profile"]["email"] == "ada@example.com"


def test_add_addresses_the_first_becomes_the_default(two):
    a = two.post("/api/account/addresses", json=HOME).json()["address"]
    assert a["isDefault"] is True and a["phone"] == "08022222222" and a["id"].startswith("ad")
    b = two.post(
        "/api/account/addresses", json={**HOME, "label": "Work", "address": "5 Station Road"}
    ).json()["address"]
    assert b["isDefault"] is False
    assert [x["label"] for x in two.get("/api/account").json()["addresses"]] == ["Home", "Work"]


def test_setting_a_new_default_clears_the_old_one(two):
    two.post("/api/account/addresses", json=HOME)
    b = two.post(
        "/api/account/addresses", json={**HOME, "label": "Work", "isDefault": True}
    ).json()["address"]
    addrs = two.get("/api/account").json()["addresses"]
    assert [a["label"] for a in addrs if a["isDefault"]] == ["Work"] and addrs[0]["id"] == b["id"]


def test_edit_and_delete_an_address_and_a_default_is_always_kept(two):
    a = two.post("/api/account/addresses", json=HOME).json()["address"]
    b = two.post("/api/account/addresses", json={**HOME, "label": "Work"}).json()["address"]
    r = two.put(
        f"/api/account/addresses/{b['id']}",
        json={**HOME, "label": "Office", "address": "9 New Road"},
    )
    assert r.json()["address"]["label"] == "Office"
    assert two.delete(f"/api/account/addresses/{a['id']}").json() == {"deleted": True}
    left = two.get("/api/account").json()["addresses"]
    assert len(left) == 1 and left[0]["isDefault"] is True and left[0]["label"] == "Office"


@pytest.mark.parametrize(
    "patch",
    [
        {"area": "Lagos"},
        {"area": ""},
        {"address": "x"},
        {"address": ""},
        {"phone": "123"},
        {"phone": ""},
    ],
)
def test_bad_addresses_are_refused(two, patch):
    assert two.post("/api/account/addresses", json={**HOME, **patch}).status_code == 400
    assert two.get("/api/account").json()["addresses"] == []


def test_at_most_ten_addresses(two):
    for i in range(10):
        assert (
            two.post("/api/account/addresses", json={**HOME, "label": f"A{i}"}).status_code == 200
        )
    r = two.post("/api/account/addresses", json=HOME)
    assert r.status_code == 409 and "up to 10" in r.json()["error"]


def test_addresses_are_private_to_each_customer(two):
    a = two.post("/api/account/addresses", json=HOME).json()["address"]
    switch(two, BOLA)
    assert two.get("/api/account").json()["addresses"] == []
    assert (
        two.put(
            f"/api/account/addresses/{a['id']}", json={**HOME, "address": "stolen street"}
        ).status_code
        == 404
    )
    assert two.delete(f"/api/account/addresses/{a['id']}").status_code == 404
    switch(two, ADA)
    got = two.get("/api/account").json()["addresses"]
    assert len(got) == 1 and got[0]["address"] == "12 Market Road", (
        "Bola could not touch Ada's address"
    )


def test_profile_changes_do_not_leak_between_customers(two):
    two.put("/api/account/profile", json={"name": "Ada Changed", "phone": "08011111111"})
    switch(two, BOLA)
    assert two.get("/api/account").json()["profile"]["name"] == "Bola Eze"


def test_change_password(two):
    r = two.post(
        "/api/account/password", json={"currentPassword": "secret123", "newPassword": "brandnew99"}
    )
    assert r.status_code == 200
    two.post("/api/auth/logout")
    assert (
        two.post(
            "/api/auth/login", json={"email": ADA["email"], "password": "secret123"}
        ).status_code
        != 200
    )
    assert (
        two.post(
            "/api/auth/login", json={"email": ADA["email"], "password": "brandnew99"}
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"currentPassword": "wrong", "newPassword": "brandnew99"}, 403),
        ({"currentPassword": "", "newPassword": "brandnew99"}, 403),
        ({"currentPassword": "secret123", "newPassword": "123"}, 400),
        ({"currentPassword": "secret123", "newPassword": "secret123"}, 400),
        ({"newPassword": "brandnew99"}, 403),
    ],
)
def test_bad_password_changes_are_refused_and_change_nothing(two, body, code):
    assert two.post("/api/account/password", json=body).status_code == code
    two.post("/api/auth/logout")
    assert (
        two.post(
            "/api/auth/login", json={"email": ADA["email"], "password": "secret123"}
        ).status_code
        == 200
    )


def test_password_guessing_is_rate_limited(two):
    codes = [
        two.post(
            "/api/account/password",
            json={"currentPassword": f"guess{i}", "newPassword": "brandnew99"},
        ).status_code
        for i in range(12)
    ]
    assert 429 in codes, (
        "an attacker with a stolen session must not be able to guess the current password forever"
    )


def test_account_responses_never_contain_a_password_hash(two):
    two.post("/api/account/addresses", json=HOME)
    for url in ("/api/account",):
        t = two.get(url).text.lower()
        assert "passhash" not in t and "$2b$" not in t and "pass_hash" not in t
