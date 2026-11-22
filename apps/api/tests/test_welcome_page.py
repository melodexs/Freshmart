"""The premium welcome page: real data only, no invented claims, and nothing the CSP would block."""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "web" / "static"


def _home(client) -> str:
    return client.get("/").text


def test_counters_show_the_real_catalogue_numbers(client):
    h = _home(client)
    data = client.get("/api/products/").json()
    products = data["products"]
    counts = re.findall(r'<strong data-count="(\d+)">\1</strong><span>([A-Za-z ]+)</span>', h)
    got = {label: int(n) for n, label in counts}
    assert got["Products"] == len(products)
    assert got["Categories"] == len({p["cat"] for p in products})


def test_delivery_from_figure_is_the_cheapest_real_area_fee(client):
    h = _home(client)
    areas = client.get("/api/products/").json()["areas"]
    cheapest = min(a["fee"] for a in areas)
    m = re.search(r"<strong>(₦[\d,]+)</strong><span>Delivery from</span>", h)
    assert m, "the 'Delivery from' fact is missing"
    assert int(m.group(1).replace("₦", "").replace(",", "")) == cheapest


def test_hero_uses_only_real_product_photos_that_exist(client):
    h = _home(client)
    stage = re.search(r'<div class="hero-stage".*?</div>\s*</div>', h, re.S).group(0)
    srcs = re.findall(r'<img src="([^"]+)"', stage)
    assert 1 <= len(srcs) <= 4
    for src in srcs:
        assert src.startswith(("/static/products/", "/media/")), src
        if src.startswith("/static/"):
            assert (STATIC / src.removeprefix("/static/")).is_file(), src


def test_no_invented_social_proof_on_the_welcome_page(client):
    text = re.sub(r"<[^>]+>", " ", _home(client)).lower()
    for phrase in (
        "5-star",
        "five star",
        "trusted by",
        "customers served",
        "as seen on",
        "award",
        "★",
    ):
        assert phrase not in text, phrase


def test_no_inline_script_and_no_third_party_assets(client):
    h = _home(client)
    for tag in re.findall(r"<script\b[^>]*>", h):
        assert "src=" in tag or 'type="application/json"' in tag, (
            tag
        )  # inline code is blocked by the CSP
    assert "fonts.googleapis.com" not in h and "fonts.gstatic.com" not in h
    for url in re.findall(r'(?:href|src)="(https?://[^"]+)"', h):
        assert "wa.me" in url or "api.whatsapp" in url, f"unexpected third-party asset: {url}"


def test_fonts_are_self_hosted_and_served(client):
    css = client.get("/static/premium.css")
    assert css.status_code == 200
    urls = re.findall(r"url\((/static/fonts/[^)]+\.woff2)\)", css.text)
    assert len(urls) >= 5
    for u in urls:
        r = client.get(u)
        assert r.status_code == 200 and len(r.content) < 40_000, u  # subset fonts stay small


def test_motion_respects_reduced_motion(client):
    css = client.get("/static/premium.css").text
    assert "prefers-reduced-motion: reduce" in css
    js = client.get("/static/js/premium.js").text
    assert "prefers-reduced-motion" in js


def test_content_is_not_hidden_unless_javascript_enabled_it(client):
    css = re.sub(
        r"@keyframes\s+[\w-]+\s*\{(?:[^{}]|\{[^{}]*\})*\}",
        "",
        client.get("/static/premium.css").text,
    )
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sel, body = m.group(1).strip(), m.group(2)
        if re.search(r"(?<![-\w])opacity:\s*0\s*(;|$)", body):
            if sel == ".rev-stars input":
                continue  # star picker radios: the visible star label is the control and stays focusable
            # allowed: elements revealed by the js gate, or ones animated in by CSS itself
            assert ".js " in sel or "float-card" in sel, f"hidden without the js gate: {sel}"


def test_filters_stay_reachable_inside_the_toggle(client):
    h = _home(client)
    block = re.search(r'<details class="more-filters">.*?</details>', h, re.S).group(0)
    for needle in ('id="sortSelect"', 'id="minPrice"', 'id="maxPrice"', 'id="favFilter"'):
        assert needle in block, needle
    assert 'id="searchInput"' not in block  # search itself stays always visible


def test_brief_copy_is_kept(client):
    h = _home(client)
    assert "Quality products delivered conveniently to your doorstep" in h
    assert "demo" not in re.sub(r"<[^>]+>", " ", h).lower()


def test_filters_never_depend_on_a_closed_details_element_on_wide_screens(client):
    """A closed <details> hides its content everywhere. Wide screens must force it open (the
    sort, price and favourites controls vanished from desktop in the first draft)."""
    js = client.get("/static/js/premium.js").text
    assert ".more-filters" in js and 'setAttribute("open"' in js
    assert "min-width: 621px" in js  # the same breakpoint where the phone toggle disappears
    css = client.get("/static/premium.css").text
    assert "@media (max-width:620px)" in css and ".more-filters > summary{" in css
