"""Server-rendered pages and HTML fragments (Jinja2 + HTMX).

The JSON API under /api stays as it is. These routes return HTML so the
browser needs very little JavaScript. Every template autoescapes.
"""

from __future__ import annotations

import re

import bcrypt
from fastapi import APIRouter, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .. import auth, catalogue, config, db, order_status, ratelimit
from ..phone import whatsapp_link
from ..templating import photo_for, templates
from .reviews import bought_and_received, public, summarise

router = APIRouter()


def _first_name(user: dict | None) -> str:
    return (user or {}).get("name", "").split(" ")[0]


def _render(request: Request, name: str, status: int = 200, **ctx) -> HTMLResponse:
    ctx.setdefault("user", auth.current_user(request))
    return templates.TemplateResponse(request, name, ctx, status_code=status)


async def rating_map() -> dict[str, dict]:
    """{product id: {"average", "count"}} from visible reviews. Products without reviews are absent,
    so a card shows stars only when real customers have rated it."""
    by_product: dict[str, list[dict]] = {}
    for r in await db.list_reviews():
        by_product.setdefault(r["productId"], []).append(r)
    return {pid: summarise(rows) for pid, rows in by_product.items()}


def _trigger(resp: Response, event: str, detail: dict | None = None) -> Response:
    """Tell the page's TypeScript that something happened (HTMX HX-Trigger).

    The header is JSON, so non-ASCII names are escaped to keep it header-safe.
    """
    import json

    resp.headers["HX-Trigger"] = json.dumps({event: detail or {}}, ensure_ascii=True)
    return resp


CATEGORY_EMOJI = {
    "Foodstuff": "🍚",
    "Snacks": "🍪",
    "Drinks & Dairy": "🥤",
    "Fresh Produce": "🥬",
    "Household": "🧴",
    "Bakery": "🍞",
    "Beauty & Personal Care": "🧼",
}


async def _testimonials() -> list[dict]:
    """Real written reviews only. Empty means the home page shows no testimonials section at all."""
    rows = [r for r in await db.list_reviews() if r["body"]][:6]
    names = {p["id"]: p["name"] for p in await catalogue.all_products()}
    return [{**public(r), "product": names.get(r["productId"], "")} for r in rows]


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    products = await catalogue.all_products()
    counts: dict[str, int] = {}
    for p in products:
        counts[p["cat"]] = counts.get(p["cat"], 0) + 1
    cards = [
        {"name": n, "count": c, "emoji": CATEGORY_EMOJI.get(n, "🛒")} for n, c in counts.items()
    ]
    # Real product photos for the hero: one per category first, so the cluster shows range.
    picks, seen = [], set()
    for pr in products:
        photo = photo_for(pr)
        if photo and pr["cat"] not in seen and pr.get("stock", 1) != 0:
            seen.add(pr["cat"])
            picks.append({"id": pr["id"], "name": pr["name"], "photo": photo})
    hero_picks = picks[:4]
    shelves = [
        {
            "key": "best",
            "title": "Best sellers",
            "items": await catalogue.shelf(section="best", limit=6),
        },
        {
            "key": "offers",
            "title": "Special offers",
            "items": await catalogue.shelf(section="offers", limit=6),
        },
        {
            "key": "new",
            "title": "New arrivals",
            "items": await catalogue.shelf(section="new", limit=6),
        },
        {
            "key": "featured",
            "title": "Featured products",
            "items": await catalogue.shelf(section="featured", limit=6),
        },
    ]
    return _render(
        request,
        "index.html",
        categories=["All", *await catalogue.categories()],
        active="All",
        category_cards=cards,
        ratings=await rating_map(),
        testimonials=await _testimonials(),
        product_total=len(products),
        hero_picks=hero_picks,
        shelves=shelves,
        discount=catalogue.discount_percent,
        delivery_fee=await catalogue.delivery_fee(),
        areas=await catalogue.delivery_areas(),
        bank=await catalogue.bank_details(),
        contact_phone=await db.get_setting("contact_phone", ""),
        whatsapp=whatsapp_link(
            await db.get_setting("whatsapp", "") or config.WHATSAPP_NUMBER,
            "Hello! I have a question about my order.",
        ),
    )


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    """The admin shell. It holds no data: every figure comes from the guarded /api/store/admin API."""
    resp = _render(request, "admin.html")
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _price(v: str) -> int | None:
    v = (v or "").strip()
    return int(v) if v.isdigit() and len(v) <= 9 else None


@router.get("/ui/products", response_class=HTMLResponse)
async def product_grid(
    request: Request,
    cat: str = "All",
    q: str = "",
    sort: str = "default",
    section: str = "",
    min: str = "",
    max: str = "",
    favs: str = "",
):
    categories = ["All", *await catalogue.categories()]
    user = auth.current_user(request)
    fav_ids = await db.get_favourites(user["email"]) if user else []
    items = await catalogue.shelf(
        cat=cat if cat in categories else "All",
        q=q,
        sort=sort,
        section=section if section in ("best", "new", "offers", "featured") else "",
        min_price=_price(min),
        max_price=_price(max),
        only_ids=fav_ids if favs == "1" else None,
    )
    heading = {
        "best": "Best sellers",
        "new": "New arrivals",
        "offers": "Special offers",
        "featured": "Featured products",
    }.get(section) or (
        "Your favourites" if favs == "1" else ("All products" if cat == "All" else cat)
    )
    return _render(
        request,
        "partials/products.html",
        products=items,
        categories=categories,
        active=cat if cat in categories else "All",
        heading=heading,
        fav_ids=fav_ids,
        ratings=await rating_map(),
        discount=catalogue.discount_percent,
        favs_only=favs == "1",
    )


@router.get("/media/{image_id}")
async def media(image_id: str):
    """A product photo uploaded by the store. Only ids we generated are served."""
    if not re.fullmatch(r"im[0-9a-f]{16}", image_id):
        return Response(status_code=404)
    data = await db.get_image(image_id)
    if data is None:
        return Response(status_code=404)
    return Response(
        data,
        media_type="image/webp",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
        },
    )


@router.get("/account", response_class=HTMLResponse)
async def account_page(request: Request):
    if not auth.current_user(request):
        return RedirectResponse("/?signin=1", status_code=303)
    return _render(request, "account.html", areas=await catalogue.delivery_areas())


@router.get("/product/{product_id}", response_class=HTMLResponse)
async def product_page(request: Request, product_id: str):
    p = await db.get_product(product_id)
    if not p or not p.get("active", True):
        return _render(request, "product_missing.html", status=404)
    user = auth.current_user(request)
    fav_ids = await db.get_favourites(user["email"]) if user else []
    visible = await db.list_reviews(p["id"])
    mine = await db.get_review(user["email"], p["id"]) if user else None
    can_review = (
        bought_and_received(await db.get_orders_for_user(user["email"]), p["id"]) if user else False
    )
    return _render(
        request,
        "product.html",
        p=p,
        review_summary=summarise(visible),
        reviews=[public(r) for r in visible[:50]],
        my_review=mine,
        can_review=can_review,
        user_signed_in=bool(user),
        related=await catalogue.related(p),
        discount=catalogue.discount_percent,
        in_stock=catalogue.in_stock(p),
        fav_ids=fav_ids,
        on=p["id"] in fav_ids,
        pid=p["id"],
        delivery_fee=await catalogue.delivery_fee(),
        areas=await catalogue.delivery_areas(),
        bank=await catalogue.bank_details(),
        contact_phone=await db.get_setting("contact_phone", ""),
        whatsapp=whatsapp_link(
            config.WHATSAPP_NUMBER, f"Hello! I have a question about {p['name']}."
        ),
    )


@router.post("/ui/favourites/{product_id}", response_class=HTMLResponse)
async def toggle_favourite(request: Request, product_id: str):
    """Add or remove a favourite for the signed-in customer. Returns the heart button."""
    user = auth.current_user(request)
    if not user:
        # Leave the heart as it is and ask the page to open the sign-in dialog. (htmx ignores the
        # body of an error response, so a 401 here would show the visitor nothing at all.)
        resp = _render(request, "partials/fav_button.html", pid=product_id, on=False)
        return _trigger(resp, "need-signin", {"message": "Sign in to save your favourites."})
    if not await db.get_product(product_id):
        return HTMLResponse("", status_code=404)
    favs = await db.get_favourites(user["email"])
    if product_id in favs:
        await db.remove_favourite(user["email"], product_id)
        now = False
    else:
        await db.add_favourite(user["email"], product_id)
        now = True
    return _render(request, "partials/fav_button.html", pid=product_id, on=now)


@router.get("/ui/header", response_class=HTMLResponse)
async def header_account(request: Request):
    return _render(request, "partials/account.html")


@router.get("/ui/signin", response_class=HTMLResponse)
async def signin_form(request: Request, last: str = ""):
    """Sign-in form. `last` is the last email remembered on this device."""
    known = None
    if last:
        ratelimit.limit(request, "lookup", 20, 60)
        known = await db.get_user_by_email(last.strip().lower())
    return _render(
        request,
        "partials/signin.html",
        known={"name": _first_name(known), "email": known["email"]} if known else None,
        message=None,
    )


@router.post("/ui/login", response_class=HTMLResponse)
async def login(request: Request, email: str = Form(""), password: str = Form("")):
    ratelimit.limit(request, "login", 10, 60)
    email = email.strip().lower()
    if not email or not password:
        return _render(
            request,
            "partials/signin.html",
            known=None,
            message=("error", "Please fill in email and password."),
        )
    user = await db.get_user_by_email(email)
    ok = bool(user) and await run_in_threadpool(
        lambda: bcrypt.checkpw(password.encode(), user["passHash"].encode())
    )
    if not ok:
        return _render(
            request,
            "partials/signin.html",
            known=None,
            message=("error", "Email or password is incorrect."),
        )
    resp = _render(request, "partials/signed_in.html", user=user, signed_in_email=user["email"])
    auth.set_auth_cookie(resp, auth.sign_token(user))
    return _trigger(resp, "signed-in", {"email": user["email"], "firstName": _first_name(user)})


@router.get("/ui/signup", response_class=HTMLResponse)
async def signup_form(request: Request):
    return _render(request, "partials/signup.html", message=None, form={})


@router.post("/ui/signup", response_class=HTMLResponse)
async def signup(
    request: Request,
    name: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    password_confirm: str = Form(""),
):
    ratelimit.limit(request, "signup", 10, 60)
    name, phone, email = name.strip(), phone.strip(), email.strip().lower()
    form = {"name": name, "phone": phone, "email": email}

    def fail(text: str):
        return _render(request, "partials/signup.html", message=("error", text), form=form)

    if not name or not phone:
        return fail("Please add your name and phone number.")
    if not email or not password:
        return fail("Please fill in email and password.")
    if len(password) < 6:
        return fail("Password should be at least 6 characters.")
    if password != password_confirm:
        return fail("Passwords don't match. Please re-enter them.")

    pass_hash = await run_in_threadpool(
        lambda: bcrypt.hashpw(password.encode(), bcrypt.gensalt(10)).decode()
    )
    user = {"name": name, "phone": phone, "email": email, "passHash": pass_hash}
    if not await db.create_user(user):
        return fail("An account with that email already exists. Try signing in instead.")
    resp = _render(request, "partials/signed_in.html", user=user, signed_in_email=email)
    auth.set_auth_cookie(resp, auth.sign_token(user))
    return _trigger(resp, "signed-in", {"email": email, "firstName": _first_name(user)})


@router.post("/ui/logout", response_class=HTMLResponse)
async def logout(request: Request):
    resp = _render(request, "partials/account.html", user=None)
    auth.clear_auth_cookie(resp)
    return _trigger(resp, "signed-out")


@router.get("/ui/orders", response_class=HTMLResponse)
async def my_orders(request: Request):
    user = auth.current_user(request)
    if not user:
        return _render(
            request,
            "partials/need_signin.html",
            status=401,
            reason="Sign in to see your past orders.",
        )
    orders = await db.get_orders_for_user(user["email"])
    return _render(request, "partials/orders.html", orders=orders)


@router.get("/api/store/ui", response_class=HTMLResponse)
async def store_inbox(request: Request):
    if not auth.staff_enabled():
        return _render(request, "partials/store_off.html")
    if not auth.is_staff(request):
        return _render(request, "partials/store_login.html", message=None)
    return await _store_feed(request)


@router.post("/api/store/ui/login", response_class=HTMLResponse)
async def store_login(request: Request, key: str = Form("")):
    ratelimit.limit(request, "staff-login", 5, 60)
    if not auth.staff_enabled():
        return _render(request, "partials/store_off.html")
    if not auth.check_staff_key(key):
        return _render(
            request,
            "partials/store_login.html",
            message=("error", "That staff key is not correct."),
        )
    resp = await _store_feed(request)
    auth.set_staff_cookie(resp)
    return resp


@router.post("/api/store/ui/logout", response_class=HTMLResponse)
async def store_logout(request: Request):
    resp = _render(request, "partials/store_login.html", message=None)
    auth.clear_staff_cookie(resp)
    return resp


async def _store_feed(request: Request, notice: tuple[str, str] | None = None) -> HTMLResponse:
    orders = await db.get_all_orders()
    counts = {st: sum(1 for o in orders if o["status"] == st) for st in order_status.ALL}
    return _render(
        request,
        "partials/store_feed.html",
        orders=orders,
        options=order_status.STAFF_NEXT,
        counts=counts,
        notice=notice,
    )


@router.post("/api/store/ui/orders/{order_id}/status", response_class=HTMLResponse)
async def staff_set_status(request: Request, order_id: str, status: str = Form("")):
    """Staff moves an order along its lifecycle. Only allowed moves are accepted."""
    if not auth.staff_enabled():
        return _render(request, "partials/store_off.html")
    if not auth.is_staff(request):
        return _render(request, "partials/store_login.html", status=401, message=None)
    order = await db.get_order(order_id)
    if not order:
        return await _store_feed(request, ("error", "That order was not found."))
    if not order_status.staff_may_move(order["status"], status):
        return await _store_feed(
            request,
            ("error", f'Order {order_id} cannot move from "{order["status"]}" to "{status}".'),
        )
    # Atomic: only applies if the status is still what staff were looking at.
    ok = await db.update_order_status(order_id, status, allowed_from=[order["status"]])
    if not ok:
        return await _store_feed(
            request, ("error", f"Order {order_id} was just changed. Please review it again.")
        )
    await db.add_audit("admin", "status_changed", order_id, {"from": order["status"], "to": status})
    if status == order_status.CANCELLED:
        await catalogue.restock_order(order)
    note = order_status.refund_note(order) if status == order_status.CANCELLED else None
    msg = f"Order {order_id} is now: {status}." + (f" {note}" if note else "")
    return await _store_feed(request, ("ok", msg))


@router.post("/ui/orders/{order_id}/cancel", response_class=HTMLResponse)
async def customer_cancel(request: Request, order_id: str):
    """A signed-in customer cancels their own order, only before it leaves the store."""
    user = auth.current_user(request)
    if not user:
        return _render(
            request,
            "partials/need_signin.html",
            status=401,
            reason="Sign in to manage your orders.",
        )
    order = await db.get_order(order_id)
    # Same answer for "not found" and "someone else's order" so IDs cannot be probed.
    if not order or order.get("user") != user["email"]:
        orders = await db.get_orders_for_user(user["email"])
        return _render(
            request,
            "partials/orders.html",
            orders=orders,
            notice=("error", "That order was not found."),
        )
    ok = False
    if order_status.customer_may_cancel(order["status"]):
        ok = await db.update_order_status(
            order_id, order_status.CANCELLED, allowed_from=order_status.CUSTOMER_CAN_CANCEL_FROM
        )
        if ok:
            await catalogue.restock_order(order)
    orders = await db.get_orders_for_user(user["email"])
    if not ok:
        notice = (
            "error",
            f"Order {order_id} can no longer be cancelled because it is already on its way.",
        )
    elif order.get("payMethod") == "before":
        notice = (
            "ok",
            f"Order {order_id} was cancelled. The store will contact you about your refund.",
        )
    else:
        notice = ("ok", f"Order {order_id} was cancelled.")
    return _render(request, "partials/orders.html", orders=orders, notice=notice)


@router.get("/ui/track", response_class=HTMLResponse)
async def track_form(request: Request):
    return _render(request, "partials/track.html", result=None, message=None)


@router.post("/ui/track", response_class=HTMLResponse)
async def track_lookup(request: Request, order_id: str = Form(""), phone: str = Form("")):
    """Find an order with its reference AND the phone number used on it.

    Both must match, so a guessed reference alone reveals nothing.
    """
    ratelimit.limit(request, "track", 10, 60)
    ref = order_id.strip().upper()[:20]
    digits = "".join(ch for ch in phone if ch.isdigit())
    not_found = "We could not find an order with that reference and phone number."
    if not ref or len(digits) < 6:
        return _render(request, "partials/track.html", result=None, message=("error", not_found))
    order = await db.get_order(ref)
    stored = "".join(ch for ch in str(order.get("phone", "")) if ch.isdigit()) if order else ""
    # Compare the last 9 digits so 0803... and +234803... both match.
    if not order or stored[-9:] != digits[-9:]:
        return _render(request, "partials/track.html", result=None, message=("error", not_found))
    return _render(
        request,
        "partials/track.html",
        result=order,
        message=None,
        progress=order_status.progress(order["status"]),
    )
