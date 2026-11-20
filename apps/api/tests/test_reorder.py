"""Reorder: new orders remember what was bought, and the button is safe and only shown when possible."""

from __future__ import annotations

import json
import re
from html import unescape

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


def signup(c):
    return c.post("/api/auth/signup", json=SIGNUP)


def place(client, items=None):
    body = {**ORDER, **({"items": items} if items else {})}
    r = client.post("/api/orders", json=body)
    assert r.status_code == 200, r.text
    return r.json()["order"]


def test_new_orders_keep_the_product_id_and_size_on_every_line(client):
    signup(client)
    order = place(
        client,
        [
            {"productId": "p1", "optionIndex": 1, "qty": 2},
            {"productId": "p12", "optionIndex": 2, "qty": 1},
        ],
    )
    assert [(i["productId"], i["optionIndex"], i["qty"]) for i in order["items"]] == [
        ("p1", 1, 2),
        ("p12", 2, 1),
    ]


def test_the_saved_price_still_comes_from_the_server_not_the_browser(client):
    signup(client)
    order = place(client, [{"productId": "p1", "optionIndex": 1, "qty": 1, "price": 1}])
    assert order["items"][0]["price"] > 1


def test_orders_page_shows_a_reorder_button_with_the_right_data(client):
    signup(client)
    place(
        client,
        [
            {"productId": "p1", "optionIndex": 1, "qty": 2},
            {"productId": "p12", "optionIndex": 2, "qty": 3},
        ],
    )
    html = client.get("/ui/orders").text
    assert 'class="status-btn reorder-btn"' in html
    ids = json.loads(unescape(re.search(r"data-reorder='([^']*)'", html).group(1)))
    options = json.loads(unescape(re.search(r"data-reorder-options='([^']*)'", html).group(1)))
    qtys = json.loads(unescape(re.search(r"data-reorder-qty='([^']*)'", html).group(1)))
    assert (ids, options, qtys) == (["p1", "p12"], [1, 2], [2, 3])


def test_old_orders_without_ids_get_no_reorder_button():
    """An order saved before this feature has no productId on its lines, so no button."""
    from app.templating import templates

    old_order = {
        "id": "FMOLD0001",
        "date": "2026-01-01T10:00:00Z",
        "total": 5800,
        "status": "Placed",
        "items": [{"name": "Local Rice (5 cups)", "qty": 1, "price": 5000, "note": ""}],
    }
    html = templates.get_template("partials/orders.html").render(
        orders=[old_order], cancellable=[], notice=None
    )
    assert "FMOLD0001" in html and "reorder-btn" not in html
