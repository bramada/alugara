# -*- coding: utf-8 -*-
import httpx
import os
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel
from src.config.settings import settings
from src.storage.db import (
    get_all_settings,
    delete_ai_memory,
    save_discuss_message,
    get_discuss_history,
    clear_discuss_history,
    get_ai_quota_stats,
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

# Cache untuk respon instan dashboard (< 20ms)
_cached_session_status = {"valid": False, "msg": "Menunggu pengecekan sesi", "checked_at": None}
_cached_signals: List[Dict[str, Any]] = []

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
async def get_gui_dashboard_status(background_tasks: BackgroundTasks):
    """
    Mengambil data status lengkap untuk Web Dashboard Alugara (Respons Cepat & Instan)
    """
    global _cached_session_status, _cached_signals

    # Cek session cache (refresh di background jika sudah > 3 menit)
    now = datetime.now(timezone.utc)
    if _cached_session_status["checked_at"] is None or (now - _cached_session_status["checked_at"]).total_seconds() > 180:
        async def _check_sess_bg():
            global _cached_session_status
            try:
                v, m = await engine.driver.check_session_valid()
                _cached_session_status = {"valid": v, "msg": m, "checked_at": datetime.now(timezone.utc)}
            except Exception as e:
                _cached_session_status = {"valid": False, "msg": str(e), "checked_at": datetime.now(timezone.utc)}
        background_tasks.add_task(_check_sess_bg)

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

    # Ambil sinyal terakhir dari engine
    signals = getattr(engine, "last_signals", None) or _cached_signals or []

    # Cek ketersediaan secret terenkripsi
    stored_pin = decrypt_value(db_settings.get("trading_pin", "")) or settings.STOCKBIT_TRADING_PIN
    stored_gemini = decrypt_value(db_settings.get("gemini_api_key", "")) or settings.GEMINI_API_KEY
    stored_tele_token = decrypt_value(db_settings.get("telegram_bot_token", "")) or settings.TELEGRAM_BOT_TOKEN
    stored_tele_chat_id = decrypt_value(db_settings.get("telegram_chat_id", "")) or settings.TELEGRAM_CHAT_ID


    return {
        "success": True,
        "session": {
            "is_authenticated": _cached_session_status["valid"],
            "message": _cached_session_status["msg"],
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
            "gemini_api_key": stored_gemini or "",
            "gemini_model": db_settings.get("gemini_model", settings.GEMINI_MODEL),
            "ai_reasoning_enabled": db_settings.get("ai_reasoning_enabled", str(settings.AI_REASONING_ENABLED)).lower() == "true",
            "capital_per_strategy": float(db_settings.get("capital_per_strategy", settings.CAPITAL_PER_STRATEGY)),
            "auto_execute_enabled": db_settings.get("auto_execute_enabled", str(settings.AUTO_EXECUTE_ENABLED)).lower() == "true",
            "telegram_enabled": db_settings.get("telegram_enabled", str(settings.TELEGRAM_ENABLED)).lower() == "true",
            "telegram_bot_token": stored_tele_token or "",
            "telegram_chat_id": stored_tele_chat_id or "",
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

    if payload.telegram_chat_id is not None and payload.telegram_chat_id != "" and payload.telegram_chat_id != "****":
        set_setting("telegram_chat_id", encrypt_value(payload.telegram_chat_id))
        settings.TELEGRAM_CHAT_ID = payload.telegram_chat_id

    return {
        "success": True,
        "message": "Pengaturan Alugara & Gemini AI berhasil diamankan & disimpan ke database internal!"
    }

class TestGeminiPayload(BaseModel):
    api_key: Optional[str] = None
    model: Optional[str] = None

@router.post("/test-gemini")
async def test_gemini_api(payload: Optional[TestGeminiPayload] = None):
    """Uji coba koneksi ke Gemini API"""
    key_input = payload.api_key.strip() if payload and payload.api_key and payload.api_key != "****" else None
    model_input = payload.model.strip() if payload and payload.model else None

    # Jika user menginput nilai baru, simpan langsung ke database internal (terenkripsi)
    if key_input:
        set_setting("gemini_api_key", encrypt_value(key_input))
        settings.GEMINI_API_KEY = key_input
    if model_input:
        set_setting("gemini_model", model_input)
        settings.GEMINI_MODEL = model_input

    active_key = key_input or ai_analyzer.get_api_key()
    active_model = model_input or ai_analyzer.get_model()

    if not active_key:
        return {"success": False, "message": "Gemini API Key belum diisi. Silakan masukkan API Key terlebih dahulu."}

    success, message = await ai_analyzer.test_connection(api_key=active_key, model=active_model)
    return {"success": success, "message": message}

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

class TestTelegramPayload(BaseModel):
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None

@router.post("/test-telegram")
async def test_telegram_connection(payload: Optional[TestTelegramPayload] = None):
    token_input = payload.bot_token.strip() if payload and payload.bot_token and payload.bot_token != "****" else None
    chat_input = payload.chat_id.strip() if payload and payload.chat_id and payload.chat_id != "****" else None

    if token_input:
        set_setting("telegram_bot_token", encrypt_value(token_input))
        settings.TELEGRAM_BOT_TOKEN = token_input
    if chat_input:
        set_setting("telegram_chat_id", encrypt_value(chat_input))
        settings.TELEGRAM_CHAT_ID = chat_input
    set_setting("telegram_enabled", "True")
    settings.TELEGRAM_ENABLED = True

    enabled, token, chat = notifier.get_credentials()
    active_token = token_input or token
    active_chat = chat_input or chat

    if not active_token or not active_chat:
        return {
            "success": False,
            "message": "Token atau Chat ID belum terisi. Harap masukkan Bot Token dan Chat ID!"
        }

    url = f"https://api.telegram.org/bot{active_token}/sendMessage"
    payload_data = {
        "chat_id": active_chat,
        "text": "<b>ALUGARA TELEGRAM NOTIFIER TEST</b>\n\nKoneksi Telegram Bot berhasil terhubung ke Channel/Group!",
        "parse_mode": "HTML"
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(url, json=payload_data)
            if res.status_code == 200:
                return {"success": True, "message": "[OK] Pesan uji coba berhasil terkirim ke Telegram!"}
            else:
                data = res.json()
                err_desc = data.get("description", res.text)
                return {"success": False, "message": f"[ERROR] Gagal mengirim ke Telegram: {err_desc}"}
    except Exception as e:
        return {"success": False, "message": f"[ERROR] Error koneksi: {e}"}


class DiscussPayload(BaseModel):
    message: str
    time: Optional[str] = None
    history: Optional[List[Dict[str, str]]] = None

@router.get("/discuss/history")
async def get_chat_history():
    """Mengambil seluruh riwayat percakapan Discuss yang tersimpan di database SQLite"""
    messages = get_discuss_history(limit=150)
    return {"success": True, "messages": messages}

@router.delete("/discuss/history")
async def clear_chat_history_db():
    """Menghapus seluruh riwayat percakapan Discuss dari database SQLite"""
    clear_discuss_history()
    return {"success": True, "message": "Riwayat percakapan berhasil dibersihkan dari database."}

@router.post("/discuss")
async def discuss_with_ai(payload: DiscussPayload):
    """
    Endpoint interaktif Menu Discuss:
    - Pesan dengan awalan 'evo:' akan mengajari AI dan menyimpan aturan ke Buku Pintar AI
    - Pesan biasa menjadi sesi tanya jawab konsultasi trading
    - Seluruh percakapan otomatis tersimpan permanen ke SQLite (cross-browser sync)
    """
    if not payload.message or not payload.message.strip():
        raise HTTPException(status_code=400, detail="Pesan tidak boleh kosong.")
    
    # User message timestamp (WIB)
    now_jkt = datetime.now(timezone(timedelta(hours=7)))
    user_time_str = payload.time or now_jkt.strftime("%H:%M WIB")
    is_evo = payload.message.strip().lower().startswith("evo:")

    # Save user message to DB
    save_discuss_message(
        role="user",
        content=payload.message.strip(),
        is_evo=is_evo,
        time_str=user_time_str
    )

    result = await ai_analyzer.discuss_and_evolve(
        user_message=payload.message,
        chat_history=payload.history
    )

    # AI reply timestamp (WIB)
    ai_now_jkt = datetime.now(timezone(timedelta(hours=7)))
    ai_time_str = ai_now_jkt.strftime("%H:%M WIB")

    # Save AI reply to DB
    save_discuss_message(
        role="assistant",
        content=result.get("reply", ""),
        is_evo=False,
        is_evolved=result.get("is_evolved", False),
        evolved_data=result.get("evolved_data"),
        time_str=ai_time_str
    )

    return result

@router.delete("/memories/{memory_id}")
async def remove_ai_memory(memory_id: int):
    """Menghapus memori tertentu dari Buku Pintar AI"""
    delete_ai_memory(memory_id)
    return {"success": True, "message": "Memori berhasil dihapus dari Buku Pintar AI."}
