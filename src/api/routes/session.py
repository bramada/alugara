from fastapi import APIRouter
from src.drivers.stockbit_driver import StockbitDriver

router = APIRouter(prefix="/api/v1/session", tags=["Session Management"])
driver = StockbitDriver()

@router.get("/status")
async def get_session_status():
    valid, msg = await driver.check_session_valid()
    return {"is_authenticated": valid, "message": msg}
