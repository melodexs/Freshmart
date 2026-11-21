"""Product photo uploads: only real, small pictures get in, and they come back out safely."""

from __future__ import annotations

import io
import re
import struct
import zlib

import pytest
from PIL import Image

from app import images

KEY = {"X-Staff-Key": "test-staff-key"}


@pytest.fixture(autouse=True)
def _staff(client, monkeypatch):
    """Run exactly as in production: a staff key is set and open dev mode is off."""
    from app import config

    monkeypatch.setattr(config, "STORE_STAFF_KEY", "test-staff-key")
    monkeypatch.setattr(config, "IS_PRODUCTION", True)


def picture(fmt="JPEG", size=(1600, 1200), colour=(40, 120, 70), **save):
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, fmt, **save)
    return buf.getvalue()


def up(client, data, name="photo.jpg", mime="image/jpeg", headers=KEY):
    return client.post(
        "/api/store/admin/images", files={"file": (name, data, mime)}, headers=headers
    )


def test_a_real_photo_is_accepted_shrunk_and_served(client):
    r = up(client, picture())
    assert r.status_code == 200 and re.fullmatch(r"/media/im[0-9a-f]{16}", r.json()["url"])
    served = client.get(r.json()["url"])
    assert served.status_code == 200 and served.headers["content-type"] == "image/webp"
    img = Image.open(io.BytesIO(served.content))
    assert img.format == "WEBP" and max(img.size) <= images.MAX_SIDE
    assert len(served.content) < len(picture()), "the stored copy is smaller than the original"


@pytest.mark.parametrize(
    ("fmt", "mime", "name"),
    [
        ("JPEG", "image/jpeg", "a.jpg"),
        ("PNG", "image/png", "a.png"),
        ("WEBP", "image/webp", "a.webp"),
    ],
)
def test_jpeg_png_and_webp_are_accepted(client, fmt, mime, name):
    assert up(client, picture(fmt, (300, 300)), name, mime).status_code == 200


def test_served_images_are_locked_down(client):
    h = client.get(up(client, picture(size=(200, 200))).json()["url"]).headers
    assert (
        h["x-content-type-options"] == "nosniff"
        and "default-src 'none'" in h["content-security-policy"]
    )
    assert "immutable" in h["cache-control"]


@pytest.mark.parametrize(
    ("data", "name", "mime"),
    [
        (b"<script>alert(1)</script>", "evil.png", "image/png"),
        (
            b"<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
            "x.svg",
            "image/svg+xml",
        ),
        (b"GIF89a" + b"\x00" * 40, "x.gif", "image/gif"),
        (b"%PDF-1.4 fake", "doc.pdf", "application/pdf"),
        (b"MZ\x90\x00" + b"\x00" * 100, "run.exe.png", "image/png"),
        (b"", "empty.png", "image/png"),
        (b"not an image at all", "a.jpg", "image/jpeg"),
    ],
)
def test_things_that_are_not_photos_are_refused(client, data, name, mime):
    r = up(client, data, name, mime)
    assert r.status_code == 400 and "error" in r.json()


def test_a_script_renamed_to_png_is_refused_even_with_a_png_header(client):
    fake = b"\x89PNG\r\n\x1a\n" + b"<script>alert(1)</script>" * 5
    assert up(client, fake, "x.png", "image/png").status_code == 400


def test_oversized_files_are_refused(client):
    big = picture(size=(300, 300)) + b"\x00" * (images.MAX_BYTES + 10)
    r = up(client, big)
    assert r.status_code == 400 and "5 MB" in r.json()["error"]


def test_a_decompression_bomb_is_refused(client):
    # A tiny PNG that claims to be 30000 x 30000 pixels.
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))

    ihdr = struct.pack(">IIBBBBB", 30000, 30000, 8, 0, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00" * 100))
        + chunk(b"IEND", b"")
    )
    assert up(client, png, "bomb.png", "image/png").status_code == 400


def test_hidden_data_in_a_real_photo_does_not_survive(client):
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), (10, 10, 10)).save(
        buf, "JPEG", comment=b"<script>alert('hidden')</script>"
    )
    raw = buf.getvalue() + b"<script>alert('trailing')</script>"
    served = client.get(up(client, raw).json()["url"]).content
    assert b"<script" not in served and b"hidden" not in served and b"trailing" not in served


def test_uploads_need_staff_and_are_audit_logged(client):
    assert up(client, picture(), headers={}).status_code == 401
    assert up(client, picture(), headers={"X-Staff-Key": "wrong"}).status_code == 401
    ok = up(client, picture(size=(100, 100)))
    audit = client.get("/api/store/admin/audit", headers=KEY).json()
    assert any(
        a["action"] == "image_uploaded" and a["subject"] == ok.json()["url"].split("/")[-1]
        for a in audit["entries"]
    )


@pytest.mark.parametrize(
    "bad",
    [
        "../etc/passwd",
        "im0123",
        "IM0123456789abcdef",
        "im0123456789abcdeg",
        "im0123456789abcdef.png",
        "%2e%2e",
    ],
)
def test_media_only_serves_ids_we_generated(client, bad):
    assert client.get(f"/media/{bad}").status_code == 404


def test_an_unknown_but_well_formed_id_is_a_404(client):
    assert client.get("/media/im0123456789abcdef").status_code == 404


def test_the_uploaded_photo_shows_on_the_product_card_and_page(client):
    url = up(client, picture(size=(400, 400))).json()["url"]
    p = client.get("/api/store/admin/products", headers=KEY).json()["products"][0]
    body = {k: p[k] for k in ("name", "cat", "description", "options")} | {
        "image": url,
        "stock": p.get("stock"),
        "options": [{"label": o["label"], "price": o["price"]} for o in p["options"]],
    }
    assert (
        client.put(f"/api/store/admin/products/{p['id']}", json=body, headers=KEY).status_code
        == 200
    )
    assert f'src="{url}"' in client.get(f"/product/{p['id']}").text
    assert f'src="{url}"' in client.get("/ui/products").text


def test_a_product_cannot_point_at_an_arbitrary_path_or_script(client):
    p = client.get("/api/store/admin/products", headers=KEY).json()["products"][0]
    base = {k: p[k] for k in ("name", "cat", "description")} | {
        "options": [{"label": o["label"], "price": o["price"]} for o in p["options"]]
    }
    for bad in (
        "javascript:alert(1)",
        "/etc/passwd",
        "http://evil.example/x.png",
        "/media/../static/x",
    ):
        assert (
            client.put(
                f"/api/store/admin/products/{p['id']}", json=base | {"image": bad}, headers=KEY
            ).status_code
            == 400
        ), bad
