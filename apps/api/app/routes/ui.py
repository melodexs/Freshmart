"""Server-rendered pages and HTML fragments (Jinja2 + HTMX).

The JSON API under /api stays as it is. These routes return HTML so the
browser needs very little JavaScript. Every template autoescapes.
"""

from __future__ import annotations

import bcrypt
from fastapi import APIRouter, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response

from .. import auth, db, order_status, products, ratelimit
from ..templating import templates

router = APIRouter()

CATEGORIES = ["All", *dict.fromkeys(p["cat"] for p in products.PRODUCTS)]


def _first_name(user: dict | None) -> str:
    return (user or {}).get("name", "").split(" ")[0]


def _render(request: Request, name: str, status: int = 200, **ctx) -> HTMLResponse:
    ctx.setdefault("user", auth.current_user(request))
    return templates.TemplateResponse(request, name, ctx, status_code=status)


def _trigger(resp: Response, event: str, detail: dict | None = None) -> Response:
    """Tell the page's TypeScript that something happened (HTMX HX-Trigger).

    The header is JSON, so non-ASCII names are escaped to keep it header-safe.
    """
    import json

    resp.headers["HX-Trigger"] = json.dumps({event: detail or {}}, ensure_ascii=True)
    return resp


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return _render(
        request,
        "index.html",
        categories=CATEGORIES,
        active="All",
        delivery_fee=products.DELIVERY_FEE,
    )


@router.get("/ui/products", response_class=HTMLResponse)
async def product_grid(request: Request, cat: str = "All", q: str = ""):
    q_norm = q.strip().lower()[:60]
    items = [
        p
        for p in products.PRODUCTS
        if (cat == "All" or p["cat"] == cat) and q_norm in p["name"].lower()
    ]
    resp = _render(
        request,
        "partials/products.html",
        products=items,
        categories=CATEGORIES,
        active=cat if cat in CATEGORIES else "All",
    )
    return resp


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
    return _render(
        request,
        "partials/store_feed.html",
        orders=orders,
        options=order_status.STAFF_NEXT,
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
