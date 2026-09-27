import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from src.config.settings import settings

class MarketScheduler:
    """
    Penjadwal Eksekusi Otomatis Berdasarkan Jam Bursa BEI (WIB) - 100% Standalone
    """
    def __init__(self, execution_engine=None):
        self.tz = pytz.timezone(settings.MARKET_TIMEZONE)
        self.scheduler = AsyncIOScheduler(timezone=self.tz)
        self.engine = execution_engine

    def start(self):
        # 1. Pre-Market Session Health Check (15:35 WIB, Senin-Jumat)
        self.scheduler.add_job(
            self.pre_market_health_check,
            CronTrigger(day_of_week="mon-fri", hour=15, minute=35, timezone=self.tz),
            id="pre_market_health_check",
            name="Pre-Market Session Check",
            replace_existing=True
        )

        # 2. Afternoon Auto-Buy Window (15:40 WIB, Senin-Jumat)
        self.scheduler.add_job(
            self.scheduled_buy_window,
            CronTrigger(day_of_week="mon-fri", hour=settings.MARKET_BUY_HOUR, minute=settings.MARKET_BUY_MINUTE, timezone=self.tz),
            id="market_buy_window",
            name="Afternoon Auto-Buy Window",
            replace_existing=True
        )

        # 3. Morning Auto-Sell Window (09:10 WIB, Senin-Jumat)
        self.scheduler.add_job(
            self.scheduled_sell_window,
            CronTrigger(day_of_week="mon-fri", hour=settings.MARKET_SELL_HOUR, minute=settings.MARKET_SELL_MINUTE, timezone=self.tz),
            id="market_sell_window",
            name="Morning Auto-Sell Window",
            replace_existing=True
        )

        self.scheduler.start()
        logger.info(f"MarketScheduler Alugara aktif di timezone {settings.MARKET_TIMEZONE}.")

    def shutdown(self):
        self.scheduler.shutdown()
        logger.info("MarketScheduler Alugara dihentikan.")

    async def pre_market_health_check(self):
        logger.info("⏰ [15:35 WIB] Menjalankan Pre-Market Session Health Check...")
        if self.engine:
            valid, msg = await self.engine.driver.check_session_valid()
            if not valid:
                await self.engine.notifier.send_message(
                    f"⚠️ <b>PERINGATAN ALUGARA (15:35 WIB)</b>\n"
                    f"Sesi login Stockbit tidak aktif menjelang jam beli!\n"
                    f"Pesan: {msg}\nSilakan jalankan 'python cli.py login' segera."
                )

    async def scheduled_buy_window(self):
        logger.info(f"🚀 [{settings.MARKET_BUY_HOUR}:{settings.MARKET_BUY_MINUTE} WIB] Jendela Beli Sore Dimulai!")
        if not settings.AUTO_EXECUTE_ENABLED:
            logger.info("Auto execute sedang dinonaktifkan di .env.")
            return
        if self.engine:
            await self.engine.run_afternoon_auto_buy()

    async def scheduled_sell_window(self):
        logger.info(f"🎯 [{settings.MARKET_SELL_HOUR}:{settings.MARKET_SELL_MINUTE} WIB] Jendela Jual Pagi Dimulai!")
        if not settings.AUTO_EXECUTE_ENABLED:
            logger.info("Auto execute sedang dinonaktifkan di .env.")
            return
        if self.engine:
            await self.engine.run_morning_auto_sell()
