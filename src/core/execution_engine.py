import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from loguru import logger
from src.config.settings import settings
from src.core.models import OrderRequest, OrderResult
from src.core.risk_manager import RiskManager
from src.drivers.stockbit_driver import StockbitDriver
from src.notifier.telegram_notifier import TelegramNotifier
from src.storage.db import (
    save_active_position,
    get_active_positions,
    close_position_to_trade_log,
    get_trade_logs,
)
from src.screener.strategy_screener import StrategyScreener

class ExecutionEngine:
    """
    Orkestrator Eksekusi Mandiri (100% Standalone Alugara Engine)
    """
    def __init__(self):
        self.driver = StockbitDriver()
        self.notifier = TelegramNotifier()
        self.risk_manager = RiskManager()
        self.screener = StrategyScreener()

    async def execute_single_order(self, req: OrderRequest) -> OrderResult:
        """
        Mengeksekusi satu order beli/jual secara mandiri
        """
        is_tick_valid, tick_msg = self.risk_manager.validate_price_tick(req.price)
        if not is_tick_valid:
            req.price = self.risk_manager.round_to_valid_tick(req.price)
            logger.info(f"Harga disesuaikan otomatis ke fraksi IDX valid: Rp {req.price:,}")

        # 1. Eksekusi via Driver Stockbit
        result = await self.driver.place_order(
            ticker=req.ticker,
            action=req.action,
            price=req.price,
            lots=req.lots,
            trading_pin=req.trading_pin,
            strategy_name=req.strategy_name or "Kuantitatif"
        )

        # 2. Catat langsung ke Database Internal Alugara
        if result.success and req.action == "BUY":
            save_active_position({
                "ticker": req.ticker,
                "strategy_name": req.strategy_name or "Kuantitatif",
                "action": "BUY",
                "entry_price": req.price,
                "current_price": req.price,
                "lots": req.lots,
                "invested_amount": result.total_amount,
                "target_price_1": req.target_price,
                "target_price_2": req.target_price,
                "stop_loss_price": req.stop_loss_price,
                "entry_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "ACTIVE_HOLD",
                "screenshot_path": result.screenshot_path
            })
            logger.info(f"Posisi aktif {req.ticker} berhasil disimpan di database internal Alugara.")

        # 3. Kirim Notifikasi Telegram Bot
        await self.notifier.notify_order_result(result, req.strategy_name or "Strategi Saham")

        return result

    async def run_afternoon_auto_buy(self):
        """
        Jadwal Beli Sore (15:40 WIB):
        1. Jalankan screener internal untuk memilih 3 saham terbaik.
        2. Alokasikan modal per strategi (dibagi rata ke 3 emiten).
        3. Eksekusi order Beli otomatis di Stockbit.
        """
        logger.info("🚀 [ALUGARA AUTO-BUY] Memulai rutinitas eksekusi beli sore 15:40 WIB...")
        signals = await self.screener.scan_market_signals()
        if not signals:
            logger.warning("Tidak ada sinyal yang memenuhi kriteria hari ini.")
            return

        capital_per_stock = settings.CAPITAL_PER_STRATEGY / max(1, len(signals))

        for sig in signals:
            lots = self.risk_manager.calculate_lots(capital_per_stock, sig["current_price"])
            if lots <= 0:
                logger.warning(f"Modal tidak cukup untuk 1 lot {sig['ticker']} @ Rp {sig['current_price']:,}")
                continue

            req = OrderRequest(
                ticker=sig["ticker"],
                action="BUY",
                price=sig["current_price"],
                lots=lots,
                strategy_name=sig.get("strategy_name", "BSJP 1"),
                target_price=sig.get("target_price_1"),
                stop_loss_price=sig.get("stop_loss_price")
            )

            await self.execute_single_order(req)

    async def run_morning_auto_sell(self):
        """
        Jadwal Jual Pagi (09:10 WIB):
        1. Cek semua posisi aktif dari database internal.
        2. Ambil harga pembukaan pasar hari ini.
        3. Eksekusi jual untuk realisasi Take Profit / Stop Loss / Time-Exit.
        """
        logger.info("🎯 [ALUGARA AUTO-SELL] Memulai rutinitas evaluasi jual pagi 09:10 WIB...")
        positions = get_active_positions()
        if not positions:
            logger.info("Tidak ada posisi aktif yang perlu dievaluasi pagi ini.")
            return

        for pos in positions:
            quote = await self.screener.fetch_quote(pos["ticker"])
            current_price = quote["price"] if quote["success"] else pos["entry_price"]
            
            # Hitung Profit / Loss
            entry_price = pos["entry_price"]
            lots = pos["lots"]
            invested = pos["invested_amount"]
            gross_return = current_price * lots * 100
            net_profit = gross_return - invested
            profit_pct = (net_profit / invested) * 100 if invested > 0 else 0

            # Eksekusi Jual Otomatis
            req = OrderRequest(
                ticker=pos["ticker"],
                action="SELL",
                price=current_price,
                lots=lots,
                strategy_name=pos.get("strategy_name", "Kuantitatif")
            )
            result = await self.driver.place_order(
                ticker=req.ticker,
                action="SELL",
                price=req.price,
                lots=req.lots,
                strategy_name=req.strategy_name
            )

            # Update database internal Alugara
            exit_reason = "TP_HIT" if profit_pct >= 2.0 else ("SL_HIT" if profit_pct <= -2.0 else "TIME_EXIT_MORNING")
            status = "WIN" if net_profit >= 0 else "LOSS"

            close_position_to_trade_log(pos["id"], {
                "ticker": pos["ticker"],
                "strategy_name": pos["strategy_name"],
                "action": "SELL",
                "entry_price": entry_price,
                "exit_price": current_price,
                "lots": lots,
                "invested_amount": invested,
                "gross_return": gross_return,
                "net_profit": net_profit,
                "profit_percent": profit_pct,
                "status": status,
                "exit_reason": exit_reason,
                "entry_date": pos["entry_date"],
                "exit_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "screenshot_path": result.screenshot_path
            })

            # Kirim Telegram
            await self.notifier.notify_order_result(result, pos.get("strategy_name", "Strategi Saham"))
