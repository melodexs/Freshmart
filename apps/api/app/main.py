"""Freshmart (Okwui's Grocery Store, OGS) backend: FastAPI port of the Express server."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import auth, catalogue, config, db
from .routes import account as account_routes
from .routes import admin as admin_routes
from .routes import admins as admins_routes
from .routes import alerts as alert_routes
from .routes import auth as auth_routes
from .routes import newsletter as newsletter_routes
from .routes import orders as order_routes
from .routes import products as product_routes
from .routes import reports as report_routes
from .routes import reset as reset_routes
from .routes import reviews as review_routes
from .routes import store as store_routes
from .routes import ui as ui_routes
from .templating import templates


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init()
    await admins_routes.seed_first_owner()
    # Remember which customers have reset their password, so old sessions stay dead after a restart.
    stored = await db.get_setting("session_cutoffs", {})
    if isinstance(stored, dict):
        for email, when in stored.items():
            if isinstance(when, int):
                auth.revoke_sessions_before(email, when)
    seeded = await catalogue.seed_if_empty()
    if seeded:
        print(f"Catalogue was empty: loaded {seeded} starter products")
    mode = "Postgres" if config.USE_POSTGRES else "local JSON file"
    print(f"OGS backend (Python) running, data store: {mode}")
    yield


app = FastAPI(title="OGS API", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


# Keep the {"error": "..."} shape the frontend already expects.
@app.exception_handler(StarletteHTTPException)
async def http_exc(request: Request, exc: StarletteHTTPException):
    # Browsers asking for a page get a friendly page; the API keeps returning JSON.
    path = request.url.path
    wants_html = "text/html" in request.headers.get("accept", "")
    if exc.status_code == 404 and wants_html and not path.startswith(("/api/", "/ui/")):
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "code": 404,
                "heading": "We could not find that page",
                "message": "The link may be old or mistyped. Head back to the shop to keep browsing.",
            },
            status_code=404,
        )
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(Exception)
async def unexpected_exc(request: Request, exc: Exception):
    """Last resort. Never shows the exception to the visitor; the server log keeps it."""
    import logging

    logging.getLogger("freshmart").exception("Unhandled error on %s", request.url.path)
    path = request.url.path
    wants_html = "text/html" in request.headers.get("accept", "")
    if wants_html and not path.startswith(("/api/", "/ui/")):
        resp = templates.TemplateResponse(
            request,
            "error.html",
            {
                "code": 500,
                "heading": "Something went wrong on our side",
                "message": "We have been notified. Please try again in a moment.",
            },
            status_code=500,
        )
    else:
        resp = JSONResponse({"error": "Something went wrong. Please try again."}, status_code=500)
    # Errors skip the normal middleware, so set the essential headers here.
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.exception_handler(RequestValidationError)
async def validation_exc(request: Request, exc: RequestValidationError):
    return JSONResponse({"error": "Invalid request."}, status_code=400)


# Scripts may only come from this site (no inline scripts), which blocks injected
# script even if markup escaping were ever missed. Inline styles are still used by
# the templates, so style-src allows them.
CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"
    )
    resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    resp.headers.setdefault("Content-Security-Policy", CSP)
    # Static files change rarely: let browsers reuse them for a day, but always
    # revalidate so a new deploy is picked up. Pages and API are never cached.
    if request.url.path.startswith("/static/"):
        resp.headers.setdefault("Cache-Control", "public, max-age=86400, must-revalidate")
    else:
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


app.include_router(auth_routes.router, prefix="/api/auth")
app.include_router(product_routes.router, prefix="/api/products")
app.include_router(order_routes.router, prefix="/api/orders")
app.include_router(store_routes.router, prefix="/api/store")
app.include_router(admins_routes.router, prefix="/api/store")
app.include_router(admins_routes.owner_router, prefix="/api/store/admin")
app.include_router(admin_routes.router, prefix="/api/store/admin")
app.include_router(report_routes.router, prefix="/api/store/admin")
app.include_router(alert_routes.router, prefix="/api/store/admin")
app.include_router(review_routes.router)
app.include_router(newsletter_routes.router)
app.include_router(reset_routes.router)
app.include_router(newsletter_routes.staff_router, prefix="/api/store/admin")
app.include_router(review_routes.staff_router, prefix="/api/store/admin")
app.include_router(account_routes.router, prefix="/api/account")
app.include_router(ui_routes.router)


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.get("/api/ready")
async def ready():
    """Readiness: confirms the data store answers, not just that the process is up."""
    try:
        await db.ping()
    except Exception:
        return JSONResponse({"ok": False, "error": "Data store unavailable."}, status_code=503)
    return {"ok": True}


@app.get("/robots.txt", include_in_schema=False)
async def robots(request: Request):
    base = str(request.base_url).rstrip("/")
    body = (
        f"User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /ui/\n\nSitemap: {base}/sitemap.xml\n"
    )
    return PlainTextResponse(body)


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap(request: Request):
    base = str(request.base_url).rstrip("/")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{base}/</loc></url></urlset>"
    )
    return Response(xml, media_type="application/xml")


@app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def api_not_found(rest: str):
    raise HTTPException(status_code=404, detail="Not found.")


# Static assets (CSS, compiled TypeScript, HTMX). Pages themselves are rendered by routes/ui.py.
if config.STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
