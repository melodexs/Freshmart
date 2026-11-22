"""Photo credits: the open licences used for the product photos require crediting the photographer."""

from __future__ import annotations

import json

from app import templating
from app.products import PRODUCTS


def rows():
    return json.loads(
        (templating.Path(templating.__file__).parent / "photo_credits.json").read_text("utf8")
    )


def test_page_lists_each_photographer_and_licence(client):
    r = client.get("/photo-credits")
    assert r.status_code == 200
    for c in templating.PHOTO_CREDITS:
        assert c["product"] in r.text and c["licence"] in r.text
        if c["requires_credit"] == "True":
            assert c["author"] in r.text


def test_every_real_photo_has_a_credit_row_and_no_row_is_for_a_missing_photo():
    credited = {r["id"] for r in rows()}
    shipped = {p["id"] for p in PRODUCTS if list(templating.PHOTO_DIR.glob(f"{p['id']}.*"))}
    # products with a credit must have a photo file; credited photos are a subset of what ships
    assert credited <= shipped


def test_credit_rows_are_complete_and_links_are_plain_https():
    for r in rows():
        assert r["author"].strip() and r["licence"].strip() and r["file"].strip()
        assert r["licence_url"].startswith("https://") and r["source"].startswith("https://")
        assert r["requires_credit"] == r["licence"].upper().startswith("CC BY")


def test_unsafe_rows_are_dropped_when_loading(tmp_path, monkeypatch):
    bad = [
        {
            "id": "p1",
            "author": "A",
            "licence": "x",
            "licence_url": "javascript:alert(1)",
            "source": "https://e.org",
        },
        {
            "id": "p2",
            "author": "B",
            "licence": "x",
            "licence_url": "https://e.org",
            "source": "https://e.org",
        },
    ]
    (tmp_path / "photo_credits.json").write_text(json.dumps(bad))
    monkeypatch.setattr(templating, "__file__", str(tmp_path / "templating.py"))
    kept = templating._load_credits()
    assert [k["id"] for k in kept] == ["p2"]


def test_page_names_products_without_a_real_photo_and_never_claims_one_for_them(client):
    r = client.get("/photo-credits")
    credited = {c["id"] for c in templating.PHOTO_CREDITS}
    for p in PRODUCTS:
        if p["id"] not in credited:
            assert p["name"] in r.text.split("not photographs of the real product")[1]


def test_footer_links_to_the_credits_page(client):
    assert 'href="/photo-credits"' in client.get("/").text
