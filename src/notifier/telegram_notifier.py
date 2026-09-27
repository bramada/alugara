import os
import httpx
from loguru import logger
from src.config.settings import settings
from src.core.models import OrderResult

class TelegramNotifier:
    """
    Layanan Pengirim Notifikasi Telegram Bot
    """
    def __init__(self):
        self.enabled = settings.TELEGRAM_ENABLED
        self.bot_token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID

    async def send_message(self, message: str) -> bool:
        if not self.enabled or not self.bot_token or not self.chat_id:
            logger.debug("Telegram notifications disabled or credentials missing.")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    logger.info("Telegram message sent successfully.")
                    return True
                else:
                    logger.error(f"Telegram send_message failed: {res.text}")
                    return False
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")
            return False

    async def send_photo(self, photo_path: str, caption: str = "") -> bool:
        if not self.enabled or not self.bot_token or not self.chat_id:
            return False

        if not os.path.exists(photo_path):
            logger.warning(f"Screenshot file not found for Telegram: {photo_path}")
            return await self.send_message(caption)

        url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                with open(photo_path, "rb") as f:
                    files = {"photo": f}
                    data = {"chat_id": self.chat_id, "caption": caption, "parse_mode": "HTML"}
                    res = await client.post(url, data=data, files=files)
                    if res.status_code == 200:
                        logger.info("Telegram photo sent successfully.")
                        return True
                    else:
                        logger.error(f"Telegram send_photo failed: {res.text}")
                        return False
        except Exception as e:
            logger.error(f"Error sending Telegram photo: {e}")
            return False

    async def notify_order_result(self, result: OrderResult, strategy_name: str = "Strategi Kuantitatif") -> bool:
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
