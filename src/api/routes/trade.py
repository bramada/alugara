from fastapi import APIRouter, Depends
from typing import List, Dict, Any
from src.core.models import OrderRequest, OrderResult
from src.core.execution_engine import ExecutionEngine
from src.storage.db import get_active_positions, get_trade_logs
from src.core.security import require_auth

router = APIRouter(prefix="/api/v1/trade", tags=["Trading Execution"], dependencies=[Depends(require_auth)])
engine = ExecutionEngine()

@router.post("/execute-order", response_model=OrderResult)
async def execute_order(order: OrderRequest):
    """Mengeksekusi order Beli / Jual secara manual via API"""
    result = await engine.execute_single_order(order)
    return result

@router.get("/active-positions", response_model=List[Dict[str, Any]])
async def list_active_positions():
    """Daftar saham yang sedang aktif di-hold oleh Alugara"""
    return get_active_positions()

@router.get("/trade-history", response_model=List[Dict[str, Any]])
async def list_trade_history(limit: int = 50):
    """Riwayat transaksi yang sudah selesai dieksekusi oleh Alugara"""
    return get_trade_logs(limit=limit)