import os
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel
from src.config.settings import settings
from src.storage.db import (
    get_all_settings,
    set_setting,
    get_active_positions,
    get_trade_logs,
    get_top_ai_memories
)
from src.drivers.stockbit_driver import StockbitDriver
from src.core.execution_engine import ExecutionEngine
from src.notifier.telegram_notifier import TelegramNotifier
from src.ai.gemini_analyzer import GeminiAnalyzer
from src.core.security import require_auth, encrypt_value, decrypt_value

router = APIRouter(prefix="/api/v1/gui", tags=["Web GUI Dashboard"], dependencies=[Depends(require_auth)])
engine = ExecutionEngine()
notifier = TelegramNotifier()
ai_analyzer = GeminiAnalyzer()

class GuiSettingsPayload(BaseModel):
    trading_pin: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    ai_reasoning_enabled: Optional[bool] = None
    capital_per_strategy: Optional[float] = None
    auto_execute_enabled: Optional[bool] = None
    telegram_enabled: Optional[bool] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

@router.get("/status")
async def get_gui_dashboard_status():
    """
    Mengambil data status lengkap untuk Web Dashboard Alugara (Terproteksi Login Gate)
    """
    valid, session_msg = await engine.driver.check_session_valid()
    positions = get_active_positions()
    logs = get_trade_logs(limit=20)
    ai_memories = get_top_ai_memories(limit=15)
    db_settings = get_all_settings()

    # 5 Metrik Utama Portofolio: Modal, Valuasi, Persentase P/L, Nominal P/L, Winrate
    modal = float(db_settings.get("capital_per_strategy", settings.CAPITAL_PER_STRATEGY))
    unrealized_pnl = sum((p.get('current_price', p['entry_price']) - p['entry_price']) * p['lots'] * 100 for p in positions)
    realized_pnl = sum(l['net_profit'] for l in logs)
    total_pnl = round(realized_pnl + unrealized_pnl, 2)
    valuasi = round(modal + total_pnl, 2)
    pnl_percent = round((total_pnl / modal * 100), 2) if modal > 0 else 0.0

    win_count = sum(1 for l in logs if l['status'] == 'WIN')
    loss_count = sum(1 for l in logs if l['status'] == 'LOSS')
    total_trades = len(logs)
    win_rate = round((win_count / total_trades * 100), 1) if total_trades > 0 else 0.0

    # Ambil sinyal screener real-time
    raw_signals = await engine.screener.scan_market_signals()
    # Jika AI aktif, saring dan beri skor
    signals = await ai_analyzer.analyze_and_rank_candidates(raw_signals)

    # Cek ketersediaan secret terenkripsi
    stored_pin = decrypt_value(db_settings.get("trading_pin", "")) or settings.STOCKBIT_TRADING_PIN
    stored_gemini = decrypt_value(db_settings.get("gemini_api_key", "")) or settings.GEMINI_API_KEY
    stored_tele_token = decrypt_value(db_settings.get("telegram_bot_token", "")) or settings.TELEGRAM_BOT_TOKEN

    return {
        "success": True,
        "session": {
            "is_authenticated": valid,
            "message": session_msg,
        },
        "stats": {
            "modal": modal,
            "valuasi": valuasi,
            "pnl_nominal": total_pnl,
            "pnl_percent": pnl_percent,
            "win_rate": win_rate,
            "win_count": win_count,
            "loss_count": loss_count,
            "total_trades": total_trades,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "active_positions_count": len(positions)
        },
        "active_positions": positions,
        "recent_trades": logs,
        "ai_memories": ai_memories,
        "screener_signals": signals,
        "settings": {
            "trading_pin": "****" if stored_pin else "",
            "gemini_api_key": "****" if stored_gemini else "",
            "gemini_model": db_settings.get("gemini_model", settings.GEMINI_MODEL),
            "ai_reasoning_enabled": db_settings.get("ai_reasoning_enabled", str(settings.AI_REASONING_ENABLED)).lower() == "true",
            "capital_per_strategy": float(db_settings.get("capital_per_strategy", settings.CAPITAL_PER_STRATEGY)),
            "auto_execute_enabled": db_settings.get("auto_execute_enabled", str(settings.AUTO_EXECUTE_ENABLED)).lower() == "true",
            "telegram_enabled": db_settings.get("telegram_enabled", str(settings.TELEGRAM_ENABLED)).lower() == "true",
            "telegram_bot_token": "****" if stored_tele_token else "",
            "telegram_chat_id": db_settings.get("telegram_chat_id", settings.TELEGRAM_CHAT_ID),
            "market_buy_time": "09:00 - 15:45 WIB (Intraday Multi-Trade)",
            "market_sell_time": "Real-Time TP/SL (+1.5% s/d +3.5%)",
        }
    }

@router.post("/settings")
async def update_gui_settings(payload: GuiSettingsPayload):
    """
    Menyimpan pengaturan Alugara & Gemini API dengan enkripsi AES-256 langsung ke database SQLite internal
    """
    if payload.trading_pin is not None and payload.trading_pin != "":
        set_setting("trading_pin", encrypt_value(payload.trading_pin))
        settings.STOCKBIT_TRADING_PIN = payload.trading_pin

    if payload.gemini_api_key is not None and payload.gemini_api_key != "":
        set_setting("gemini_api_key", encrypt_value(payload.gemini_api_key))
        settings.GEMINI_API_KEY = payload.gemini_api_key

    if payload.gemini_model is not None:
        set_setting("gemini_model", payload.gemini_model)
        settings.GEMINI_MODEL = payload.gemini_model

    if payload.ai_reasoning_enabled is not None:
        set_setting("ai_reasoning_enabled", str(payload.ai_reasoning_enabled))
        settings.AI_REASONING_ENABLED = payload.ai_reasoning_enabled

    if payload.capital_per_strategy is not None:
        set_setting("capital_per_strategy", str(payload.capital_per_strategy))
        settings.CAPITAL_PER_STRATEGY = payload.capital_per_strategy

    if payload.auto_execute_enabled is not None:
        set_setting("auto_execute_enabled", str(payload.auto_execute_enabled))
        settings.AUTO_EXECUTE_ENABLED = payload.auto_execute_enabled

    if payload.telegram_enabled is not None:
        set_setting("telegram_enabled", str(payload.telegram_enabled))
        settings.TELEGRAM_ENABLED = payload.telegram_enabled

    if payload.telegram_bot_token is not None and payload.telegram_bot_token != "":
        set_setting("telegram_bot_token", encrypt_value(payload.telegram_bot_token))
        settings.TELEGRAM_BOT_TOKEN = payload.telegram_bot_token

    if payload.telegram_chat_id is not None:
        set_setting("telegram_chat_id", payload.telegram_chat_id)
        settings.TELEGRAM_CHAT_ID = payload.telegram_chat_id

    return {
        "success": True,
        "message": "Pengaturan Alugara & Gemini AI berhasil diamankan & disimpan ke database internal!"
    }

@router.post("/test-gemini")
async def test_gemini_api():
    """Uji coba koneksi ke Gemini API"""
    res = await ai_analyzer.call_gemini("Halo Gemini, jawab singkat: 'Koneksi Gemini AI ke Alugara berhasil!'")
    if res:
        return {"success": True, "message": res.strip()}
    return {"success": False, "message": "Gagal terhubung ke Gemini API. Pastikan API Key valid."}

@router.post("/trigger-login")
async def trigger_browser_login(background_tasks: BackgroundTasks):
    async def _run_login():
        driver = StockbitDriver(headless=False)
        await driver.interactive_login()

    background_tasks.add_task(_run_login)
    return {
        "success": True,
        "message": "Jendela Google Chrome sedang dibuka. Silakan login ke Stockbit."
    }

@router.post("/trigger-buy")
async def trigger_manual_buy():
    await engine.run_intraday_cycle(force_scan=True)
    return {"success": True, "message": "Siklus Intraday Scan & Trade berhasil dieksekusi."}

@router.post("/trigger-sell")
async def trigger_manual_sell():
    await engine.run_morning_auto_sell()
    return {"success": True, "message": "Rutinitas evaluasi Jual Pagi berhasil dijalankan."}

@router.post("/test-telegram")
async def test_telegram_connection():
    res = await notifier.send_message("🚀 <b>ALUGARA TELEGRAM NOTIFIER TEST</b>\n\nKoneksi Telegram Bot berhasil terhubung!")
    return {"success": res, "message": "Pesan berhasil dikirim ke Telegram!" if res else "Gagal mengirim. Cek Token & Chat ID."}