import json
import os
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from loguru import logger
from playwright.async_api import async_playwright, BrowserContext, Page
from src.config.settings import settings
from src.core.models import OrderResult
from src.storage.db import get_setting, set_setting
from src.core.security import (
    encrypt_value,
    decrypt_value,
    create_session_export_package,
    decrypt_session_export_package
)

class StockbitDriver:
    """
    Driver Otomasi Stockbit Web menggunakan Playwright Stealth Engine
    """
    def __init__(self, session_dir: Optional[str] = None, headless: Optional[bool] = None):
        self.session_dir = os.path.abspath(session_dir or settings.STOCKBIT_SESSION_DIR)
        self.state_file = os.path.join(self.session_dir, "stockbit_state.json")
        self.profile_dir = os.path.join(self.session_dir, "browser_profile")
        self.headless = settings.HEADLESS_MODE if headless is None else headless
        self.timeout_ms = settings.BROWSER_TIMEOUT_MS
        os.makedirs(self.session_dir, exist_ok=True)
        os.makedirs(self.profile_dir, exist_ok=True)
        os.makedirs("screenshots", exist_ok=True)

    async def get_context(self, p, headless: Optional[bool] = None) -> BrowserContext:
        """
        Membuka persistent browser context dengan cookie & session yang tersimpan
        """
        is_headless = self.headless if headless is None else headless
        user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )

        context = await p.chromium.launch_persistent_context(
            user_data_dir=self.profile_dir,
            headless=is_headless,
            user_agent=user_agent,
            viewport={"width": 1366, "height": 768},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ]
        )

        # Apply stealth scripts to disguise automation flags
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', { get: () => ['id-ID', 'id', 'en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)

        # Muat otomatis cookie dari stockbit_state.json jika file sesi tersedia
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as sf:
                    state_data = json.load(sf)
                    cookies = state_data.get("cookies", [])
                    if cookies:
                        await context.add_cookies(cookies)
                        logger.debug(f"Berhasil memuat {len(cookies)} cookies dari {self.state_file}")
            except Exception as e:
                logger.warning(f"Gagal memuat cookies dari {self.state_file}: {e}")

        return context

    async def check_session_valid(self) -> Tuple[bool, str]:
        """
        Memeriksa apakah sesi login Stockbit saat ini masih aktif dan valid
        """
        # 1. Cek apakah file sesi stockbit_state.json sudah ada, jika belum coba pulihkan dari DB
        if not os.path.exists(self.state_file):
            enc_db = get_setting("stockbit_encrypted_session")
            if enc_db:
                try:
                    raw_state = decrypt_value(enc_db)
                    if raw_state and "cookies" in raw_state:
                        with open(self.state_file, "w", encoding="utf-8") as sf:
                            sf.write(raw_state)
                        logger.info("Berhasil memulihkan session state Stockbit dari database!")
                except Exception as ex:
                    logger.warning(f"Gagal memulihkan sesi dari DB: {ex}")

        if not os.path.exists(self.state_file):
            return False, "Belum login. Silakan hubungkan akun via browser atau impor sesi."

        try:
            with open(self.state_file, "r", encoding="utf-8") as sf:
                state_data = json.load(sf)
                cookies = state_data.get("cookies", [])
                if not cookies:
                    return False, "File sesi kosong. Silakan login atau impor ulang."
        except Exception:
            return False, "File sesi tidak valid. Silakan login atau impor ulang."

        # 2. Buka browser dan verifikasi login nyata di Stockbit
        async with async_playwright() as p:
            context = await self.get_context(p, headless=True)
            page = await context.new_page()
            try:
                logger.info("Memeriksa status sesi login Stockbit di web...")
                await page.goto("https://stockbit.com/#/order", timeout=self.timeout_ms, wait_until="domcontentloaded")
                await asyncio.sleep(2.5)

                current_url = page.url
                if "login" in current_url.lower() or "signin" in current_url.lower():
                    await context.close()
                    return False, "Sesi login kedaluwarsa. Silakan login atau impor ulang sesi."

                # Cek elemen profil user terautentikasi
                is_logged_in = await page.evaluate("""
                    () => {
                        const avatar = document.querySelector('[data-testid="user-avatar"]') || 
                                       document.querySelector('.header-avatar') ||
                                       document.querySelector('a[href*="/portfolio"]') ||
                                       document.querySelector('button[aria-label*="Account"]') ||
                                       document.querySelector('.user-profile-name');
                        return !!avatar;
                    }
                """)

                await context.close()
                if is_logged_in:
                    return True, "Sesi login Stockbit aktif & siap eksekusi."
                return False, "Belum terautentikasi di Stockbit. Silakan hubungkan akun."
            except Exception as e:
                await context.close()
                logger.error(f"Error checking session: {e}")
                return False, f"Gagal mengecek sesi: {str(e)}"

    def export_session_package(self, passphrase: Optional[str] = None) -> Tuple[bool, Optional[dict], str]:
        """
        Mengekspor sesi Stockbit saat ini ke dalam paket terenkripsi AES-256.
        Mencoba membaca dari sessions/stockbit_state.json atau fallback dari database.
        """
        raw_json = None
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    raw_json = f.read()
            except Exception as e:
                logger.error(f"Gagal membaca file sesi: {e}")

        if not raw_json:
            enc_db = get_setting("stockbit_encrypted_session")
            if enc_db:
                raw_json = decrypt_value(enc_db)

        if not raw_json:
            return False, None, "Tidak ada data sesi Stockbit aktif yang ditemukan. Silakan login terlebih dahulu."

        try:
            parsed = json.loads(raw_json)
            cookies = parsed.get("cookies", [])
            if not cookies:
                return False, None, "Data sesi kosong (tidak mengandung cookies)."

            package = create_session_export_package(raw_json, passphrase=passphrase)
            return True, package, f"Sesi Stockbit ({len(cookies)} cookies) berhasil diekspor."
        except Exception as e:
            return False, None, f"Gagal mengekspor sesi: {str(e)}"

    def import_session_package(self, package_data: dict, passphrase: Optional[str] = None) -> Tuple[bool, str]:
        """
        Mengimpor paket sesi terenkripsi, mendekripsi, memvalidasi cookies,
        lalu menyimpan ke sessions/stockbit_state.json dan mencadangkan ke database.
        """
        try:
            raw_json = decrypt_session_export_package(package_data, passphrase=passphrase)
            parsed = json.loads(raw_json)
            cookies = parsed.get("cookies", [])
            if not cookies:
                return False, "Sesi yang didekripsi tidak mengandung cookies autentikasi yang valid."

            # Tulis ke file sessions/stockbit_state.json
            with open(self.state_file, "w", encoding="utf-8") as f:
                f.write(raw_json)

            # Cadangkan terenkripsi ke database
            set_setting("stockbit_encrypted_session", encrypt_value(raw_json))
            logger.info(f"Berhasil mengimpor sesi Stockbit dengan {len(cookies)} cookies!")
            return True, f"Sesi Stockbit berhasil dipasang ({len(cookies)} cookies aktif) & dicadangkan ke database."
        except Exception as e:
            logger.error(f"Gagal mengimpor sesi: {e}")
            return False, str(e)

    async def interactive_login(self):
        """
        Membuka browser interaktif (GUI) agar pengguna dapat login 1x dan input OTP.
        Sesi akan otomatis disimpan secara permanen di sessions/ dan dicadangkan ke DB.
        """
        logger.info("Membuka browser untuk Interactive Login Stockbit...")
        print("\n========================================================")
        print("  ALUGARA INTERACTIVE LOGIN PAIRING")
        print("========================================================")
        print("1. Browser akan terbuka di layar Anda.")
        print("2. Silakan login ke akun Stockbit Anda (termasuk isi OTP jika diminta).")
        print("3. Setelah berhasil masuk ke Dashboard Stockbit, kembali ke terminal ini.")
        print("========================================================\n")

        async with async_playwright() as p:
            context = await self.get_context(p, headless=False)
            page = await context.new_page()
            await page.goto("https://stockbit.com/login", timeout=60000)

            # Wait until user logs in and reaches main dashboard or order page
            print("Menunggu login berhasil...")
            for _ in range(120): # Maksimal 4 menit
                await asyncio.sleep(2)
                current_url = page.url
                if "login" not in current_url.lower() and "signin" not in current_url.lower():
                    # Check if storage state can be captured
                    await asyncio.sleep(3)
                    await context.storage_state(path=self.state_file)
                    
                    # Simpan juga cadangan sesi terenkripsi ke database
                    try:
                        with open(self.state_file, "r", encoding="utf-8") as sf:
                            raw_state = sf.read()
                            set_setting("stockbit_encrypted_session", encrypt_value(raw_state))
                            logger.info("Berhasil mencadangkan sesi Stockbit terenkripsi ke database!")
                    except Exception as ex:
                        logger.warning(f"Gagal mencadangkan sesi ke DB: {ex}")

                    logger.info("Berhasil menyimpan session state Stockbit!")
                    print("\n✅ LOGIN BERHASIL! Sesi telah disimpan di sessions/stockbit_state.json dan database.")
                    await context.close()
                    return True

            logger.warning("Timeout menunggu interaksi login pengguna.")
            await context.close()
            return False

    async def place_order(
        self,
        ticker: str,
        action: str,
        price: int,
        lots: int,
        trading_pin: Optional[str] = None,
        strategy_name: str = "Strategi Kuantitatif"
    ) -> OrderResult:
        """
        Mengeksekusi order Beli (BUY) atau Jual (SELL) di Stockbit Web
        """
        clean_ticker = ticker.upper().replace(".JK", "").strip()
        pin = trading_pin or settings.STOCKBIT_TRADING_PIN
        total_amount = price * lots * 100
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_path = os.path.abspath(f"screenshots/{action.lower()}_{clean_ticker}_{timestamp_str}.png")

        if not pin:
            return OrderResult(
                success=False,
                ticker=clean_ticker,
                action=action,
                price=price,
                lots=lots,
                total_amount=total_amount,
                status="FAILED",
                message="Trading PIN belum dikonfigurasi di .env atau payload.",
                screenshot_path=None
            )

        logger.info(f"Memulai eksekusi {action} {lots} lot {clean_ticker} @ Rp {price:,}...")

        async with async_playwright() as p:
            context = await self.get_context(p, headless=self.headless)
            page = await context.new_page()

            try:
                # 1. Buka halaman order saham
                order_url = f"https://stockbit.com/#/symbol/{clean_ticker}/order"
                await page.goto(order_url, timeout=self.timeout_ms, wait_until="domcontentloaded")
                await asyncio.sleep(2.5)

                # 2. Cek apakah diarahkan ke halaman login
                if "login" in page.url.lower():
                    await page.screenshot(path=screenshot_path)
                    await context.close()
                    return OrderResult(
                        success=False,
                        ticker=clean_ticker,
                        action=action,
                        price=price,
                        lots=lots,
                        total_amount=total_amount,
                        status="REJECTED",
                        message="Sesi Stockbit kedaluwarsa. Silakan jalankan 'python cli.py login' ulang.",
                        screenshot_path=screenshot_path
                    )

                # 3. Pilih Tab BUY atau SELL
                action_btn_selector = f"button:has-text('{action.capitalize()}')"
                if await page.locator(action_btn_selector).count() > 0:
                    await page.click(action_btn_selector)
                    await asyncio.sleep(0.5)

                # 4. Input Harga (Price)
                price_input = page.locator("input[placeholder*='Price'], input[name*='price'], input[data-testid*='price']").first
                if await price_input.count() > 0:
                    await price_input.click()
                    await price_input.fill("")
                    await price_input.type(str(price), delay=50)
                else:
                    inputs = page.locator("input[type='text'], input[type='number']")
                    if await inputs.count() >= 2:
                        await inputs.nth(0).click()
                        await inputs.nth(0).fill(str(price))

                # 5. Input Lot
                lot_input = page.locator("input[placeholder*='Lot'], input[name*='lot'], input[data-testid*='lot']").first
                if await lot_input.count() > 0:
                    await lot_input.click()
                    await lot_input.fill("")
                    await lot_input.type(str(lots), delay=50)
                else:
                    inputs = page.locator("input[type='text'], input[type='number']")
                    if await inputs.count() >= 2:
                        await inputs.nth(1).click()
                        await inputs.nth(1).fill(str(lots))

                await asyncio.sleep(1)

                # 6. Klik tombol Submit Order
                submit_btn = page.locator(f"button:has-text('Order {action.capitalize()}'), button:has-text('Send {action.capitalize()} Order'), button:has-text('Place Order')").first
                if await submit_btn.count() > 0:
                    await submit_btn.click()
                else:
                    btn = page.locator(f"button:has-text('{action}')").last
                    await btn.click()

                await asyncio.sleep(1.5)

                # 7. Masukkan Trading PIN jika diminta
                pin_input = page.locator("input[type='password'], input[placeholder*='PIN'], input[name*='pin']").first
                if await pin_input.count() > 0:
                    logger.info("Menginput 6-digit Trading PIN...")
                    await pin_input.fill(pin)
                    await asyncio.sleep(0.5)
                    confirm_btn = page.locator("button:has-text('Confirm'), button:has-text('Konfirmasi'), button:has-text('OK')").first
                    if await confirm_btn.count() > 0:
                        await confirm_btn.click()

                await asyncio.sleep(2.5)

                # 8. Ambil screenshot bukti eksekusi
                await page.screenshot(path=screenshot_path)
                logger.info(f"Screenshot disimpan ke: {screenshot_path}")

                await context.close()

                return OrderResult(
                    success=True,
                    order_id=f"ORD_{clean_ticker}_{timestamp_str}",
                    ticker=clean_ticker,
                    action=action,
                    price=price,
                    lots=lots,
                    total_amount=total_amount,
                    status="SUBMITTED",
                    message=f"Order {action} {clean_ticker} senilai Rp {total_amount:,} berhasil dikirim ke Stockbit.",
                    screenshot_path=screenshot_path
                )

            except Exception as e:
                logger.error(f"Gagal mengeksekusi order: {e}")
                try:
                    await page.screenshot(path=screenshot_path)
                except:
                    screenshot_path = None
                await context.close()

                return OrderResult(
                    success=False,
                    ticker=clean_ticker,
                    action=action,
                    price=price,
                    lots=lots,
                    total_amount=total_amount,
                    status="FAILED",
                    message=f"Terjadi kegagalan automasi: {str(e)}",
                    screenshot_path=screenshot_path
                )
