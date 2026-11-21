"""The live product catalogue.

Products live in the database so the admin can change them. products.py is only the
starter list, copied in once when the database has no products at all. After that the
database is the truth, and a restart never overwrites an admin's edits.
"""

from __future__ import annotations

from . import db, products

DEFAULT_DELIVERY_FEE = products.DELIVERY_FEE


async def seed_if_empty() -> int:
    """Copy the starter products in, but only into an empty catalogue. Returns how many."""
    if await db.count_products() > 0:
        return 0
    for i, p in enumerate(products.PRODUCTS):
        await db.save_product({**p, "sort": i, "active": True, "stock": None})
    return len(products.PRODUCTS)


async def all_products(include_inactive: bool = False) -> list[dict]:
    return await db.list_products(include_inactive)


async def categories() -> list[str]:
    """Category names in the order products first use them, active products only."""
    return list(dict.fromkeys(p["cat"] for p in await db.list_products()))


async def find_option(product_id, option_index):
    """Same contract as products.find_option, but against the live catalogue.

    Inactive products cannot be bought. Returns (product, option) or None.
    """
    if not isinstance(product_id, str):
        return None
    product = await db.get_product(product_id)
    if product is None or not product.get("active", True):
        return None
    if not isinstance(option_index, int) or isinstance(option_index, bool):
        return None
    if option_index < 0 or option_index >= len(product["options"]):
        return None
    return product, product["options"][option_index]


async def delivery_fee() -> int:
    """The delivery fee the admin has set, or the default when none is set."""
    v = await db.get_setting("delivery_fee")
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else DEFAULT_DELIVERY_FEE


async def log_stock(
    product_id: str, change: int, after, reason: str, actor: str, order_id: str | None = None
) -> None:
    """Record why stock changed. A logging problem must never stop a sale or a cancellation."""
    if change == 0:
        return
    try:
        await db.add_stock_move(
            {
                "productId": product_id,
                "change": change,
                "after": after,
                "reason": reason,
                "orderId": order_id,
                "actor": actor,
            }
        )
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger("ogs").exception("could not record a stock movement")


async def restock_order(
    order: dict, reason: str = "Order cancelled", actor: str = "customer"
) -> None:
    """Put an order's items back on the shelf and give back its discount use.

    Every way an order can be cancelled goes through here.
    """
    for line in order.get("items", []):
        pid, qty = line.get("productId"), line.get("qty")
        if isinstance(pid, str) and isinstance(qty, int) and qty > 0:
            after = await db.adjust_stock(pid, qty)
            if after is not None:
                await log_stock(pid, qty, after, reason, actor, order.get("id"))
    if order.get("id"):
        await db.release_discount(order["id"])


async def bank_details() -> dict:
    """The store's real bank account, set by the admin. Empty until the owner enters it.

    Nothing here is ever invented: when the account is not set, checkout offers no transfer option.
    """
    d = await db.get_setting("bank_details")
    if not isinstance(d, dict):
        return {"bank": "", "accountName": "", "accountNumber": "", "ready": False}
    out = {k: str(d.get(k) or "") for k in ("bank", "accountName", "accountNumber")}
    out["ready"] = all(out.values())
    return out


DEFAULT_AREA = "Otukpo"


async def delivery_areas() -> list[dict]:
    """Areas the store delivers to, each with its own fee. Falls back to one area at the default fee.

    The admin edits this list. A fee here always wins over the browser: orders look the fee up
    by area name on the server.
    """
    raw = await db.get_setting("delivery_areas")
    areas = []
    if isinstance(raw, list):
        for a in raw:
            if not isinstance(a, dict):
                continue
            name = str(a.get("name") or "").strip()
            fee = a.get("fee")
            if name and isinstance(fee, int) and not isinstance(fee, bool) and fee >= 0:
                areas.append({"name": name, "fee": fee})
    if not areas:
        areas = [{"name": DEFAULT_AREA, "fee": await delivery_fee()}]
    return areas


async def fee_for_area(name) -> int | None:
    """The fee for a named area, or None when the store does not deliver there."""
    if not isinstance(name, str):
        return None
    for a in await delivery_areas():
        if a["name"].lower() == name.strip().lower():
            return a["fee"]
    return None


def from_price(p: dict) -> int:
    """The smallest size's price: the 'from' price shoppers see first."""
    return min(o["price"] for o in p["options"])


def discount_percent(p: dict, index: int = 0) -> int | None:
    """Whole-number percent off for a size, when the admin set an old price. Otherwise None."""
    was = (p.get("comparePrices") or [None] * len(p["options"]))[index : index + 1]
    was = was[0] if was else None
    now = p["options"][index]["price"]
    if isinstance(was, int) and was > now:
        return round((was - now) * 100 / was)
    return None


def on_offer(p: dict) -> bool:
    return any(discount_percent(p, i) for i in range(len(p["options"])))


def in_stock(p: dict) -> bool:
    return p.get("stock") is None or p["stock"] > 0


async def shelf(
    *,
    cat: str = "All",
    q: str = "",
    sort: str = "default",
    section: str = "",
    min_price: int | None = None,
    max_price: int | None = None,
    only_ids: list[str] | None = None,
    limit: int | None = None,
) -> list[dict]:
    """The one place that decides which products show, and in what order.

    section: "best" (most ordered), "new" (newest first), "offers" (discounted), "featured".
    Price filters compare against the 'from' price. Sold-out products sort last.
    """
    q_norm = q.strip().lower()[:60]
    items = []
    for p in await db.list_products():
        if cat != "All" and p["cat"] != cat:
            continue
        if q_norm and q_norm not in p["name"].lower() and q_norm not in p["cat"].lower():
            continue
        price = from_price(p)
        if min_price is not None and price < min_price:
            continue
        if max_price is not None and price > max_price:
            continue
        if only_ids is not None and p["id"] not in only_ids:
            continue
        if section == "offers" and not on_offer(p):
            continue
        if section == "featured" and not p.get("featured"):
            continue
        items.append(p)
    pop = await db.popularity() if (sort == "popular" or section == "best") else {}
    if section == "best":
        items = [p for p in items if pop.get(p["id"], 0) > 0]
        items.sort(key=lambda p: -pop[p["id"]])
    elif section == "new":
        items.sort(key=lambda p: -p.get("sort", 0))
    elif sort == "popular":
        items.sort(key=lambda p: (-pop.get(p["id"], 0), p.get("sort", 0)))
    elif sort == "price-asc":
        items.sort(key=from_price)
    elif sort == "price-desc":
        items.sort(key=from_price, reverse=True)
    elif sort == "name":
        items.sort(key=lambda p: p["name"].lower())
    items.sort(key=lambda p: not in_stock(p))  # stable: sold-out products go last
    return items[:limit] if limit else items


async def related(product: dict, limit: int = 4) -> list[dict]:
    """Other products from the same category, falling back to anything else."""
    same = [
        p
        for p in await db.list_products()
        if p["cat"] == product["cat"] and p["id"] != product["id"]
    ]
    return [p for p in same if in_stock(p)][:limit]
