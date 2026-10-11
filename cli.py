import asyncio
import os
import signal
import subprocess
import sys
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
        click.secho(f"[OK] {msg}", fg="green", bold=True)
    else:
        click.secho(f"[ERROR] {msg}", fg="red", bold=True)

@cli.command()
@click.option("--passphrase", "-p", default="", help="Passphrase pengaman untuk enkripsi (opsional)")
@click.option("--output", "-o", default="", help="Path file output (.alugara)")
def export_session(passphrase, output):
    """Ekspor sesi Stockbit saat ini ke file terenkripsi (.alugara)"""
    import json
    driver = StockbitDriver(headless=True)
    ok, pkg, msg = driver.export_session_package(passphrase=passphrase if passphrase else None)
    if not ok:
        click.secho(f"[ERROR] {msg}", fg="red", bold=True)
        return
    
    if not output:
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = os.path.join(driver.session_dir, f"stockbit_session_{ts}.alugara")
    
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(pkg, f, indent=2)
    
    click.secho(f"[OK] {msg}", fg="green", bold=True)
    click.secho(f"File sesi tersimpan di: {output}", fg="cyan")

@cli.command()
@click.argument("filepath", type=click.Path(exists=True))
@click.option("--passphrase", "-p", default="", help="Passphrase pengaman jika file terproteksi")
def import_session(filepath, passphrase):
    """Impor file sesi Stockbit terenkripsi (.alugara) ke dalam sistem & database"""
    import json
    driver = StockbitDriver(headless=True)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            pkg = json.load(f)
    except Exception as e:
        click.secho(f"[ERROR] Gagal membaca file: {e}", fg="red", bold=True)
        return

    ok, msg = driver.import_session_package(pkg, passphrase=passphrase if passphrase else None)
    if ok:
        click.secho(f"[OK] {msg}", fg="green", bold=True)
        valid, vmsg = asyncio.run(driver.check_session_valid())
        if valid:
            click.secho(f"[VERIFIED] {vmsg}", fg="green")
        else:
            click.secho(f"[WARNING] {vmsg}", fg="yellow")
    else:
        click.secho(f"[ERROR] {msg}", fg="red", bold=True)

@cli.command()
def scan():
    """Jalankan screener internal Alugara untuk melihat rekomendasi emiten hari ini"""
    engine = ExecutionEngine()
    signals = asyncio.run(engine.screener.scan_market_signals())
    click.secho(f"\nHasil Screener Internal Alugara ({len(signals)} Saham):", fg="cyan", bold=True)
    for s in signals:
        click.echo(f"- {s['ticker']}: Rp {s['current_price']:,} (TP: Rp {s['target_price_1']:,} | SL: Rp {s['stop_loss_price']:,})")

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
    click.secho(f"\nPosisi Aktif Alugara ({len(pos)} Saham):", fg="yellow", bold=True)
    for p in pos:
        click.echo(f"- {p['ticker']} | {p['lots']} Lot | Beli: Rp {p['entry_price']:,} | Entry: {p['entry_date']}")

@cli.command()
def history():
    """Lihat histori transaksi yang sudah selesai dieksekusi Alugara"""
    logs = get_trade_logs(limit=20)
    click.secho(f"\nHistori Transaksi ({len(logs)} Trade):", fg="blue", bold=True)
    for l in logs:
        status_color = "green" if l['status'] == "WIN" else "red"
        click.secho(f"- {l['ticker']} | {l['status']} ({l['profit_percent']:+.2f}%) | Beli: Rp {l['entry_price']:,} -> Jual: Rp {l['exit_price']:,} | P/L: Rp {l['net_profit']:+,.0f}", fg=status_color)

@cli.command()
def test_telegram():
    """Kirim pesan uji coba ke Telegram Bot Anda"""
    notifier = TelegramNotifier()
    success = asyncio.run(notifier.send_message(
        "<b>ALUGARA TELEGRAM NOTIFIER TEST</b>\n\n"
        "Koneksi Telegram Bot berhasil terhubung ke server Alugara Standalone!"
    ))
    if success:
        click.secho("[OK] Notifikasi Telegram berhasil terkirim!", fg="green")
    else:
        click.secho("[ERROR] Gagal mengirim ke Telegram. Cek TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID di .env.", fg="red")

@cli.command()
@click.option("--host", default=settings.HOST, help="Host address")
@click.option("--port", default=settings.PORT, type=int, help="Port number")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload")
def serve(host, port, reload):
    """Jalankan Server API & Scheduler Alugara (Start Server)"""
    import uvicorn
    uvicorn.run("src.api.main:app", host=host, port=port, reload=reload)

@cli.command()
@click.option("--port", default=settings.PORT, type=int, help="Port number server yang akan dihentikan")
def stop(port):
    """Hentikan server Alugara yang sedang berjalan (Stop Server)"""
    try:
        if sys.platform == "win32":
            cmd = f'powershell -Command "Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force }}"'
            subprocess.run(cmd, shell=True, capture_output=True, text=True)
            click.secho(f"[STOP] Server Alugara pada port {port} berhasil dihentikan.", fg="green", bold=True)
        else:
            cmd = f"fuser -k {port}/tcp"
            subprocess.run(cmd, shell=True, capture_output=True)
            click.secho(f"[STOP] Server Alugara pada port {port} berhasil dihentikan.", fg="green", bold=True)
    except Exception as e:
        click.secho(f"[ERROR] Gagal menghentikan server: {e}", fg="red")

@cli.command()
@click.option("--username", default=None, help="Username baru")
@click.option("--password", default=None, help="Password baru")
def reset_password(username, password):
    """Reset Username & Password Web Dashboard Alugara"""
    from src.core.security import set_user_credentials
    from src.storage.db import get_setting
    
    current_user = get_setting("auth_username") or "admin"
    u = username or click.prompt("Masukkan Username", default=current_user)
    p = password or click.prompt("Masukkan Password baru", hide_input=True, confirmation_prompt=True)
    
    set_user_credentials(u, p)
    click.secho(f"[OK] Kredensial Alugara berhasil di-reset untuk username: '{u}'!", fg="green", bold=True)

if __name__ == "__main__":
    cli()
