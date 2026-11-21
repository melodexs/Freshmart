"""The live catalogue: seeded once, editable, and the order flow respects stock and activity."""

from __future__ import annotations

import asyncio

SIGNUP = {
    "name": "Ada",
    "phone": "08011111111",
    "email": "ada@example.com",
    "password": "secret123",
    "passwordConfirm": "secret123",
}


def order(client, items):
    return client.post(
        "/api/orders",
        json={
            "items": items,
            "address": "12 Market Rd",
            "phone": "08022222222",
            "city": "Otukpo",
            "payMethod": "delivery",
        },
    )


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_empty_catalogue_is_seeded_with_the_starter_products(client):
    from app import db

    assert run(db.count_products()) == 28


def test_seeding_never_overwrites_an_admins_edits(client):
    from app import catalogue, db

    p = run(db.get_product("p1"))
    p["name"] = "Premium Local Rice"
    run(db.save_product(p))
    assert run(catalogue.seed_if_empty()) == 0, "a non-empty catalogue must not be re-seeded"
    assert run(db.get_product("p1"))["name"] == "Premium Local Rice"


def test_orders_use_the_database_price_not_the_starter_price(client):
    from app import db

    client.post("/api/auth/signup", json=SIGNUP)
    p = run(db.get_product("p1"))
    p["options"][1]["price"] = 2500
    run(db.save_product(p))
    o = order(client, [{"productId": "p1", "optionIndex": 1, "qty": 2}]).json()["order"]
    assert o["items"][0]["price"] == 2500 and o["subtotal"] == 5000


def test_changing_a_price_later_does_not_rewrite_old_orders(client):
    from app import db

    client.post("/api/auth/signup", json=SIGNUP)
    placed = order(client, [{"productId": "p1", "optionIndex": 1, "qty": 1}]).json()["order"]
    old_price = placed["items"][0]["price"]
    p = run(db.get_product("p1"))
    p["options"][1]["price"] = old_price + 999
    run(db.save_product(p))
    mine = client.get("/api/orders/mine").json()["orders"]
    assert mine[0]["items"][0]["price"] == old_price


def test_an_inactive_product_cannot_be_bought(client):
    from app import db

    client.post("/api/auth/signup", json=SIGNUP)
    p = run(db.get_product("p1"))
    p["active"] = False
    run(db.save_product(p))
    r = order(client, [{"productId": "p1", "optionIndex": 0, "qty": 1}])
    assert r.status_code == 400


def test_the_delivery_fee_comes_from_the_setting(client):
    from app import db

    client.post("/api/auth/signup", json=SIGNUP)
    run(db.set_setting("delivery_fee", 1500))
    o = order(client, [{"productId": "p1", "optionIndex": 0, "qty": 1}]).json()["order"]
    assert o["deliveryFee"] == 1500 and o["total"] == o["subtotal"] + 1500


def test_a_bad_delivery_fee_setting_falls_back_to_the_default(client):
    from app import db

    client.post("/api/auth/signup", json=SIGNUP)
    run(db.set_setting("delivery_fee", "free"))
    o = order(client, [{"productId": "p1", "optionIndex": 0, "qty": 1}]).json()["order"]
    assert o["deliveryFee"] == 800


def test_untracked_stock_never_runs_out(client):
    client.post("/api/auth/signup", json=SIGNUP)
    for _ in range(3):
        assert order(client, [{"productId": "p1", "optionIndex": 0, "qty": 50}]).status_code == 200


def set_stock(n):
    from app import db

    p = run(db.get_product("p1"))
    p["stock"] = n
    run(db.save_product(p))


def test_tracked_stock_goes_down_with_each_order(client):
    from app import db

    client.post("/api/auth/signup", json=SIGNUP)
    set_stock(10)
    assert order(client, [{"productId": "p1", "optionIndex": 0, "qty": 4}]).status_code == 200
    assert run(db.get_product("p1"))["stock"] == 6


def test_ordering_more_than_is_left_is_refused_and_changes_nothing(client):
    from app import db

    client.post("/api/auth/signup", json=SIGNUP)
    set_stock(3)
    r = order(client, [{"productId": "p1", "optionIndex": 0, "qty": 4}])
    assert r.status_code == 409 and "only 3 left" in r.json()["error"]
    assert run(db.get_product("p1"))["stock"] == 3
    assert client.get("/api/orders/mine").json()["orders"] == []


def test_the_last_item_can_only_be_bought_once(client):
    from app import db

    client.post("/api/auth/signup", json=SIGNUP)
    set_stock(1)
    assert order(client, [{"productId": "p1", "optionIndex": 0, "qty": 1}]).status_code == 200
    r = order(client, [{"productId": "p1", "optionIndex": 0, "qty": 1}])
    assert r.status_code == 409 and "out of stock" in r.json()["error"]
    assert run(db.get_product("p1"))["stock"] == 0


def test_a_cart_with_one_unavailable_line_does_not_take_stock_from_the_others(client):
    from app import db

    client.post("/api/auth/signup", json=SIGNUP)
    set_stock(5)
    p2 = run(db.get_product("p2"))
    p2["stock"] = 0
    run(db.save_product(p2))
    r = order(
        client,
        [
            {"productId": "p1", "optionIndex": 0, "qty": 2},
            {"productId": "p2", "optionIndex": 0, "qty": 1},
        ],
    )
    assert r.status_code == 409
    assert run(db.get_product("p1"))["stock"] == 5, "nothing may be taken when the order fails"


def test_reserve_stock_is_all_or_nothing_per_call(client):
    from app import db

    set_stock(2)
    assert run(db.reserve_stock("p1", 3)) is False
    assert run(db.get_product("p1"))["stock"] == 2
    assert run(db.reserve_stock("p1", 2)) is True
    assert run(db.get_product("p1"))["stock"] == 0


def test_two_customers_racing_for_the_last_item_cannot_both_get_it(client):
    """The early stock check passes for both; only the atomic reserve stops the second."""
    import asyncio

    from app import db

    set_stock(1)

    async def race():
        return await asyncio.gather(db.reserve_stock("p1", 1), db.reserve_stock("p1", 1))

    results = run(race())
    assert sorted(results) == [False, True], "exactly one of two simultaneous buyers may win"
    assert run(db.get_product("p1"))["stock"] == 0


def test_a_failed_save_gives_the_reserved_stock_back(client, monkeypatch):
    from app import db

    client.post("/api/auth/signup", json=SIGNUP)
    set_stock(5)

    async def boom(_order):
        raise RuntimeError("database went away")

    monkeypatch.setattr(db, "add_order", boom)
    try:
        order(client, [{"productId": "p1", "optionIndex": 0, "qty": 2}])
    except RuntimeError:
        pass
    assert run(db.get_product("p1"))["stock"] == 5, (
        "stock must be returned when the order is not saved"
    )
