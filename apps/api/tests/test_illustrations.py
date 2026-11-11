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
