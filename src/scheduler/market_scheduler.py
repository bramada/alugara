import pytz
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from src.config.settings import settings
from src.storage.db import get_setting

class MarketScheduler:
    """
    Penjadwal Eksekusi Otomatis Berdasarkan Jam Bursa BEI (WIB) - Full-Day Intraday
    Mengawal transaksi berkelanjutan sepanjang jam bursa buka.
    """
    def __init__(self, execution_engine=None):
        self.tz = pytz.timezone(settings.MARKET_TIMEZONE)
        self.scheduler = AsyncIOScheduler(timezone=self.tz)
        self.engine = execution_engine

    def is_auto_execute_active(self) -> bool:
        val = get_setting("auto_execute_enabled", str(settings.AUTO_EXECUTE_ENABLED))
        return str(val).strip().lower() == "true"

    def is_market_open(self, now_dt: datetime) -> bool:
        """
        Cek apakah saat ini dalam jam perdagangan resmi Bursa Efek Indonesia (IDX):
        - Senin - Kamis: Sesi 1 (09:00 - 12:00 WIB), Sesi 2 (13:30 - 15:55 WIB)
        - Jumat: Sesi 1 (09:00 - 11:30 WIB), Sesi 2 (14:00 - 15:55 WIB)
        """
        weekday = now_dt.weekday() # 0 = Senin, 4 = Jumat, 5 = Sabtu, 6 = Minggu
        if weekday >= 5:
            return False

        time_mins = now_dt.hour * 60 + now_dt.minute

        if weekday == 4: # Jumat
            sesi1 = (9 * 60 <= time_mins <= 11 * 60 + 30)
            sesi2 = (14 * 60 <= time_mins <= 15 * 60 + 55)
            return sesi1 or sesi2
        else: # Senin - Kamis
            sesi1 = (9 * 60 <= time_mins <= 12 * 60)
            sesi2 = (13 * 60 + 30 <= time_mins <= 15 * 60 + 55)
            return sesi1 or sesi2

    def start(self):
        # 1. Siklus Intraday Auto-Trade Berjalan Setiap 3 Menit selama jam kerja bursa (09:00 - 15:59 WIB, Senin-Jumat)
        self.scheduler.add_job(
            self.intraday_market_tick,
            CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/3", timezone=self.tz),
            id="intraday_tick_loop",
            name="Intraday Auto-Trade Scanner & Execution Loop",
            replace_existing=True
        )

        # 2. Pengecekan Kesiapan Akun Sebelum Pasar Buka (08:50 WIB, Senin-Jumat)
        self.scheduler.add_job(
            self.pre_market_health_check,
            CronTrigger(day_of_week="mon-fri", hour=8, minute=50, timezone=self.tz),
            id="pre_market_health_check",
            name="Pre-Market Session Check",
            replace_existing=True
        )

        self.scheduler.start()
        logger.info(f"MarketScheduler Alugara (Full-Day Intraday) aktif di timezone {settings.MARKET_TIMEZONE}.")

    def shutdown(self):
        self.scheduler.shutdown()
        logger.info("MarketScheduler Alugara dihentikan.")

    async def pre_market_health_check(self):
        logger.info("⏰ [08:50 WIB] Menjalankan Pre-Market Session Health Check...")
        if self.engine:
            valid, msg = await self.engine.driver.check_session_valid()
            if not valid:
                await self.engine.notifier.send_message(
                    f"⚠️ <b>PERINGATAN ALUGARA (08:50 WIB)</b>\n"
                    f"Sesi login Stockbit tidak aktif menjelang pembukaan pasar!\n"
                    f"Pesan: {msg}\nSilakan jalankan 'python cli.py login' segera."
                )

    async def intraday_market_tick(self):
        now = datetime.now(self.tz)
        if not self.is_market_open(now):
            return

        if not self.is_auto_execute_active():
            return

        logger.info(f"🔄 [{now.strftime('%H:%M:%S')} WIB] Menjalankan siklus Intraday Auto-Trade...")
        if self.engine:
            await self.engine.run_intraday_cycle(now)
