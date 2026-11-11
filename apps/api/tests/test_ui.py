"""Server-rendered pages and HTMX fragments (Jinja2)."""

import json

XSS = '"><img src=x onerror="alert(1)">'


def form_signup(c, **over):
    data = {
        "name": "Ada Bello",
        "phone": "08011111111",
        "email": "ada@example.com",
        "password": "secret12",
        "password_confirm": "secret12",
    }
    data.update(over)
    return c.post("/ui/signup", data=data)


def trigger(resp):
    return json.loads(resp.headers["HX-Trigger"])


# ---------- pages ----------


def test_home_page_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Fatoke" in r.text and 'id="catalog"' in r.text
    assert "/static/js/main.js" in r.text and "/static/vendor/htmx.min.js" in r.text


def test_static_assets_served(client):
    assert client.get("/static/styles.css").status_code == 200
    assert client.get("/static/vendor/htmx.min.js").status_code == 200
    assert client.get("/static/js/main.js").status_code == 200


def test_unknown_page_is_404_not_a_spa_fallback(client):
    assert client.get("/some/spa/route").status_code == 404


def test_static_path_traversal_blocked(client):
    r = client.get("/static/../app/main.py")
    assert r.status_code in (400, 404)
    assert "FastAPI" not in r.text


# ---------- product grid ----------


def test_product_grid_lists_products(client):
    r = client.get("/ui/products")
    assert r.status_code == 200
    assert r.text.count('class="card"') > 5
    assert "Local Rice" in r.text


def test_product_grid_search_and_category(client):
    rice = client.get("/ui/products", params={"q": "rice"}).text
    assert "Local Rice" in rice and "Semovita" not in rice
    drinks = client.get("/ui/products", params={"cat": "Drinks & Dairy"}).text
    assert "Drinks &amp; Dairy" in drinks and "Local Rice" not in drinks


def test_product_grid_no_match(client):
    assert "No products match" in client.get("/ui/products", params={"q": "zzzz"}).text


def test_product_search_is_escaped(client):
    r = client.get("/ui/products", params={"q": "<script>alert(1)</script>"})
    assert r.status_code == 200 and "<script>alert" not in r.text


# ---------- sign in / up ----------


def test_signup_signs_in_and_triggers_event(client):
    r = form_signup(client)
    assert r.status_code == 200
    assert trigger(r) == {"signed-in": {"email": "ada@example.com", "firstName": "Ada"}}
    cookie = r.headers["set-cookie"].lower()
    assert "fm_token" in cookie and "httponly" in cookie
    header = client.get("/ui/header").text
    assert "Ada" in header and "Sign out" in header


def test_signup_validation_messages(client):
    assert "name and phone" in form_signup(client, name="").text
    assert "at least 6" in form_signup(client, password="abc", password_confirm="abc").text
    assert "match" in form_signup(client, password_confirm="different1").text


def test_signup_duplicate_email(client):
    form_signup(client)
    client.post("/ui/logout")
    assert "already exists" in form_signup(client).text


def test_signup_hostile_name_is_escaped_everywhere(client):
    r = form_signup(client, name=XSS)
    assert "<img" not in r.text
    header = client.get("/ui/header").text
    assert "<img" not in header and "&lt;img" in header


def test_login_flow_and_wrong_password(client):
    form_signup(client)
    client.post("/ui/logout")
    bad = client.post("/ui/login", data={"email": "ada@example.com", "password": "nope"})
    assert "incorrect" in bad.text and "HX-Trigger" not in bad.headers
    ok = client.post("/ui/login", data={"email": "ADA@example.com", "password": "secret12"})
    assert trigger(ok)["signed-in"]["email"] == "ada@example.com"


def test_logout_clears_session(client):
    form_signup(client)
    r = client.post("/ui/logout")
    assert "signed-out" in trigger(r)
    assert client.get("/ui/orders").status_code == 401


def test_signin_form_remembers_known_email_only(client):
    form_signup(client)
    client.post("/ui/logout")
    known = client.get("/ui/signin", params={"last": "ada@example.com"}).text
    assert "Welcome back, Ada" in known
    unknown = client.get("/ui/signin", params={"last": "nobody@example.com"}).text
    assert "Welcome back" not in unknown


def test_login_is_rate_limited(client):
    codes = [
        client.post("/ui/login", data={"email": "x@y.com", "password": f"p{i}"}).status_code
        for i in range(14)
    ]
    assert 429 in codes


# ---------- orders ----------


def place_order(c, address="1 Main St"):
    return c.post(
        "/api/orders",
        json={
            "items": [{"productId": "p1", "optionIndex": 0, "qty": 2, "note": XSS}],
            "address": address,
            "phone": "08022222222",
            "city": "Otukpo, Benue State",
            "payMethod": "delivery",
        },
    )


def test_orders_fragment_requires_sign_in(client):
    r = client.get("/ui/orders")
    assert r.status_code == 401 and "Sign in" in r.text


def test_orders_fragment_lists_orders_escaped(client):
    form_signup(client)
    assert "No orders yet" in client.get("/ui/orders").text
    assert place_order(client).status_code == 200
    html = client.get("/ui/orders").text
    assert "Local Rice" in html and "₦" in html
    assert "<img" not in html and "&lt;img" in html


# ---------- staff inbox (cookie scoped to /api/store) ----------


def test_store_fragment_login_flow(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "STORE_STAFF_KEY", "s3cret")
    assert "Staff key" in client.get("/api/store/ui").text
    bad = client.post("/api/store/ui/login", data={"key": "wrong"})
    assert "not correct" in bad.text and "fm_staff" not in bad.headers.get("set-cookie", "")
    ok = client.post("/api/store/ui/login", data={"key": "s3cret"})
    sc = ok.headers["set-cookie"].lower()
    assert "fm_staff" in sc and "httponly" in sc and "samesite=strict" in sc
    assert "path=/api/store" in sc
    assert "Sign out of staff view" in client.get("/api/store/ui").text
    out = client.post("/api/store/ui/logout")
    assert "Staff key" in out.text


def test_store_feed_shows_orders_escaped_to_staff_only(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "STORE_STAFF_KEY", "s3cret")
    form_signup(client)
    place_order(client, address=XSS)
    assert "Deliver to" not in client.get("/api/store/ui").text  # customer is not staff
    client.post("/api/store/ui/login", data={"key": "s3cret"})
    html = client.get("/api/store/ui").text
    assert "Deliver to" in html
    assert "<img" not in html and "&lt;img" in html


def test_staff_login_fragment_is_rate_limited(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "STORE_STAFF_KEY", "s3cret")
    codes = [
        client.post("/api/store/ui/login", data={"key": f"g{i}"}).status_code for i in range(8)
    ]
    assert 429 in codes


def test_templates_autoescape_enabled():
    from app.templating import templates

    assert "<b>" not in templates.env.from_string("{{ x }}").render(x="<b>")


def test_page_has_seo_and_share_metadata(client):
    html = client.get("/").text
    assert '<meta name="description"' in html
    assert 'property="og:title"' in html and 'name="twitter:card"' in html
    assert '<meta name="theme-color"' in html


def test_robots_blocks_api_and_points_to_sitemap(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert "Disallow: /api/" in r.text and "Sitemap:" in r.text


def test_favicon_is_linked_and_served(client):
    assert 'rel="icon"' in client.get("/").text
    r = client.get("/static/favicon.svg")
    assert r.status_code == 200 and "<svg" in r.text


def test_sitemap_lists_the_home_page(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200 and "xml" in r.headers["content-type"]
    assert "<loc>" in r.text and "urlset" in r.text


def test_browser_404_is_a_friendly_page_but_api_stays_json(client):
    page = client.get("/no-such-page", headers={"accept": "text/html"})
    assert page.status_code == 404 and "Back to the shop" in page.text
    api = client.get("/api/nope", headers={"accept": "text/html"})
    assert api.status_code == 404 and api.json() == {"error": "Not found."}


def test_page_has_skip_link_to_the_catalog(client):
    html = client.get("/").text
    assert 'class="skip-link" href="#catalog"' in html and 'id="catalog"' in html


def test_stylesheet_respects_reduced_motion(client):
    css = client.get("/static/styles.css").text
    assert "prefers-reduced-motion: reduce" in css


def test_grid_shows_a_result_count(client):
    all_html = client.get("/ui/products").text
    assert 'id="resultCount">28 items<' in all_html
    one = client.get("/ui/products", params={"q": "yam"}).text
    assert 'id="resultCount">1 item<' in one


def _names(html):
    import re

    return re.findall(r"<h3>([^<]+)</h3>", html)


def test_grid_can_sort_by_name_and_price(client):
    by_name = _names(client.get("/ui/products", params={"sort": "name"}).text)
    assert by_name == sorted(by_name, key=str.lower)
    from app.products import PRODUCTS

    def cheapest(name):
        p = next(p for p in PRODUCTS if p["name"] == name)
        return min(o["price"] for o in p["options"])

    asc = [
        cheapest(n) for n in _names(client.get("/ui/products", params={"sort": "price-asc"}).text)
    ]
    desc = [
        cheapest(n) for n in _names(client.get("/ui/products", params={"sort": "price-desc"}).text)
    ]
    assert asc == sorted(asc) and desc == sorted(desc, reverse=True)


def test_unknown_sort_value_is_ignored(client):
    assert client.get("/ui/products", params={"sort": "'; drop table"}).status_code == 200


def test_page_offers_a_sort_dropdown_sharing_one_filters_include(client):
    html = client.get("/").text
    assert 'id="sortSelect"' in html and 'value="price-asc"' in html
    assert (
        'id="filters"' in html and 'hx-include="#filters"' in html
    )  # one shared include for all controls


def test_sort_applies_within_a_category(client):
    html = client.get("/ui/products", params={"cat": "Snacks", "sort": "name"}).text
    import re

    names = re.findall(r"<h3>([^<]+)</h3>", html)
    assert len(names) == 4 and names == sorted(names, key=str.lower)


def test_page_has_a_back_to_top_button(client):
    assert 'id="backToTop"' in client.get("/").text


def test_home_explains_delivery_fee_payment_and_tracking(client):
    html = client.get("/").text
    assert "How ordering works" in html and "₦800 delivery fee" in html
    assert "Pay on delivery" in html and "Track every order" in html


def test_confirmation_offers_to_copy_the_order_reference(client):
    assert 'id="copyRef"' in client.get("/").text


def test_cart_drawer_has_a_clear_button(client):
    assert 'id="clearCartBtn"' in client.get("/").text


def test_every_titled_modal_is_an_accessible_dialog(client):
    import re

    html = client.get("/").text
    dialogs = re.findall(r'role="dialog" aria-modal="true" aria-labelledby="(\w+)"', html)
    assert len(dialogs) == 7
    for ident in dialogs:
        assert f'id="{ident}"' in html  # each dialog points at a real heading
