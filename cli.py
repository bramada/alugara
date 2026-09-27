import asyncio
import click
from loguru import logger
from src.storage.db import init_db, get_active_positions, get_trade_logs
from src.drivers.stockbit_driver import StockbitDriver
from src.core.models import OrderRequest
from src.core.execution_engine import ExecutionEngine
from src.notifier.telegram_notifier import TelegramNotifier
from src.config.settings import settings

@click.group()
def cli():
    """Alugara CLI - Kontrol & Manajemen Bot Trading Mandiri"""
    init_db()

@cli.command()
def login():
    """Buka browser interaktif untuk pairing login 1x ke Stockbit"""
    driver = StockbitDriver(headless=False)
    asyncio.run(driver.interactive_login())

@cli.command()
def check_session():
    """Periksa apakah sesi login Stockbit saat ini valid"""
    driver = StockbitDriver(headless=True)
    valid, msg = asyncio.run(driver.check_session_valid())
    if valid:
        click.secho(f"✅ {msg}", fg="green", bold=True)
    else:
        click.secho(f"❌ {msg}", fg="red", bold=True)

@cli.command()
def scan():
    """Jalankan screener internal Alugara untuk melihat rekomendasi emiten hari ini"""
    engine = ExecutionEngine()
    signals = asyncio.run(engine.screener.scan_market_signals())
    click.secho(f"\n📊 Hasil Screener Internal Alugara ({len(signals)} Saham):", fg="cyan", bold=True)
    for s in signals:
        click.echo(f"• {s['ticker']}: Rp {s['current_price']:,} (TP: Rp {s['target_price_1']:,} | SL: Rp {s['stop_loss_price']:,})")

@cli.command()
def run_buy():
    """Jalankan eksekusi Beli Sore (15:40 WIB) secara manual sekarang"""
    engine = ExecutionEngine()
    asyncio.run(engine.run_afternoon_auto_buy())

@cli.command()
def run_sell():
    """Jalankan evaluasi Jual Pagi (09:10 WIB) secara manual sekarang"""
    engine = ExecutionEngine()
    asyncio.run(engine.run_morning_auto_sell())

@cli.command()
def positions():
    """Lihat daftar posisi saham aktif yang sedang di-hold di database internal Alugara"""
    pos = get_active_positions()
    click.secho(f"\n💼 Posisi Aktif Alugara ({len(pos)} Saham):", fg="yellow", bold=True)
    for p in pos:
        click.echo(f"• {p['ticker']} | {p['lots']} Lot | Beli: Rp {p['entry_price']:,} | Entry: {p['entry_date']}")

@cli.command()
def history():
    """Lihat histori transaksi yang sudah selesai dieksekusi Alugara"""
    logs = get_trade_logs(limit=20)
    click.secho(f"\n📜 Histori Transaksi ({len(logs)} Trade):", fg="blue", bold=True)
    for l in logs:
        status_color = "green" if l['status'] == "WIN" else "red"
        click.secho(f"• {l['ticker']} | {l['status']} ({l['profit_percent']:+.2f}%) | Beli: Rp {l['entry_price']:,} -> Jual: Rp {l['exit_price']:,} | P/L: Rp {l['net_profit']:+,.0f}", fg=status_color)

@cli.command()
def test_telegram():
    """Kirim pesan uji coba ke Telegram Bot Anda"""
    notifier = TelegramNotifier()
    success = asyncio.run(notifier.send_message(
        "🤖 <b>ALUGARA TELEGRAM NOTIFIER TEST</b>\n\n"
        "Koneksi Telegram Bot berhasil terhubung ke server Alugara Standalone!"
    ))
    if success:
        click.secho("✅ Notifikasi Telegram berhasil terkirim!", fg="green")
    else:
        click.secho("❌ Gagal mengirim ke Telegram. Cek TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID di .env.", fg="red")

@cli.command()
@click.option("--host", default=settings.HOST, help="Host address")
@click.option("--port", default=settings.PORT, type=int, help="Port number")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload")
def serve(host, port, reload):
    """Jalankan Server API & Scheduler Alugara"""
    import uvicorn
    uvicorn.run("src.api.main:app", host=host, port=port, reload=reload)

if __name__ == "__main__":
    cli()
