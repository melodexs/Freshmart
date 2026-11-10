"""Jinja2 setup. Autoescape is ON for every template, so customer-supplied
text (addresses, notes, names) is always HTML-escaped by default."""

from __future__ import annotations

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
