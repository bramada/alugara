import os
import httpx
from typing import Optional, Tuple
from loguru import logger
from src.config.settings import settings
from src.core.models import OrderResult

class TelegramNotifier:
    """
    Layanan Pengirim Notifikasi Telegram Bot (Dinamis dari SQLite & Enkripsi AES-256)
    """
    def __init__(self):
        pass

    def get_credentials(self) -> Tuple[bool, str, str]:
        from src.storage.db import get_setting
        from src.core.security import decrypt_value

        db_enabled = get_setting("telegram_enabled")
        enabled = (db_enabled.lower() == "true") if db_enabled else settings.TELEGRAM_ENABLED

        stored_token = get_setting("telegram_bot_token")
        bot_token = decrypt_value(stored_token) if stored_token else settings.TELEGRAM_BOT_TOKEN

        stored_chat = get_setting("telegram_chat_id")
        chat_id = decrypt_value(stored_chat) if stored_chat else settings.TELEGRAM_CHAT_ID

        return enabled, bot_token or "", chat_id or ""

    async def send_message(self, message: str, bot_token: Optional[str] = None, chat_id: Optional[str] = None) -> bool:
        enabled, default_token, default_chat = self.get_credentials()
        token = bot_token or default_token
        target_chat = chat_id or default_chat

        if not enabled and not bot_token:
            logger.debug("Notifikasi Telegram dinonaktifkan.")
            return False

        if not token or not target_chat:
            logger.warning("Kredensial Telegram belum lengkap (Token / Chat ID kosong).")
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": target_chat,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    logger.info("Notifikasi Telegram berhasil dikirim.")
                    return True
                else:
                    logger.error(f"Telegram send_message gagal ({res.status_code}): {res.text}")
                    return False
        except Exception as e:
            logger.error(f"Error mengirim Telegram: {e}")
            return False

    async def send_photo(self, photo_path: str, caption: str = "", bot_token: Optional[str] = None, chat_id: Optional[str] = None) -> bool:
        enabled, default_token, default_chat = self.get_credentials()
        token = bot_token or default_token
        target_chat = chat_id or default_chat

        if not enabled and not bot_token:
            return False

        if not token or not target_chat:
            return False

        if not os.path.exists(photo_path):
            logger.warning(f"Screenshot file not found for Telegram: {photo_path}")
            return await self.send_message(caption, token, target_chat)

        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                with open(photo_path, "rb") as f:
                    files = {"photo": f}
                    data = {"chat_id": target_chat, "caption": caption, "parse_mode": "HTML"}
                    res = await client.post(url, data=data, files=files)
                    if res.status_code == 200:
                        logger.info("Telegram photo berhasil dikirim.")
                        return True
                    else:
                        logger.error(f"Telegram send_photo gagal: {res.text}")
                        return False
        except Exception as e:
            logger.error(f"Error mengirim photo Telegram: {e}")
            return False

    async def notify_order_result(self, result: OrderResult, strategy_name: str = "Strategi Saham") -> bool:
        action_icon = "🟢 <b>BELI (BUY)</b>" if result.action == "BUY" else "🔴 <b>JUAL (SELL)</b>"
        status_icon = "✅ <b>BERHASIL DITERIMA BROKER</b>" if result.success else "❌ <b>GAGAL EKSEKUSI</b>"
        
        caption = (
            f"🤖 <b>ALUGARA AUTO-TRADING ENGINE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{action_icon} | Status: {status_icon}\n\n"
            f"• <b>Emiten:</b> #{result.ticker}\n"
            f"• <b>Strategi:</b> {strategy_name}\n"
            f"• <b>Harga:</b> Rp {result.price:,}\n"
            f"• <b>Volume:</b> {result.lots} Lot ({result.lots * 100:,} Lembar)\n"
            f"• <b>Total Nilai:</b> Rp {result.total_amount:,}\n"
            f"• <b>Waktu:</b> {result.executed_at.strftime('%d/%m/%Y %H:%M:%S WIB')}\n"
            f"• <b>Pesan:</b> {result.message}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Eksekusi otomatis tanpa intervensi manual.</i>"
        )

        if result.screenshot_path and os.path.exists(result.screenshot_path):
            return await self.send_photo(result.screenshot_path, caption)
        return await self.send_message(caption)
