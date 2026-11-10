"""Server-rendered pages and HTML fragments (Jinja2 + HTMX).

The JSON API under /api stays as it is. These routes return HTML so the
browser needs very little JavaScript. Every template autoescapes.
"""

from __future__ import annotations

import bcrypt
from fastapi import APIRouter, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, Response

from .. import auth, db, products, ratelimit
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
    return _render(request, "partials/store_feed.html", notifications=await db.get_store_sms())


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
    resp = _render(request, "partials/store_feed.html", notifications=await db.get_store_sms())
    auth.set_staff_cookie(resp)
    return resp


@router.post("/api/store/ui/logout", response_class=HTMLResponse)
async def store_logout(request: Request):
    resp = _render(request, "partials/store_login.html", message=None)
    auth.clear_staff_cookie(resp)
    return resp
