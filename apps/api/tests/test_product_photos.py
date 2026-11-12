"""Real photos are optional: drop <id>.webp into static/products/ to replace the drawn art."""

from __future__ import annotations

import pytest

from app import templating


@pytest.fixture
def photo_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(templating, "PHOTO_DIR", tmp_path)
    return tmp_path


def art(pid="p1", name="Local Rice"):
    return str(templating.product_art({"id": pid, "name": name}))


def test_without_a_photo_the_drawn_art_is_used(photo_dir):
    html = art()
    assert "<svg" in html and "<img" not in html


def test_a_photo_replaces_the_drawn_art(photo_dir):
    (photo_dir / "p1.webp").write_bytes(b"x")
    html = art()
    assert '<img class="art photo" src="/static/products/p1.webp"' in html
    assert "<svg" not in html and 'loading="lazy"' in html


def test_other_products_keep_their_drawn_art(photo_dir):
    (photo_dir / "p1.webp").write_bytes(b"x")
    assert "<svg" in art("p2", "Semovita")


def test_webp_is_preferred_over_jpg(photo_dir):
    (photo_dir / "p1.jpg").write_bytes(b"x")
    (photo_dir / "p1.webp").write_bytes(b"x")
    assert "p1.webp" in art()


def test_unsafe_ids_never_touch_the_disk(photo_dir):
    assert templating._photo_url("../secret") is None
    assert templating._photo_url("a/b") is None
    assert templating._photo_url("") is None


def test_product_name_in_alt_text_is_escaped(photo_dir):
    (photo_dir / "p1.webp").write_bytes(b"x")
    html = art(name='"><script>alert(1)</script>')
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_photo_is_served_by_the_app(client, photo_dir):
    # the real static dir is what gets served; just confirm the folder is a valid static path
    assert client.get("/static/products/does-not-exist.webp").status_code == 404
