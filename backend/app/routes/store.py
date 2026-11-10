from fastapi import APIRouter, Depends

from .. import auth, db

router = APIRouter()


@router.get("/notifications", dependencies=[Depends(auth.require_staff)])
async def notifications():
    # Contains customer addresses and phone numbers, so it is staff-only
    # (X-Staff-Key header) in production, unlike the open demo version.
    return {"notifications": await db.get_store_sms()}
