import os
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from src.config.settings import settings
from src.storage.db import (
    get_all_settings,
    set_setting,
    get_active_positions,
    get_trade_logs
)
from src.drivers.stockbit_driver import StockbitDriver
from src.core.execution_engine import ExecutionEngine
from src.notifier.telegram_notifier import TelegramNotifier

router = APIRouter(prefix="/api/v1/gui", tags=["Web GUI Dashboard"])
engine = ExecutionEngine()
notifier = TelegramNotifier()

class GuiSettingsPayload(BaseModel):
    trading_pin: Optional[str] = None
    capital_per_strategy: Optional[float] = None
    auto_execute_enabled: Optional[bool] = None
    telegram_enabled: Optional[bool] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    market_buy_hour: Optional[int] = None
    market_buy_minute: Optional[int] = None
    market_sell_hour: Optional[int] = None
    market_sell_minute: Optional[int] = None

@router.get("/status")
async def get_gui_dashboard_status():
    """
    Mengambil data status lengkap untuk Web Dashboard:
    - Status sesi login Stockbit
    - Statistik win rate & cuan internal
    - Posisi aktif saat ini
    - Sinyal screener hari ini
    - Konfigurasi aktif
    """
    # 1. Cek sesi
    valid, session_msg = await engine.driver.check_session_valid()

    # 2. Ambil data database
    positions = get_active_positions()
    logs = get_trade_logs(limit=20)
    db_settings = get_all_settings()

    # 3. Hitung Win Rate & Total PnL
    win_count = sum(1 for l in logs if l['status'] == 'WIN')
    loss_count = sum(1 for l in logs if l['status'] == 'LOSS')
    total_trades = len(logs)
    win_rate = round((win_count / total_trades * 100), 1) if total_trades > 0 else 0.0
    total_pnl = sum(l['net_profit'] for l in logs)

    # 4. Ambil sinyal screener real-time
    signals = await engine.screener.scan_market_signals()

    # 5. Format response
    return {
        "success": True,
        "session": {
            "is_authenticated": valid,
            "message": session_msg,
        },
        "stats": {
            "win_rate": win_rate,
            "win_count": win_count,
            "loss_count": loss_count,
            "total_trades": total_trades,
            "total_pnl": total_pnl,
            "active_positions_count": len(positions)
        },
        "active_positions": positions,
        "recent_trades": logs,
        "screener_signals": signals,
        "settings": {
            "trading_pin": "****" if db_settings.get("trading_pin") or settings.STOCKBIT_TRADING_PIN else "",
            "capital_per_strategy": float(db_settings.get("capital_per_strategy", settings.CAPITAL_PER_STRATEGY)),
            "auto_execute_enabled": db_settings.get("auto_execute_enabled", str(settings.AUTO_EXECUTE_ENABLED)).lower() == "true",
            "telegram_enabled": db_settings.get("telegram_enabled", str(settings.TELEGRAM_ENABLED)).lower() == "true",
            "telegram_bot_token": db_settings.get("telegram_bot_token", settings.TELEGRAM_BOT_TOKEN),
            "telegram_chat_id": db_settings.get("telegram_chat_id", settings.TELEGRAM_CHAT_ID),
            "market_buy_time": f"{settings.MARKET_BUY_HOUR:02d}:{settings.MARKET_BUY_MINUTE:02d} WIB",
            "market_sell_time": f"{settings.MARKET_SELL_HOUR:02d}:{settings.MARKET_SELL_MINUTE:02d} WIB",
        }
    }

@router.post("/settings")
async def update_gui_settings(payload: GuiSettingsPayload):
    """
    Menyimpan pengaturan Alugara langsung ke database internal (Tanpa .env)
    """
    if payload.trading_pin is not None and payload.trading_pin != "":
        set_setting("trading_pin", payload.trading_pin)
        settings.STOCKBIT_TRADING_PIN = payload.trading_pin

    if payload.capital_per_strategy is not None:
        set_setting("capital_per_strategy", str(payload.capital_per_strategy))
        settings.CAPITAL_PER_STRATEGY = payload.capital_per_strategy

    if payload.auto_execute_enabled is not None:
        set_setting("auto_execute_enabled", str(payload.auto_execute_enabled))
        settings.AUTO_EXECUTE_ENABLED = payload.auto_execute_enabled

    if payload.telegram_enabled is not None:
        set_setting("telegram_enabled", str(payload.telegram_enabled))
        settings.TELEGRAM_ENABLED = payload.telegram_enabled

    if payload.telegram_bot_token is not None:
        set_setting("telegram_bot_token", payload.telegram_bot_token)
        settings.TELEGRAM_BOT_TOKEN = payload.telegram_bot_token

    if payload.telegram_chat_id is not None:
        set_setting("telegram_chat_id", payload.telegram_chat_id)
        settings.TELEGRAM_CHAT_ID = payload.telegram_chat_id

    return {
        "success": True,
        "message": "Pengaturan Alugara berhasil disimpan ke database internal."
    }

@router.post("/trigger-login")
async def trigger_browser_login(background_tasks: BackgroundTasks):
    """
    Memicu pembukaan browser interaktif untuk login pairing
    """
    async def _run_login():
        driver = StockbitDriver(headless=False)
        await driver.interactive_login()

    background_tasks.add_task(_run_login)
    return {
        "success": True,
        "message": "Jendela browser Google Chrome sedang dibuka di server/laptop Anda. Silakan login ke Stockbit."
    }

@router.post("/trigger-buy")
async def trigger_manual_buy():
    """
    Memicu eksekusi Beli Sore (15:40 WIB) secara instan sekarang
    """
    await engine.run_afternoon_auto_buy()
    return {
        "success": True,
        "message": "Rutinitas eksekusi Beli Sore berhasil dijalankan."
    }

@router.post("/trigger-sell")
async def trigger_manual_sell():
    """
    Memicu eksekusi Jual Pagi (09:10 WIB) secara instan sekarang
    """
    await engine.run_morning_auto_sell()
    return {
        "success": True,
        "message": "Rutinitas evaluasi Jual Pagi berhasil dijalankan."
    }

@router.post("/test-telegram")
async def test_telegram_connection():
    """
    Uji coba koneksi Telegram Bot
    """
    res = await notifier.send_message(
        "🤖 <b>ALUGARA WEB GUI NOTIFIER TEST</b>\n\n"
        "Koneksi Telegram Bot dari Web Dashboard berhasil terhubung!"
    )
    return {
        "success": res,
        "message": "Pesan berhasil dikirim ke Telegram!" if res else "Gagal mengirim. Pastikan Token & Chat ID sudah benar."
    }
