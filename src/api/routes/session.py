from fastapi import APIRouter, Depends
from src.drivers.stockbit_driver import StockbitDriver
from src.core.security import require_auth

router = APIRouter(prefix="/api/v1/session", tags=["Session Management"], dependencies=[Depends(require_auth)])
driver = StockbitDriver()

@router.get("/status")
async def get_session_status():
    valid, msg = await driver.check_session_valid()
    return {"is_authenticated": valid, "message": msg}