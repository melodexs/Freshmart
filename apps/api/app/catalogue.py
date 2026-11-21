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


async def restock_order(order: dict) -> None:
    """Put an order's items back on the shelf (used by every way an order can be cancelled)."""
    for line in order.get("items", []):
        pid, qty = line.get("productId"), line.get("qty")
        if isinstance(pid, str) and isinstance(qty, int) and qty > 0:
            await db.adjust_stock(pid, qty)


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
