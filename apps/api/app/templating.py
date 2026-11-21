"""Jinja2 setup. Autoescape is ON for every template, so customer-supplied
text (addresses, notes, names) is always HTML-escaped by default."""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
# Jinja2Templates enables autoescape for .html templates. Make that explicit
# so a future change cannot silently turn it off.
templates.env.autoescape = True


def naira(value: int | float) -> str:
    return "₦" + f"{int(value):,}"


def local_time(iso: str) -> str:
    """'2026-11-10T14:30:00.000Z' -> '10 Nov 2026, 14:30' (UTC)."""
    from datetime import datetime

    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y, %H:%M")
    except ValueError:
        return str(iso)


templates.env.filters["naira"] = naira
templates.env.filters["local_time"] = local_time

from . import order_status  # noqa: E402

templates.env.globals["progress_map"] = order_status.PROGRESS
templates.env.globals["timeline"] = order_status.timeline
templates.env.globals["cancellable"] = order_status.CUSTOMER_CAN_CANCEL_FROM

from markupsafe import Markup  # noqa: E402

from . import illustrations  # noqa: E402

PHOTO_DIR = Path(__file__).resolve().parents[2] / "web" / "static" / "products"
PHOTO_EXTENSIONS = (".webp", ".jpg", ".jpeg", ".png")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def _photo_url(product_id: str) -> str | None:
    """URL of a real photo for this product if one was added, else None.

    Drop `<id>.webp` (or .jpg/.png) into apps/web/static/products/ and it replaces
    the drawn illustration automatically. The id is checked before touching the disk.
    """
    if not _SAFE_ID.match(product_id):
        return None
    for ext in PHOTO_EXTENSIONS:
        if (PHOTO_DIR / f"{product_id}{ext}").is_file():
            return f"/static/products/{product_id}{ext}"
    return None


_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _load_frames() -> dict[str, str]:
    """Each photo's own edge colour, so the card frame blends into it with no visible seam."""
    try:
        data = json.loads((Path(__file__).parent / "photo_frames.json").read_text("utf8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str) and _HEX.match(v)}


PHOTO_FRAMES = _load_frames()


def frame_colour(product_id: str) -> str:
    """CSS colour for the frame behind a product's photo ('' when there is none)."""
    return PHOTO_FRAMES.get(str(product_id), "")


def product_art(product: dict) -> Markup:
    uploaded = str(product.get("image") or "")
    url = uploaded if re.fullmatch(r"/media/im[0-9a-f]{16}", uploaded) else None
    url = url or _photo_url(str(product["id"]))
    if url:
        return Markup(  # noqa: S704
            '<img class="art photo" src="{}" alt="{}" loading="lazy" width="140" height="150">'
        ).format(url, product["name"])
    return Markup(illustrations.svg_for(product["id"], product["name"]))  # noqa: S704


templates.env.filters["product_art"] = product_art
templates.env.filters["frame_colour"] = frame_colour
