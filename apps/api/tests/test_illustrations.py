from __future__ import annotations

import xml.dom.minidom

from app import illustrations
from app.products import PRODUCTS


def test_every_product_has_artwork():
    assert [p["id"] for p in PRODUCTS if p["id"] not in illustrations.ART] == []


def test_every_illustration_is_well_formed_svg():
    for p in PRODUCTS:
        doc = xml.dom.minidom.parseString(illustrations.svg_for(p["id"], p["name"]))
        assert doc.documentElement.tagName == "svg"


def test_hostile_product_name_cannot_inject_markup():
    svg = illustrations.svg_for("p1", '"><img src=x onerror="alert(1)">')
    assert "<img" not in svg
    xml.dom.minidom.parseString(svg)  # still valid XML


def test_unknown_product_falls_back_instead_of_crashing():
    xml.dom.minidom.parseString(illustrations.svg_for("does-not-exist", "Mystery"))


def test_grid_uses_artwork_not_emoji(client):
    html = client.get("/ui/products").text
    assert html.count('class="art"') == len(PRODUCTS)
    assert 'class="thumb">🍚' not in html


def test_every_product_has_unique_gradient_ids():
    import re

    ids = []
    for pid in illustrations.ART:
        ids += re.findall(r'id="([^"]+)"', illustrations.svg_for(pid, "x"))
    assert len(ids) == len(set(ids)) == len(illustrations.ART) * 2


def test_gradient_never_replaces_a_text_label_colour():
    import re

    for pid in illustrations.ART:
        svg = illustrations.svg_for(pid, "x")
        for fill in re.findall(r"<text[^>]*fill=\"([^\"]+)\"", svg):
            assert not fill.startswith("url("), pid


def test_body_uses_a_gradient_and_a_ground_shadow():
    svg = illustrations.svg_for("p1", "Rice")
    assert "linearGradient" in svg and 'fill="url(#gp1-body)"' in svg
    assert 'opacity=".16"' in svg
