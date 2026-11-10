"""Freshmart (Fatoke Market) backend: FastAPI port of the Express server."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config, db
from .routes import auth as auth_routes
from .routes import orders as order_routes
from .routes import products as product_routes
from .routes import store as store_routes
from .routes import ui as ui_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init()
    mode = "Postgres" if config.USE_POSTGRES else "local JSON file"
    print(f"Fatoke Market backend (Python) running, data store: {mode}")
    yield


app = FastAPI(
    title="Freshmart API", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
)


# Keep the {"error": "..."} shape the frontend already expects.
@app.exception_handler(StarletteHTTPException)
async def http_exc(request: Request, exc: StarletteHTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exc(request: Request, exc: RequestValidationError):
    return JSONResponse({"error": "Invalid request."}, status_code=400)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return resp


app.include_router(auth_routes.router, prefix="/api/auth")
app.include_router(product_routes.router, prefix="/api/products")
app.include_router(order_routes.router, prefix="/api/orders")
app.include_router(store_routes.router, prefix="/api/store")
app.include_router(ui_routes.router)


@app.get("/api/health")
async def health():
    return {"ok": True}


@app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def api_not_found(rest: str):
    raise HTTPException(status_code=404, detail="Not found.")


# Static assets (CSS, compiled TypeScript, HTMX). Pages themselves are rendered by routes/ui.py.
if config.STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
