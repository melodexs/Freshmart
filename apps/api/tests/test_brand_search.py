"""Optional subcategory and brand: real values only, searchable, filterable, never invented."""

from __future__ import annotations

import pytest

STAFF = {"X-Staff-Key": "staff-secret-key"}


@pytest.fixture
def shop(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "STORE_STAFF_KEY", "staff-secret-key")
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    return client


def edit(c, pid, **fields):
    cur = next(
        p
        for p in c.get("/api/store/admin/products", headers=STAFF).json()["products"]
        if p["id"] == pid
    )
    body = {
        **cur,
        **fields,
        "options": [{"label": o["label"], "price": o["price"]} for o in cur["options"]],
    }
    r = c.put(f"/api/store/admin/products/{pid}", json=body, headers=STAFF)
    assert r.status_code == 200, r.text
    return r.json()


def grid(c, **params):
    return c.get("/ui/products", params=params).text


def test_no_brand_or_subcategory_is_invented_for_existing_products(shop):
    products = shop.get("/api/store/admin/products", headers=STAFF).json()["products"]
    assert products and all(p.get("sub", "") == "" and p.get("brand", "") == "" for p in products)
    h = grid(shop)
    assert 'class="facets"' not in h  # no chips until the owner fills something in


def test_admin_can_set_and_clear_them(shop):
    edit(shop, "p1", sub="Rice and grains", brand="Mama Gold")
    p = next(
        p
        for p in shop.get("/api/store/admin/products", headers=STAFF).json()["products"]
        if p["id"] == "p1"
    )
    assert p["sub"] == "Rice and grains" and p["brand"] == "Mama Gold"
    edit(shop, "p1", sub="", brand="")
    p = next(
        p
        for p in shop.get("/api/store/admin/products", headers=STAFF).json()["products"]
        if p["id"] == "p1"
    )
    assert p["sub"] == "" and p["brand"] == ""


def test_values_are_trimmed_limited_and_stored_as_text(shop):
    edit(shop, "p1", sub="  Rice    and   grains ", brand="x" * 200)
    p = next(
        p
        for p in shop.get("/api/store/admin/products", headers=STAFF).json()["products"]
        if p["id"] == "p1"
    )
    assert p["sub"] == "Rice and grains" and len(p["brand"]) == 40


def test_search_finds_a_product_by_its_brand(shop):
    edit(shop, "p1", brand="Mama Gold")
    assert "Local Rice" in grid(shop, q="mama gold")
    assert "Local Rice" in grid(shop, q="MAMA")
    assert "Local Rice" not in grid(shop, q="peak milk")


def test_search_finds_a_product_by_subcategory(shop):
    edit(shop, "p1", sub="Rice and grains")
    assert "Local Rice" in grid(shop, q="grains")


def test_every_word_must_match_so_searches_narrow_down(shop):
    edit(shop, "p1", brand="Mama Gold")
    edit(shop, "p2", brand="Other Brand")
    both = grid(shop, q="mama")
    assert "Local Rice" in both and "Semovita" not in both
    assert "Local Rice" in grid(shop, q="mama rice") and "Local Rice" not in grid(
        shop, q="mama semovita"
    )
    assert "Local Rice" in grid(shop, q="foodstuff mama")  # category word + brand word together


def test_brand_filter_chips_appear_and_filter(shop):
    edit(shop, "p1", brand="Mama Gold")
    edit(shop, "p2", brand="Other Brand")
    h = grid(shop)
    assert (
        'aria-label="Brand"' in h and "Mama Gold" in h and "Other Brand" in h and "All brands" in h
    )
    only = grid(shop, brand="Mama Gold")
    assert "Local Rice" in only and "Semovita" not in only


def test_subcategory_chips_belong_to_their_category_only(shop):
    edit(shop, "p1", sub="Rice and grains")
    foods = grid(shop, cat="Foodstuff")
    assert "Rice and grains" in foods and 'aria-label="Type"' in foods
    other_cat = next(
        p["cat"]
        for p in shop.get("/api/store/admin/products", headers=STAFF).json()["products"]
        if p["cat"] != "Foodstuff"
    )
    assert "Rice and grains" not in grid(shop, cat=other_cat)
    assert "Local Rice" in grid(shop, cat="Foodstuff", sub="Rice and grains")
    assert "Semovita" not in grid(shop, cat="Foodstuff", sub="Rice and grains")


def test_made_up_filter_values_are_ignored_not_an_empty_page(shop):
    edit(shop, "p1", brand="Mama Gold")
    h = grid(shop, brand="Not A Brand", sub="Not A Type")
    assert "Local Rice" in h and "We could not find a match" not in h


def test_filter_values_are_escaped_everywhere(shop):
    edit(shop, "p1", brand="<img src=x onerror=alert(1)>", sub='"><script>alert(1)</script>')
    h = grid(shop) + grid(shop, cat="Foodstuff") + shop.get("/").text
    assert "<script>alert(1)" not in h and "<img src=x onerror" not in h


def test_a_brand_only_belongs_to_its_own_product_card(shop):
    edit(shop, "p1", brand="Mama Gold")
    h = grid(shop, q="semovita")
    cards = h.split('class="grid" id="productGrid"')[1]  # the product cards, not the filter chips
    assert "Semovita" in cards and "Local Rice" not in cards and "Mama Gold" not in cards


def test_only_staff_can_set_them(shop):
    r = shop.put(
        "/api/store/admin/products/p1",
        json={"name": "x", "cat": "x", "options": [{"label": "a", "price": 1}], "brand": "Hacked"},
    )
    assert r.status_code == 401
    assert "Hacked" not in grid(shop)


def test_hidden_products_are_not_searchable_by_brand(shop):
    edit(shop, "p1", brand="Mama Gold", active=False)
    assert "Local Rice" not in grid(shop, q="mama gold")
