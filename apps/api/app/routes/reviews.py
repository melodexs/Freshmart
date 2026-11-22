"""Verified-purchase product reviews.

Honesty rules, enforced here on the server and not left to the page:
  * Only a signed-in customer with a DELIVERED order that contains the product can review it.
  * One review per customer per product. Writing again edits it.
  * Staff can hide a review (it is kept and audit-logged) but can never rewrite what a customer wrote.
  * Averages and counts are computed from real, visible reviews only. No reviews means no stars.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import auth, catalogue, db, order_status, ratelimit

router = APIRouter()
staff_router = APIRouter(dependencies=[Depends(auth.require_staff)])

MAX_BODY = 600


def err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def bought_and_received(orders: list[dict], product_id: str) -> bool:
    """True only if one of these orders was delivered and contains this product."""
    for o in orders:
        if o["status"] != order_status.DELIVERED:
            continue
        if any(line.get("productId") == product_id for line in o["items"]):
            return True
    return False


def summarise(reviews: list[dict]) -> dict:
    """Average and breakdown from the visible reviews. Empty in, nothing out (never a fake 0 stars)."""
    n = len(reviews)
    if not n:
        return {"count": 0, "average": None, "stars": {str(i): 0 for i in range(1, 6)}}
    stars = {str(i): 0 for i in range(1, 6)}
    for r in reviews:
        stars[str(r["rating"])] += 1
    return {
        "count": n,
        "average": round(sum(r["rating"] for r in reviews) / n, 1),
        "stars": stars,
    }


def public(r: dict) -> dict:
    """What anyone may see. The customer's email is never included, only their first name."""
    first = (r["name"].split() or ["Customer"])[0]
    return {
        "name": first,
        "rating": r["rating"],
        "body": r["body"],
        "date": r["updated"][:10],
        "productId": r["productId"],
    }


async def live_product(product_id: str) -> dict | None:
    """A product customers can see. Hidden (inactive) products have no public reviews page."""
    p = await db.get_product(product_id)
    return p if p and p.get("active", True) else None


def clean_body(v) -> str:
    return " ".join(v.split())[:MAX_BODY] if isinstance(v, str) else ""


@router.get("/api/products/{product_id}/reviews")
async def product_reviews(product_id: str, request: Request):
    product = await live_product(product_id)
    if not product:
        return err(404, "Product not found.")
    rows = await db.list_reviews(product_id)
    out = {
        "summary": summarise(rows),
        "reviews": [public(r) for r in rows[:50]],
        "mine": None,
        "canReview": False,
    }
    user = auth.current_user(request)
    if user:
        mine = await db.get_review(user["email"], product_id)
        if mine:
            out["mine"] = {"rating": mine["rating"], "body": mine["body"], "hidden": mine["hidden"]}
        out["canReview"] = bought_and_received(
            await db.get_orders_for_user(user["email"]), product_id
        )
    return out


@router.post("/api/products/{product_id}/reviews")
async def write_review(product_id: str, request: Request, user: dict = Depends(auth.require_auth)):
    ratelimit.limit(request, "review", 10, 600)
    product = await live_product(product_id)
    if not product:
        return err(404, "Product not found.")
    try:
        b = await request.json()
    except Exception:
        b = {}
    b = b if isinstance(b, dict) else {}
    rating = b.get("rating")
    if not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 5:
        return err(400, "Please choose a rating from 1 to 5 stars.")
    body = clean_body(b.get("body"))
    if not bought_and_received(await db.get_orders_for_user(user["email"]), product_id):
        return err(403, "Only customers who have received this product can review it.")
    account = await db.get_user_by_email(user["email"])
    name = (account or {}).get("name") or "Customer"
    await db.save_review(
        {"email": user["email"], "productId": product_id, "name": name, "rating": rating, "body": body,
         "created": _now(), "updated": _now()}
    )  # fmt: skip
    rows = await db.list_reviews(product_id)
    return {"ok": True, "summary": summarise(rows)}


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@router.get("/api/reviews/recent")
async def recent_reviews():
    """Real written reviews for the home page. An empty list means the section is not shown."""
    rows = [r for r in await db.list_reviews() if r["body"]][:6]
    names = {p["id"]: p["name"] for p in await catalogue.all_products()}
    return {"reviews": [{**public(r), "product": names.get(r["productId"], "")} for r in rows]}


# ---- staff moderation ----
@staff_router.get("/reviews")
async def staff_reviews():
    rows = await db.list_reviews(include_hidden=True)
    names = {p["id"]: p["name"] for p in await catalogue.all_products(include_inactive=True)}
    return {
        "reviews": [{**r, "product": names.get(r["productId"], r["productId"])} for r in rows[:200]]
    }


@staff_router.post("/reviews/hide")
async def hide_review(request: Request):
    try:
        b = await request.json()
    except Exception:
        b = {}
    b = b if isinstance(b, dict) else {}
    email, pid, hidden = b.get("email"), b.get("productId"), b.get("hidden")
    if not isinstance(email, str) or not isinstance(pid, str) or not isinstance(hidden, bool):
        return err(400, "Choose a review and whether to hide it.")
    if not await db.set_review_hidden(email, pid, hidden):
        return err(404, "Review not found.")
    await db.add_audit(
        "admin", "review_hidden" if hidden else "review_shown", pid, {"customer": email}
    )
    return {"ok": True}
