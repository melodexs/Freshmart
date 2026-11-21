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
