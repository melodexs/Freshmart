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
            CREATE TABLE IF NOT EXISTS stock_moves (
              id BIGSERIAL PRIMARY KEY, product_id TEXT NOT NULL, change INTEGER NOT NULL,
              after INTEGER, reason TEXT NOT NULL, order_id TEXT, actor TEXT NOT NULL,
              at TIMESTAMPTZ NOT NULL DEFAULT now());
            CREATE INDEX IF NOT EXISTS stock_moves_product_idx ON stock_moves (product_id, at DESC);
            CREATE TABLE IF NOT EXISTS discount_codes (
              code TEXT PRIMARY KEY, rule JSONB NOT NULL, created TIMESTAMPTZ NOT NULL DEFAULT now());
            CREATE TABLE IF NOT EXISTS discount_uses (
              id BIGSERIAL PRIMARY KEY, code TEXT NOT NULL, email TEXT NOT NULL, order_id TEXT NOT NULL UNIQUE,
              amount INTEGER NOT NULL, at TIMESTAMPTZ NOT NULL DEFAULT now());
            CREATE INDEX IF NOT EXISTS discount_uses_code_idx ON discount_uses (code, email);
            CREATE TABLE IF NOT EXISTS images (
              id TEXT PRIMARY KEY, data BYTEA NOT NULL, created TIMESTAMPTZ NOT NULL DEFAULT now());
            CREATE TABLE IF NOT EXISTS addresses (
              id TEXT PRIMARY KEY, email TEXT NOT NULL, label TEXT NOT NULL, area TEXT NOT NULL,
              address TEXT NOT NULL, phone TEXT NOT NULL, is_default BOOLEAN NOT NULL DEFAULT FALSE,
              created TIMESTAMPTZ NOT NULL DEFAULT now());
            CREATE INDEX IF NOT EXISTS addresses_email_idx ON addresses (email);
            CREATE TABLE IF NOT EXISTS favourites (
              email TEXT NOT NULL, product_id TEXT NOT NULL, at TIMESTAMPTZ NOT NULL DEFAULT now(),
              PRIMARY KEY (email, product_id));
            CREATE TABLE IF NOT EXISTS reviews (
              email TEXT NOT NULL, product_id TEXT NOT NULL, name TEXT NOT NULL,
              rating SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5), body TEXT NOT NULL DEFAULT '',
              hidden BOOLEAN NOT NULL DEFAULT FALSE,
              created TIMESTAMPTZ NOT NULL DEFAULT now(), updated TIMESTAMPTZ NOT NULL DEFAULT now(),
              PRIMARY KEY (email, product_id));
            CREATE INDEX IF NOT EXISTS reviews_product_idx ON reviews (product_id);
            CREATE TABLE IF NOT EXISTS audit_log (
              id BIGSERIAL PRIMARY KEY, at TIMESTAMPTZ NOT NULL DEFAULT now(),
              actor TEXT NOT NULL, action TEXT NOT NULL, subject TEXT NOT NULL,
              detail JSONB NOT NULL DEFAULT '{}'::jsonb);
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


def _pd(detail) -> dict:
    d = json.loads(detail) if isinstance(detail, str) else detail
    return d if isinstance(d, dict) else {}


def _order(r) -> dict:
    items = r["items"]
    detail = r["payment_detail"]
    return {
        "id": r["id"],
        "date": _iso(r["date"]),
        "items": json.loads(items) if isinstance(items, str) else items,
        "subtotal": r["subtotal"],
        "discount": _pd(detail).get("discountAmount", 0),
        "deliveryFee": r["delivery_fee"],
        "total": r["total"],
        "address": r["address"],
        "phone": r["phone"],
        "city": r["city"],
        "payMethod": r["pay_method"],
        "paymentDetail": _pd(detail),
        "customerName": _pd(detail).get("_name", ""),
        "instructions": _pd(detail).get("_instructions", ""),
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
            json.dumps(
                {
                    **(o.get("paymentDetail") or {}),
                    "_name": o.get("customerName", ""),
                    "_instructions": o.get("instructions", ""),
                }
            ),
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


async def add_audit(actor: str, action: str, subject: str, detail: dict) -> None:
    """Append-only record of a sensitive action. Never updated or deleted by the app."""
    async with _pool.acquire() as c:
        await c.execute(
            "INSERT INTO audit_log (actor,action,subject,detail) VALUES ($1,$2,$3,$4::jsonb)",
            actor,
            action,
            subject,
            json.dumps(detail),
        )


async def get_audit(subject: str | None = None, limit: int = 100) -> list[dict]:
    async with _pool.acquire() as c:
        if subject:
            rows = await c.fetch(
                "SELECT * FROM audit_log WHERE subject=$1 ORDER BY id DESC LIMIT $2", subject, limit
            )
        else:
            rows = await c.fetch("SELECT * FROM audit_log ORDER BY id DESC LIMIT $1", limit)
    out = []
    for r in rows:
        d = r["detail"]
        out.append(
            {
                "at": _iso(r["at"]),
                "actor": r["actor"],
                "action": r["action"],
                "subject": r["subject"],
                "detail": json.loads(d) if isinstance(d, str) else d,
            }
        )
    return out


async def confirm_payment(order_id: str, expected_from: str, new_status: str, record: dict) -> bool:
    """Atomically move an order out of "awaiting payment" and store the payment record on it.
    Only succeeds if the order is still in expected_from, so two admins cannot confirm twice."""
    async with _pool.acquire() as c:
        res = await c.execute(
            """UPDATE orders SET status=$3,
                 payment_detail = COALESCE(payment_detail,'{}'::jsonb) || $4::jsonb
               WHERE id=$1 AND status=$2""",
            order_id,
            expected_from,
            new_status,
            json.dumps(record),
        )
    return res.endswith(" 1")


async def get_favourites(email: str) -> list[str]:
    async with _pool.acquire() as c:
        rows = await c.fetch(
            "SELECT product_id FROM favourites WHERE email=$1 ORDER BY at DESC", email
        )
    return [r["product_id"] for r in rows]


async def add_favourite(email: str, product_id: str) -> None:
    async with _pool.acquire() as c:
        await c.execute(
            "INSERT INTO favourites (email,product_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
            email,
            product_id,
        )


async def remove_favourite(email: str, product_id: str) -> None:
    async with _pool.acquire() as c:
        await c.execute(
            "DELETE FROM favourites WHERE email=$1 AND product_id=$2", email, product_id
        )


async def popularity() -> dict[str, int]:
    """How many units of each product have been ordered (cancelled orders do not count)."""
    async with _pool.acquire() as c:
        rows = await c.fetch("SELECT items FROM orders WHERE status <> 'Cancelled'")
    out: dict[str, int] = {}
    for r in rows:
        items = json.loads(r["items"]) if isinstance(r["items"], str) else r["items"]
        for i in items:
            if i.get("productId"):
                out[i["productId"]] = out.get(i["productId"], 0) + int(i.get("qty", 0))
    return out


def _addr(r) -> dict:
    return {
        "id": r["id"],
        "label": r["label"],
        "area": r["area"],
        "address": r["address"],
        "phone": r["phone"],
        "isDefault": r["is_default"],
    }


async def list_addresses(email: str) -> list[dict]:
    async with _pool.acquire() as c:
        rows = await c.fetch(
            "SELECT * FROM addresses WHERE email=$1 ORDER BY is_default DESC, created", email
        )
    return [_addr(r) for r in rows]


async def save_address(email: str, a: dict) -> None:
    """Insert or replace one of this customer's addresses. Setting a default clears the others."""
    async with _pool.acquire() as c, c.transaction():
        if a["isDefault"]:
            await c.execute("UPDATE addresses SET is_default=FALSE WHERE email=$1", email)
        await c.execute(
            """INSERT INTO addresses (id,email,label,area,address,phone,is_default)
               VALUES ($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT (id) DO UPDATE SET label=$3, area=$4, address=$5, phone=$6, is_default=$7
               WHERE addresses.email=$2""",
            a["id"],
            email,
            a["label"],
            a["area"],
            a["address"],
            a["phone"],
            a["isDefault"],
        )


async def delete_address(email: str, address_id: str) -> bool:
    async with _pool.acquire() as c:
        res = await c.execute("DELETE FROM addresses WHERE id=$1 AND email=$2", address_id, email)
    return res.endswith(" 1")


async def update_profile(email: str, name: str, phone: str) -> None:
    async with _pool.acquire() as c:
        await c.execute("UPDATE users SET name=$2, phone=$3 WHERE email=$1", email, name, phone)


async def save_image(image_id: str, data: bytes) -> None:
    async with _pool.acquire() as c:
        await c.execute("INSERT INTO images (id, data) VALUES ($1, $2)", image_id, data)


async def get_image(image_id: str) -> bytes | None:
    async with _pool.acquire() as c:
        row = await c.fetchrow("SELECT data FROM images WHERE id=$1", image_id)
    return bytes(row["data"]) if row else None


def _rule(r) -> dict:
    v = r["rule"]
    return json.loads(v) if isinstance(v, str) else v


async def get_discount(code: str) -> dict | None:
    async with _pool.acquire() as c:
        r = await c.fetchrow("SELECT rule FROM discount_codes WHERE code=$1", code)
    return _rule(r) if r else None


async def list_discounts() -> list[dict]:
    async with _pool.acquire() as c:
        rows = await c.fetch(
            """SELECT d.rule, COUNT(u.id) AS used, COALESCE(SUM(u.amount),0) AS given
               FROM discount_codes d LEFT JOIN discount_uses u ON u.code = d.code
               GROUP BY d.code, d.rule, d.created ORDER BY d.created DESC"""
        )
    return [{**_rule(r), "used": r["used"], "given": int(r["given"])} for r in rows]


async def save_discount(rule: dict) -> None:
    async with _pool.acquire() as c:
        await c.execute(
            """INSERT INTO discount_codes (code, rule) VALUES ($1, $2::jsonb)
               ON CONFLICT (code) DO UPDATE SET rule = EXCLUDED.rule""",
            rule["code"],
            json.dumps(rule),
        )


async def discount_usage(code: str, email: str) -> tuple[int, bool]:
    """(times used by anyone, whether this customer has used it)."""
    async with _pool.acquire() as c:
        r = await c.fetchrow(
            "SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE email=$2) AS mine FROM discount_uses WHERE code=$1",
            code,
            email,
        )
    return r["n"], r["mine"] > 0


async def claim_discount(rule: dict, email: str, order_id: str, amount: int) -> bool:
    """Record a use only if the limits still hold. Returns False when the code ran out or this
    customer already used it.

    Claims for one code are serialised with a transaction-scoped advisory lock. Without it, two
    simultaneous orders would both check "has this customer used it?" before either was saved,
    both see "no", and a once-only code would be used twice.
    """
    async with _pool.acquire() as c, c.transaction():
        await c.execute("SELECT pg_advisory_xact_lock(hashtext($1))", "discount:" + rule["code"])
        res = await c.execute(
            """INSERT INTO discount_uses (code, email, order_id, amount)
               SELECT $1, $2, $3, $4
               WHERE ($5::int IS NULL OR (SELECT COUNT(*) FROM discount_uses WHERE code=$1) < $5::int)
                 AND (NOT $6::boolean OR NOT EXISTS (SELECT 1 FROM discount_uses WHERE code=$1 AND email=$2))""",
            rule["code"],
            email,
            order_id,
            amount,
            rule.get("maxUses"),
            bool(rule.get("perCustomerOnce")),
        )
    return res.endswith(" 1")


async def release_discount(order_id: str) -> None:
    """A cancelled order gives its use back."""
    async with _pool.acquire() as c:
        await c.execute("DELETE FROM discount_uses WHERE order_id=$1", order_id)


async def add_stock_move(m: dict) -> None:
    async with _pool.acquire() as c:
        await c.execute(
            "INSERT INTO stock_moves (product_id, change, after, reason, order_id, actor) VALUES ($1,$2,$3,$4,$5,$6)",
            m["productId"],
            m["change"],
            m.get("after"),
            m["reason"],
            m.get("orderId"),
            m["actor"],
        )


async def list_stock_moves(product_id: str | None, limit: int) -> list[dict]:
    async with _pool.acquire() as c:
        rows = await c.fetch(
            """SELECT m.*, p.name FROM stock_moves m LEFT JOIN products p ON p.id = m.product_id
               WHERE ($1::text IS NULL OR m.product_id = $1) ORDER BY m.at DESC, m.id DESC LIMIT $2""",
            product_id,
            limit,
        )
    return [
        {
            "productId": r["product_id"],
            "name": r["name"] or r["product_id"],
            "change": r["change"],
            "after": r["after"],
            "reason": r["reason"],
            "orderId": r["order_id"],
            "actor": r["actor"],
            "at": _iso(r["at"]),
        }
        for r in rows
    ]


# ---- product reviews ----
def _review(r) -> dict:
    return {
        "email": r["email"], "productId": r["product_id"], "name": r["name"],
        "rating": r["rating"], "body": r["body"], "hidden": r["hidden"],
        "created": r["created"].isoformat().replace("+00:00", "Z"),
        "updated": r["updated"].isoformat().replace("+00:00", "Z"),
    }  # fmt: skip


async def save_review(r: dict) -> None:
    async with _pool.acquire() as c:
        await c.execute(
            """INSERT INTO reviews (email,product_id,name,rating,body)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT (email,product_id) DO UPDATE
               SET name=EXCLUDED.name, rating=EXCLUDED.rating, body=EXCLUDED.body, updated=now()""",
            r["email"], r["productId"], r["name"], r["rating"], r["body"],
        )  # fmt: skip


async def list_reviews(product_id: str | None = None, include_hidden: bool = False) -> list[dict]:
    async with _pool.acquire() as c:
        rows = await c.fetch(
            """SELECT * FROM reviews
               WHERE ($1::text IS NULL OR product_id=$1) AND ($2 OR NOT hidden)
               ORDER BY updated DESC""",
            product_id, include_hidden,
        )  # fmt: skip
    return [_review(r) for r in rows]


async def get_review(email: str, product_id: str) -> dict | None:
    async with _pool.acquire() as c:
        r = await c.fetchrow(
            "SELECT * FROM reviews WHERE email=$1 AND product_id=$2", email, product_id
        )
    return _review(r) if r else None


async def set_review_hidden(email: str, product_id: str, hidden: bool) -> bool:
    async with _pool.acquire() as c:
        res = await c.execute(
            "UPDATE reviews SET hidden=$3 WHERE email=$1 AND product_id=$2",
            email,
            product_id,
            hidden,
        )
    return res.endswith(" 1")
