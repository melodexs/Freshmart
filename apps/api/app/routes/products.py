from fastapi import APIRouter

from ..products import DELIVERY_FEE, PRODUCTS

router = APIRouter()


@router.get("")
@router.get("/")
async def list_products():
    return {"products": PRODUCTS, "deliveryFee": DELIVERY_FEE}
