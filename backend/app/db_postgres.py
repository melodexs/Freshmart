"""Postgres store (asyncpg). Used automatically when DATABASE_URL is set.

Same schema as the Node version, so an existing Render database keeps working.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import asyncpg

from . import config

_pool: asyncpg.Pool | None = None


def _dsn() -> str:
    url = config.DATABASE_URL
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


async def init() -> None:
    global _pool
    # Hosted Postgres (Render/Neon/Supabase) needs SSL. "require" encrypts
    # without verifying the CA chain, matching the Node version's behaviour.
    _pool = await asyncpg.create_pool(_dsn(), ssl=config.PG_SSL, min_size=1, max_size=5)
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
            """
        )


def _iso(v) -> str:
    """Same ISO format as the file store and the Node version: ...Z"""
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
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
            user["email"], user["name"], user["phone"], user["passHash"],
        )


async def create_user(user: dict) -> bool:
    async with _pool.acquire() as c:
        res = await c.execute(
            """INSERT INTO users (email,name,phone,pass_hash) VALUES ($1,$2,$3,$4)
               ON CONFLICT (email) DO NOTHING""",
            user["email"], user["name"], user["phone"], user["passHash"],
        )
    return res.endswith(" 1")


def _order(r) -> dict:
    items = r["items"]
    detail = r["payment_detail"]
    return {
        "id": r["id"], "date": _iso(r["date"]),
        "items": json.loads(items) if isinstance(items, str) else items,
        "subtotal": r["subtotal"], "deliveryFee": r["delivery_fee"], "total": r["total"],
        "address": r["address"], "phone": r["phone"], "city": r["city"],
        "payMethod": r["pay_method"],
        "paymentDetail": json.loads(detail) if isinstance(detail, str) else detail,
        "status": r["status"], "user": r["user_email"],
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
            o["id"], _ts(o["date"]), json.dumps(o["items"]), o["subtotal"], o["deliveryFee"],
            o["total"], o["address"], o["phone"], o["city"], o["payMethod"],
            json.dumps(o.get("paymentDetail") or {}), o["status"], o["user"],
        )


async def get_store_sms():
    async with _pool.acquire() as c:
        rows = await c.fetch("SELECT * FROM store_sms ORDER BY date DESC")
    return [{"id": r["id"], "text": r["text"], "date": _iso(r["date"])} for r in rows]


async def add_store_sms(e: dict) -> None:
    async with _pool.acquire() as c:
        await c.execute(
            "INSERT INTO store_sms (id,text,date) VALUES ($1,$2,$3)",
            e["id"], e["text"], _ts(e["date"]),
        )
