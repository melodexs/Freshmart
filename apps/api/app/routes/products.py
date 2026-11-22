from fastapi import APIRouter

from .. import catalogue
from ..templating import photo_for

router = APIRouter()


def with_photo(products: list[dict]) -> list[dict]:
    """Copy each product and add the one picture URL every screen should use for it."""
    return [{**p, "photo": photo_for(p) or ""} for p in products]


@router.get("")
@router.get("/")
async def list_products():
    return {
        "products": with_photo(await catalogue.all_products()),
        "deliveryFee": await catalogue.delivery_fee(),
        "bank": await catalogue.bank_details(),
        "areas": await catalogue.delivery_areas(),
    }
