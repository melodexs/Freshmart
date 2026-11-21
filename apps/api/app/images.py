"""Product photo uploads.

An uploaded file is never trusted. It is decoded to prove it really is a JPEG, PNG or WebP picture,
limited in size and pixel count, then re-encoded as a fresh WebP no larger than 900px. Re-encoding
throws away everything else in the file (metadata, embedded scripts, trailing data).
"""

from __future__ import annotations

import io
import secrets

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 40_000_000  # blocks "decompression bomb" files
MAX_SIDE = 900
ALLOWED = {"JPEG", "PNG", "WEBP"}

Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class BadImage(ValueError):
    """The upload was refused; the message is safe to show to the admin."""


def process(raw: bytes) -> bytes:
    if not raw:
        raise BadImage("No file was received.")
    if len(raw) > MAX_BYTES:
        raise BadImage("That photo is too large. Please use one under 5 MB.")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            if probe.format not in ALLOWED:
                raise BadImage("Please upload a JPEG, PNG or WebP photo.")
            probe.verify()
        with Image.open(io.BytesIO(raw)) as img:
            img = ImageOps.exif_transpose(
                img
            )  # honour the phone's rotation, then drop the metadata
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
            img.thumbnail((MAX_SIDE, MAX_SIDE))
            out = io.BytesIO()
            img.save(out, "WEBP", quality=82, method=4)
    except BadImage:
        raise
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise BadImage(
            "That file is not a photo we can read. Please try a JPEG, PNG or WebP image."
        ) from exc
    return out.getvalue()


def new_id() -> str:
    return "im" + secrets.token_hex(8)
