"""Postgres store (asyncpg). Used automatically when DATABASE_URL is set.

Same schema as the Node version, so an existing Render database keeps working.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import asyncpg

from . import config

_pool: asyncpg.Pool | None = None


def _dsn() -> str:
    url = config.DATABASE_URL
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    return url


async def init() -> None:
    global _pool
    # Hosted Postgres (Render/Neon/Supabase) needs SSL. "require" encrypts
    # without verifying the CA chain, matching the Node version's behaviour.
    # Serverless Postgres (Neon) suspends when idle and drops connections, so a pooled
    # connection can be dead by the next order. Recycle idle ones well before that, and
    # never let a call hang forever.
    _pool = await asyncpg.create_pool(
        _dsn(),
        ssl=config.PG_SSL,
        min_size=1,
        max_size=5,
        timeout=30,  # opening a connection (allows for a cold database waking up)
        command_timeout=30,  # any single query
        max_inactive_connection_lifetime=120,  # drop idle connections after 2 minutes
    )
    async with _pool.acquire() as c:
        await c.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              email TEXT PRIMARY KEY, name TEXT NOT NULL,
              phone TEXT NOT NULL, pass_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS orders (
              id TEXT PRIMARY KEY, date TIMESTAMPTZ NOT NULL, items JSONB NOT NULL,
              subtotal INTEGER NOT NULL, delivery_fee INTEGER NOT NULL, total INTEGER NOT NULL,
              address TEXT NOT NULL, phone TEXT NOT NULL, city TEXT,
              pay_method TEXT NOT NULL, payment_detail JSONB, status TEXT NOT NULL,
              user_email TEXT NOT NULL REFERENCES users(email));
            CREATE TABLE IF NOT EXISTS store_sms (
              id TEXT NOT NULL, text TEXT NOT NULL, date TIMESTAMPTZ NOT NULL);
            CREATE TABLE IF NOT EXISTS categories (
              id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, sort INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS products (
              id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
              emoji TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
              image TEXT NOT NULL DEFAULT '', options JSONB NOT NULL,
              compare_prices JSONB NOT NULL DEFAULT '[]'::jsonb,
              stock INTEGER, active BOOLEAN NOT NULL DEFAULT TRUE,
              featured BOOLEAN NOT NULL DEFAULT FALSE, sort INTEGER NOT NULL DEFAULT 0,
              updated TIMESTAMPTZ NOT NULL DEFAULT now());
            CREATE TABLE IF NOT EXISTS settings (
              key TEXT PRIMARY KEY, value JSONB NOT NULL);
            """
        )


def _iso(v) -> str:
    """Same ISO format as the file store and the Node version: ...Z"""
    if isinstance(v, datetime):
        return v.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return v


def _ts(v: str) -> datetime:
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


def _user(r):
    if r is None:
        return None
    return {"name": r["name"], "phone": r["phone"], "email": r["email"], "passHash": r["pass_hash"]}


async def get_user_by_email(email: str):
    async with _pool.acquire() as c:
        return _user(await c.fetchrow("SELECT * FROM users WHERE email=$1", email))


async def save_user(user: dict) -> None:
    async with _pool.acquire() as c:
        await c.execute(
            """INSERT INTO users (email,name,phone,pass_hash) VALUES ($1,$2,$3,$4)
               ON CONFLICT (email) DO UPDATE SET name=$2, phone=$3, pass_hash=$4""",
            user["email"],
            user["name"],
            user["phone"],
            user["passHash"],
        )


async def create_user(user: dict) -> bool:
    async with _pool.acquire() as c:
        res = await c.execute(
            """INSERT INTO users (email,name,phone,pass_hash) VALUES ($1,$2,$3,$4)
               ON CONFLICT (email) DO NOTHING""",
            user["email"],
            user["name"],
            user["phone"],
            user["passHash"],
        )
    return res.endswith(" 1")


def _order(r) -> dict:
    items = r["items"]
    detail = r["payment_detail"]
    return {
        "id": r["id"],
        "date": _iso(r["date"]),
        "items": json.loads(items) if isinstance(items, str) else items,
        "subtotal": r["subtotal"],
        "deliveryFee": r["delivery_fee"],
        "total": r["total"],
        "address": r["address"],
        "phone": r["phone"],
        "city": r["city"],
        "payMethod": r["pay_method"],
        "paymentDetail": json.loads(detail) if isinstance(detail, str) else detail,
        "status": r["status"],
        "user": r["user_email"],
    }


async def get_orders_for_user(email: str):
    async with _pool.acquire() as c:
        rows = await c.fetch("SELECT * FROM orders WHERE user_email=$1 ORDER BY date DESC", email)
    return [_order(r) for r in rows]


async def add_order(o: dict) -> None:
    async with _pool.acquire() as c:
        await c.execute(
            """INSERT INTO orders (id,date,items,subtotal,delivery_fee,total,address,phone,
                 city,pay_method,payment_detail,status,user_email)
               VALUES ($1,$2,$3::jsonb,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12,$13)""",
            o["id"],
            _ts(o["date"]),
            json.dumps(o["items"]),
            o["subtotal"],
            o["deliveryFee"],
            o["total"],
            o["address"],
            o["phone"],
            o["city"],
            o["payMethod"],
            json.dumps(o.get("paymentDetail") or {}),
            o["status"],
            o["user"],
        )


async def get_store_sms():
    async with _pool.acquire() as c:
        rows = await c.fetch("SELECT * FROM store_sms ORDER BY date DESC")
    return [{"id": r["id"], "text": r["text"], "date": _iso(r["date"])} for r in rows]


async def add_store_sms(e: dict) -> None:
    async with _pool.acquire() as c:
        await c.execute(
            "INSERT INTO store_sms (id,text,date) VALUES ($1,$2,$3)",
            e["id"],
            e["text"],
            _ts(e["date"]),
        )


async def get_order(order_id: str):
    async with _pool.acquire() as c:
        r = await c.fetchrow("SELECT * FROM orders WHERE id=$1", order_id)
    return _order(r) if r else None


async def get_all_orders():
    async with _pool.acquire() as c:
        rows = await c.fetch("SELECT * FROM orders ORDER BY date DESC")
    return [_order(r) for r in rows]


async def update_order_status(
    order_id: str, new_status: str, allowed_from: list[str] | None = None
) -> bool:
    """Atomic: the status check and the update are one statement."""
    async with _pool.acquire() as c:
        if allowed_from is None:
            res = await c.execute("UPDATE orders SET status=$2 WHERE id=$1", order_id, new_status)
        else:
            res = await c.execute(
                "UPDATE orders SET status=$2 WHERE id=$1 AND status = ANY($3::text[])",
                order_id,
                new_status,
                allowed_from,
            )
    return res.endswith(" 1")


async def ping() -> None:
    """Cheap liveness check: one trivial query, no matter how many orders exist."""
    async with _pool.acquire() as c:
        await c.fetchval("SELECT 1")


# ---------- catalogue ----------


def _product(r) -> dict:
    opts, cmp_ = r["options"], r["compare_prices"]
    return {
        "id": r["id"],
        "name": r["name"],
        "cat": r["category"],
        "emoji": r["emoji"],
        "description": r["description"],
        "image": r["image"],
        "options": json.loads(opts) if isinstance(opts, str) else opts,
        "comparePrices": json.loads(cmp_) if isinstance(cmp_, str) else cmp_,
        "stock": r["stock"],
        "active": r["active"],
        "featured": r["featured"],
        "sort": r["sort"],
    }


async def list_products(include_inactive: bool = False) -> list[dict]:
    async with _pool.acquire() as c:
        q = "SELECT * FROM products"
        if not include_inactive:
            q += " WHERE active"
        rows = await c.fetch(q + " ORDER BY sort, name")
    return [_product(r) for r in rows]


async def get_product(product_id: str) -> dict | None:
    async with _pool.acquire() as c:
        r = await c.fetchrow("SELECT * FROM products WHERE id=$1", product_id)
    return _product(r) if r else None


async def save_product(p: dict) -> None:
    """Insert or replace a whole product."""
    async with _pool.acquire() as c:
        await c.execute(
            """INSERT INTO products (id,name,category,emoji,description,image,options,
                 compare_prices,stock,active,featured,sort,updated)
               VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9,$10,$11,$12,now())
               ON CONFLICT (id) DO UPDATE SET name=$2, category=$3, emoji=$4, description=$5,
                 image=$6, options=$7::jsonb, compare_prices=$8::jsonb, stock=$9, active=$10,
                 featured=$11, sort=$12, updated=now()""",
            p["id"],
            p["name"],
            p["cat"],
            p.get("emoji", ""),
            p.get("description", ""),
            p.get("image", ""),
            json.dumps(p["options"]),
            json.dumps(p.get("comparePrices") or []),
            p.get("stock"),
            bool(p.get("active", True)),
            bool(p.get("featured", False)),
            int(p.get("sort", 0)),
        )


async def delete_product(product_id: str) -> bool:
    async with _pool.acquire() as c:
        res = await c.execute("DELETE FROM products WHERE id=$1", product_id)
    return res.endswith(" 1")


async def count_products() -> int:
    async with _pool.acquire() as c:
        return await c.fetchval("SELECT count(*) FROM products")


async def adjust_stock(product_id: str, delta: int) -> int | None:
    """Add delta to a tracked stock count, never below zero. Returns the new count, or
    None when the product does not track stock (stock is NULL) or does not exist."""
    async with _pool.acquire() as c:
        return await c.fetchval(
            """UPDATE products SET stock = GREATEST(stock + $2, 0), updated=now()
               WHERE id=$1 AND stock IS NOT NULL RETURNING stock""",
            product_id,
            delta,
        )


async def get_setting(key: str, default=None):
    async with _pool.acquire() as c:
        v = await c.fetchval("SELECT value FROM settings WHERE key=$1", key)
    if v is None:
        return default
    return json.loads(v) if isinstance(v, str) else v


async def set_setting(key: str, value) -> None:
    async with _pool.acquire() as c:
        await c.execute(
            """INSERT INTO settings (key,value) VALUES ($1,$2::jsonb)
               ON CONFLICT (key) DO UPDATE SET value=$2::jsonb""",
            key,
            json.dumps(value),
        )


async def reserve_stock(product_id: str, qty: int) -> bool:
    """Take qty off a tracked product only if enough is left, in one statement, so two
    orders for the last item cannot both succeed. Untracked products (stock NULL) always pass."""
    async with _pool.acquire() as c:
        res = await c.execute(
            """UPDATE products SET stock = stock - $2, updated=now()
               WHERE id=$1 AND (stock IS NULL OR stock >= $2)""",
            product_id,
            qty,
        )
    return res.endswith(" 1")
