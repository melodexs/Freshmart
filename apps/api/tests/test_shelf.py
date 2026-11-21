"""Which products show and in what order: filters, sort, sections, discounts and sold-out handling."""

from __future__ import annotations

import asyncio

SIGNUP = {
    "name": "Ada",
    "phone": "08011111111",
    "email": "ada@example.com",
    "password": "secret123",
    "passwordConfirm": "secret123",
}


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def edit(pid, **changes):
    from app import db

    p = run(db.get_product(pid))
    p.update(changes)
    run(db.save_product(p))


def ids(items):
    return [p["id"] for p in items]


def buy(client, pid, qty=1):
    client.post("/api/auth/signup", json=SIGNUP)
    return client.post(
        "/api/orders",
        json={
            "items": [{"productId": pid, "optionIndex": 0, "qty": qty}],
            "address": "12 Market Rd",
            "phone": "08022222222",
            "city": "Otukpo",
            "payMethod": "delivery",
        },
    )


def test_everything_shows_by_default(client):
    from app import catalogue

    assert len(run(catalogue.shelf())) == 28


def test_search_matches_name_and_category_ignoring_case(client):
    from app import catalogue

    assert "p1" in ids(run(catalogue.shelf(q="RICE")))
    foodstuff = run(catalogue.shelf(q="foodstuff"))
    assert foodstuff and all(p["cat"] == "Foodstuff" for p in foodstuff)
    assert run(catalogue.shelf(q="zzzz-nothing")) == []


def test_category_filter(client):
    from app import catalogue

    got = run(catalogue.shelf(cat="Foodstuff"))
    assert got and {p["cat"] for p in got} == {"Foodstuff"}


def test_price_range_uses_the_from_price(client):
    from app import catalogue

    got = run(catalogue.shelf(min_price=1000, max_price=3000))
    assert got and all(1000 <= catalogue.from_price(p) <= 3000 for p in got)
    assert run(catalogue.shelf(min_price=10**8)) == []


def test_price_sorting_both_ways(client):
    from app import catalogue

    asc = [catalogue.from_price(p) for p in run(catalogue.shelf(sort="price-asc"))]
    desc = [catalogue.from_price(p) for p in run(catalogue.shelf(sort="price-desc"))]
    assert asc == sorted(asc) and desc == sorted(desc, reverse=True)


def test_name_sorting(client):
    from app import catalogue

    names = [p["name"].lower() for p in run(catalogue.shelf(sort="name"))]
    assert names == sorted(names)


def test_discount_percent_needs_a_higher_old_price(client):
    from app import catalogue

    edit("p1", comparePrices=[500, None, None, None])  # option 0 costs 400
    p = run(__import__("app.db", fromlist=["db"]).get_product("p1"))
    assert catalogue.discount_percent(p, 0) == 20
    assert catalogue.discount_percent(p, 1) is None
    edit(
        "p1", comparePrices=[300, None, None, None]
    )  # old price LOWER than current: not a discount
    p = run(__import__("app.db", fromlist=["db"]).get_product("p1"))
    assert catalogue.discount_percent(p, 0) is None


def test_offers_section_lists_only_discounted_products(client):
    from app import catalogue

    assert run(catalogue.shelf(section="offers")) == []
    edit(
        "p3",
        comparePrices=[None]
        * len(run(__import__("app.db", fromlist=["db"]).get_product("p3"))["options"]),
    )
    p3 = run(__import__("app.db", fromlist=["db"]).get_product("p3"))
    p3["comparePrices"][0] = p3["options"][0]["price"] + 100
    edit("p3", comparePrices=p3["comparePrices"])
    assert ids(run(catalogue.shelf(section="offers"))) == ["p3"]


def test_best_sellers_come_from_real_orders_not_a_guess(client):
    from app import catalogue

    assert run(catalogue.shelf(section="best")) == [], "nothing has sold yet"
    buy(client, "p5", 3)
    buy(client, "p2", 1)
    assert ids(run(catalogue.shelf(section="best"))) == ["p5", "p2"]


def test_cancelled_orders_do_not_make_a_best_seller(client):
    from app import catalogue, db

    o = buy(client, "p5", 5).json()["order"]
    run(db.update_order_status(o["id"], "Cancelled"))
    assert run(catalogue.shelf(section="best")) == []


def test_popular_sort_puts_the_most_ordered_first(client):
    from app import catalogue

    buy(client, "p9", 4)
    assert run(catalogue.shelf(sort="popular"))[0]["id"] == "p9"


def test_new_arrivals_are_the_most_recently_added(client):
    from app import catalogue, db

    run(
        db.save_product(
            {
                "id": "fresh",
                "name": "Fresh One",
                "cat": "Foodstuff",
                "options": [{"label": "1", "price": 100}],
                "sort": 9999,
            }
        )
    )
    assert run(catalogue.shelf(section="new"))[0]["id"] == "fresh"


def test_featured_section(client):
    from app import catalogue

    edit("p4", featured=True)
    assert ids(run(catalogue.shelf(section="featured"))) == ["p4"]


def test_hidden_products_never_show(client):
    from app import catalogue

    edit("p1", active=False)
    assert "p1" not in ids(run(catalogue.shelf())) and "p1" not in ids(
        run(catalogue.shelf(q="rice"))
    )


def test_sold_out_products_sort_last_but_still_show(client):
    from app import catalogue

    edit("p1", stock=0)
    got = ids(run(catalogue.shelf()))
    assert got[-1] == "p1" and len(got) == 28


def test_related_products_share_the_category_and_skip_the_product_itself(client):
    from app import catalogue, db

    p = run(db.get_product("p1"))
    rel = run(catalogue.related(p))
    assert rel and all(r["cat"] == p["cat"] and r["id"] != "p1" for r in rel) and len(rel) <= 4


def test_only_ids_limits_the_shelf_for_favourites(client):
    from app import catalogue

    assert ids(run(catalogue.shelf(only_ids=["p2", "p7"]))) == ["p2", "p7"]
    assert run(catalogue.shelf(only_ids=[])) == []
