"""Newsletter signup.

* Anyone can subscribe with a valid email. Subscribing twice is harmless and the reply is the
  same either way, so the form cannot be used to find out who already subscribed.
* Each address gets a signed unsubscribe link (no login needed) so leaving is one click.
* Nothing is emailed from here. Sending a newsletter needs an email service that the owner connects;
  until then this only collects addresses, and the admin screen says so.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .. import auth, config, db, ratelimit
from ..emails import clean_email

router = APIRouter()
staff_router = APIRouter(dependencies=[Depends(auth.require_staff)])


def token_for(email: str) -> str:
    """An unguessable per-address token, so only someone holding the link can unsubscribe that address."""
    return hmac.new(
        config.JWT_SECRET.encode(), f"unsub:{email}".encode(), hashlib.sha256
    ).hexdigest()[:32]


def unsubscribe_path(email: str) -> str:
    from urllib.parse import quote

    return f"/newsletter/unsubscribe?email={quote(email)}&t={token_for(email)}"


@router.post("/api/newsletter")
async def subscribe(request: Request):
    ratelimit.limit(request, "newsletter", 6, 600)
    try:
        b = await request.json()
    except Exception:
        b = {}
    email = clean_email(b.get("email") if isinstance(b, dict) else None)
    if not email:
        return JSONResponse({"error": "Please enter a valid email address."}, status_code=400)
    await db.add_subscriber(email, datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    # Same answer for a new and an existing subscriber on purpose.
    return {"ok": True, "message": "Thank you. You are on our list."}


@router.get("/newsletter/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(email: str = "", t: str = ""):
    e = clean_email(email)
    if not e or not hmac.compare_digest(t, token_for(e)):
        return HTMLResponse(
            _page(
                "This unsubscribe link is not valid.", "Please use the link from your latest email."
            ),
            status_code=400,
        )
    await db.remove_subscriber(e)
    return HTMLResponse(
        _page("You have been unsubscribed.", "You will no longer receive our newsletter.")
    )


def _page(title: str, text: str) -> str:
    from html import escape

    return (
        '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{escape(title)}</title><body style="font-family:system-ui;max-width:460px;margin:12vh auto;padding:0 20px;text-align:center">'
        f'<h1 style="font-size:1.4rem">{escape(title)}</h1><p style="color:#555">{escape(text)}</p><p><a href="/">Back to the shop</a></p></body>'
    )


# ---- staff ----
@staff_router.get("/subscribers")
async def staff_subscribers():
    rows = await db.list_subscribers()
    return {"subscribers": rows, "count": len(rows), "emailConfigured": False}


def _cell(v: str) -> str:
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


@staff_router.get("/subscribers.csv")
async def subscribers_csv():
    import csv
    import io

    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Email", "Subscribed (UTC)"])
    rows = await db.list_subscribers()
    for r in rows:
        w.writerow([_cell(r["email"]), r["subscribed"]])
    await db.add_audit("admin", "subscribers_exported", "newsletter", {"count": len(rows)})
    return Response(
        "\ufeff" + out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="ogs-newsletter.csv"',
            "Cache-Control": "no-store",
        },
    )
