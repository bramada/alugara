import os
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from loguru import logger
from playwright.async_api import async_playwright, BrowserContext, Page
from src.config.settings import settings
from src.core.models import OrderResult

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

        return context

    async def check_session_valid(self) -> Tuple[bool, str]:
        """
        Memeriksa apakah sesi login Stockbit saat ini masih aktif dan valid
        """
        async with async_playwright() as p:
            context = await self.get_context(p, headless=True)
            page = await context.new_page()
            try:
                logger.info("Memeriksa status sesi login Stockbit...")
                await page.goto("https://stockbit.com/#/order", timeout=self.timeout_ms, wait_until="domcontentloaded")
                await asyncio.sleep(3)

                current_url = page.url
                # Jika dialihkan ke halaman login, sesi tidak aktif
                if "login" in current_url.lower() or "signin" in current_url.lower():
                    await context.close()
                    return False, "Sesi kedaluwarsa atau belum login."

                # Cek elemen profil/portofolio
                is_logged_in = await page.evaluate("""
                    () => {
                        const avatar = document.querySelector('[data-testid="user-avatar"]') || 
                                       document.querySelector('.header-avatar') ||
                                       document.querySelector('a[href*="/portfolio"]') ||
                                       document.querySelector('button[aria-label*="Account"]');
                        return !!avatar;
                    }
                """)

                await context.close()
                if is_logged_in:
                    return True, "Sesi login Stockbit aktif & siap eksekusi."
                return True, "Sesi aktif (URL Order dapat diakses)."
            except Exception as e:
                await context.close()
                logger.error(f"Error checking session: {e}")
                return False, f"Gagal mengecek sesi: {str(e)}"

    async def interactive_login(self):
        """
        Membuka browser interaktif (GUI) agar pengguna dapat login 1x dan input OTP.
        Sesi akan otomatis disimpan secara permanen di sessions/.
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
                    logger.info("Berhasil menyimpan session state Stockbit!")
                    print("\n✅ LOGIN BERHASIL! Sesi telah disimpan di sessions/stockbit_state.json.")
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
