"""Card frames take each photo's own edge colour so photos blend in with no visible seam."""

from __future__ import annotations

import re
import statistics

import pytest

from app import templating
from app.products import PRODUCTS


def edge_colour(path):
    from PIL import Image

    im = Image.open(path).convert("RGB")
    w, h = im.size
    px = []
    for x in range(0, w, 4):
        px += [
            im.getpixel((x, 0)),
            im.getpixel((x, 1)),
            im.getpixel((x, h - 1)),
            im.getpixel((x, h - 2)),
        ]
    for y in range(0, h, 4):
        px += [
            im.getpixel((0, y)),
            im.getpixel((1, y)),
            im.getpixel((w - 1, y)),
            im.getpixel((w - 2, y)),
        ]
    return tuple(round(statistics.median(c[i] for c in px)) for i in range(3))


def test_every_product_has_a_frame_colour():
    missing = [p["id"] for p in PRODUCTS if not templating.frame_colour(p["id"])]
    assert missing == []


def test_frame_colours_are_plain_hex_so_they_are_safe_in_a_style_attribute():
    assert all(re.fullmatch(r"#[0-9a-f]{6}", v) for v in templating.PHOTO_FRAMES.values())


def test_saved_frame_colours_still_match_the_photos():
    pytest.importorskip("PIL", reason="Pillow is only needed for this check, not by the app")
    """If a photo is replaced, its saved colour must be refreshed too (this test says which one)."""
    stale = []
    for p in PRODUCTS:
        got = edge_colour(next(templating.PHOTO_DIR.glob(f"{p['id']}.*")))
        want = tuple(int(templating.frame_colour(p["id"])[i : i + 2], 16) for i in (1, 3, 5))
        if max(abs(a - b) for a, b in zip(got, want, strict=True)) > 6:
            stale.append(p["id"])
    assert stale == [], (
        f"photo changed but apps/api/app/photo_frames.json was not refreshed: {stale}"
    )


def test_a_bad_frame_value_is_ignored_not_trusted(monkeypatch):
    monkeypatch.setattr(templating, "PHOTO_FRAMES", {"p1": "red; background:url(x)"})
    # the loader filters on load; frame_colour only returns what the loader accepted
    assert not templating._HEX.match("red; background:url(x)")
    assert templating._HEX.match("#a1b2c3")
