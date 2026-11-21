from fastapi import APIRouter

from .. import catalogue

router = APIRouter()


@router.get("")
@router.get("/")
async def list_products():
    return {
        "products": await catalogue.all_products(),
        "deliveryFee": await catalogue.delivery_fee(),
    }
