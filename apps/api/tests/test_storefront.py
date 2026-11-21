"""The redesigned storefront: homepage sections, product pages, favourites and the grid filters."""

from __future__ import annotations

import asyncio
import re

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


def cards(html):
    return re.findall(r'data-product-id="([^"]+)"', html)


def test_home_has_the_brief_headline_and_both_buttons(client):
    h = client.get("/").text
    assert "Everything fresh. Everything you need." in h
    assert "Shop now" in h and "Explore categories" in h
    assert "Quality products delivered conveniently to your doorstep" in h


def test_home_nav_has_every_link_the_brief_asks_for(client):
    h = client.get("/").text
    for label in ("Shop", "Categories", "Offers", "About", "Contact"):
        assert f">{label}</a>" in h
    assert 'type="search"' in h and 'id="cartCount"' in h


def test_category_cards_come_from_real_stock_and_never_link_to_empty_shelves(client):
    h = client.get("/").text
    block = h[h.index('id="categories"') : h.index('id="offers"')]
    names = re.findall(r"<strong>([^<]+)</strong><small>(\d+) product", block)
    assert len(names) == 7 and all(int(n) >= 1 for _, n in names)
    assert ("Foodstuff", "6") in names


def test_a_new_category_in_the_admin_makes_a_new_card(client):
    from app import db

    run(
        db.save_product(
            {
                "id": "x1",
                "name": "Frozen Fish",
                "cat": "Meat & Fish",
                "options": [{"label": "1kg", "price": 3000}],
                "sort": 99,
            }
        )
    )
    assert "Meat &amp; Fish" in client.get("/").text


def test_empty_shelves_are_not_shown(client):
    h = client.get("/").text
    assert "Best sellers" not in h and "Special offers" not in h, (
        "nothing has sold or been discounted yet"
    )


def test_shelves_appear_once_there_is_real_data(client):
    edit(
        "p3",
        comparePrices=[900]
        + [None]
        * (len(run(__import__("app.db", fromlist=["db"]).get_product("p3"))["options"]) - 1),
    )
    client.post("/api/auth/signup", json=SIGNUP)
    client.post(
        "/api/orders",
        json={
            "items": [{"productId": "p5", "optionIndex": 0, "qty": 2}],
            "address": "12 Market Rd",
            "phone": "08022222222",
            "city": "Otukpo",
            "payMethod": "delivery",
        },
    )
    h = client.get("/").text
    assert "Best sellers" in h and "Special offers" in h and "New arrivals" in h


def test_the_home_page_never_invents_reviews_or_a_dead_newsletter(client):
    h = client.get("/").text.lower()
    assert (
        "testimonial" not in h
        and "newsletter" not in h
        and "5 stars" not in h
        and "verified buyer" not in h
    )


def test_trust_faq_and_contact_sections_exist(client):
    h = client.get("/").text
    for t in (
        "Why shop with OGS",
        "Questions, answered",
        "Get in touch",
        "Quality groceries",
        "Reliable delivery",
    ):
        assert t in h
    assert "We never ask for card details" in h


def test_faq_lists_the_real_delivery_areas(client, monkeypatch):
    from app import db

    run(
        db.set_setting(
            "delivery_areas", [{"name": "Otukpo", "fee": 800}, {"name": "Ugbokpo", "fee": 1500}]
        )
    )
    h = client.get("/").text
    assert "Otukpo, Ugbokpo" in h and "Delivery from ₦800" in h


def test_bank_transfer_is_only_advertised_when_an_account_is_set(client):
    from app import db

    assert "bank transfer" in client.get("/").text.lower()
    run(db.set_setting("bank_details", {}))
    assert "bank transfer" not in client.get("/").text.lower().split("why shop with ogs")[0]


def test_price_filter_in_the_grid(client):
    ids = cards(client.get("/ui/products", params={"min": "1000", "max": "3000"}).text)
    assert ids and len(ids) < 28
    assert cards(client.get("/ui/products", params={"min": "99999999"}).text) == []


def test_junk_price_filters_are_ignored_not_crashing(client):
    for v in ("abc", "-5", "1e9", "9" * 30, "1; drop table"):
        assert client.get("/ui/products", params={"min": v, "max": v}).status_code == 200


def test_discounted_products_show_a_badge_and_the_old_price(client):
    edit("p1", comparePrices=[500, None, None, None])
    h = client.get("/ui/products", params={"q": "local rice"}).text
    assert "20% off" in h and "₦500" in h and "<s " in h


def test_sold_out_product_has_no_add_button_but_is_listed(client):
    edit("p1", stock=0)
    h = client.get("/ui/products", params={"q": "local rice"}).text
    card = h[h.index('data-product-id="p1"') :]
    card = card[: card.index("</div>\n  </div>") if "</div>\n  </div>" in card else len(card)]
    assert "Out of stock" in card and "qtyArea" not in card.split("product-data")[0]


def test_every_card_links_to_its_product_page(client):
    h = client.get("/ui/products").text
    assert h.count('href="/product/') >= 28 * 2


def test_product_page_shows_the_details_the_brief_asks_for(client):
    edit(
        "p1",
        description="Clean, stone-free local rice.",
        comparePrices=[500, None, None, None],
        stock=3,
    )
    h = client.get("/product/p1").text
    for part in (
        "Local Rice",
        "Clean, stone-free local rice.",
        "₦400",
        "₦500",
        "20% off",
        "Only 3 left",
        "qtyArea",
        "You may also like",
        "Foodstuff",
    ):
        assert part in h, part
    assert "<h1>Local Rice</h1>" in h


def test_product_page_for_an_unknown_or_hidden_product_is_a_proper_404(client):
    assert client.get("/product/nope").status_code == 404
    edit("p1", active=False)
    r = client.get("/product/p1")
    assert r.status_code == 404 and "could not find" in r.text


def test_product_page_escapes_admin_typed_text(client):
    edit("p1", description="<script>alert(1)</script>", name="Rice <b>X</b>")
    h = client.get("/product/p1").text
    assert "<script>alert(1)</script>" not in h and "&lt;script&gt;" in h and "<b>X</b>" not in h


def test_favourites_need_sign_in_and_ask_the_page_to_open_the_sign_in_dialog(client):
    r = client.post("/ui/favourites/p1")
    assert r.status_code == 200, "htmx ignores error responses, so the visitor would see nothing"
    assert "need-signin" in r.headers["hx-trigger"] and "Sign in to save" in r.headers["hx-trigger"]
    assert "♡" in r.text and 'aria-pressed="false"' in r.text, "the heart stays off"
    assert cards(client.get("/ui/products", params={"favs": "1"}).text) == []


def test_favourites_toggle_and_persist_per_customer(client):
    client.post("/api/auth/signup", json=SIGNUP)
    on = client.post("/ui/favourites/p1")
    assert on.status_code == 200 and "♥" in on.text and 'aria-pressed="true"' in on.text
    assert cards(client.get("/ui/products", params={"favs": "1"}).text) == ["p1"]
    off = client.post("/ui/favourites/p1")
    assert "♡" in off.text and 'aria-pressed="false"' in off.text
    assert cards(client.get("/ui/products", params={"favs": "1"}).text) == []


def test_empty_favourites_explain_how_to_add_one(client):
    client.post("/api/auth/signup", json=SIGNUP)
    assert "Tap the ♡" in client.get("/ui/products", params={"favs": "1"}).text


def test_one_customers_favourites_are_not_visible_to_another(client):
    client.post("/api/auth/signup", json=SIGNUP)
    client.post("/ui/favourites/p1")
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/signup", json={**SIGNUP, "email": "bola@example.com", "phone": "08033333333"}
    )
    assert cards(client.get("/ui/products", params={"favs": "1"}).text) == []


def test_favouriting_an_unknown_product_is_refused(client):
    client.post("/api/auth/signup", json=SIGNUP)
    assert client.post("/ui/favourites/nope").status_code == 404


def test_section_headings_match_what_is_shown(client):
    assert "Special offers" in client.get("/ui/products", params={"section": "offers"}).text
    assert "Best sellers" in client.get("/ui/products", params={"section": "best"}).text
    assert "Your favourites" in client.get("/ui/products", params={"favs": "1"}).text
    assert "Foodstuff" in client.get("/ui/products", params={"cat": "Foodstuff"}).text


def test_every_page_that_loads_the_shop_script_has_every_element_it_requires(client):
    """The script throws on start-up if an element it needs is missing, and the cart then silently
    stops working. Check each page against the ids the script actually asks for."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "web" / "src"
    needed = set()
    for f in src.glob("*.ts"):
        needed |= set(re.findall(r'\$(?:<[^>]+>)?\("([A-Za-z]+)"\)', f.read_text()))
    # elements the checkout, cart and toasts create or fill are in the shared pages; check each page
    pages = {"/": client.get("/").text, "/product/p1": client.get("/product/p1").text}
    for url, html in pages.items():
        missing = sorted(i for i in needed if f'id="{i}"' not in html)
        assert not missing, f"{url} is missing elements the script needs: {missing}"
