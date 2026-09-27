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
    get_setting,
)
from src.screener.strategy_screener import StrategyScreener
from src.ai.gemini_analyzer import GeminiAnalyzer

class ExecutionEngine:
    """
    Orkestrator Eksekusi Mandiri Alugara (Full-Day Intraday & Scalping Engine)
    Didukung Gemini AI dengan filosofi: Cuan berapa persen pun asal tidak lose.
    """
    def __init__(self):
        self.driver = StockbitDriver()
        self.notifier = TelegramNotifier()
        self.risk_manager = RiskManager()
        self.screener = StrategyScreener()
        self.ai = GeminiAnalyzer()

    async def execute_single_order(self, req: OrderRequest, ai_score: int = 0, ai_reasoning: str = "") -> OrderResult:
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
            strategy_name=req.strategy_name or "Intraday Multi-Trade"
        )

        # 2. Catat langsung ke Database Internal Alugara
        if result.success and req.action == "BUY":
            save_active_position({
                "ticker": req.ticker,
                "strategy_name": req.strategy_name or "Intraday Multi-Trade",
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
                "ai_score": ai_score,
                "ai_reasoning": ai_reasoning,
                "screenshot_path": result.screenshot_path
            })
            logger.info(f"Posisi aktif {req.ticker} berhasil disimpan di database internal Alugara.")

        # 3. Kirim Notifikasi Telegram Bot
        await self.notifier.notify_order_result(result, req.strategy_name or "Intraday Multi-Trade")

        return result

    async def run_intraday_cycle(self, now: Optional[datetime] = None, force_scan: bool = False):
        """
        Siklus Intraday Auto-Trade Berjalan Terus-Menerus di Jam Bursa:
        1. Pantau seluruh posisi aktif:
           - Cek Take Profit (+1.5% s/d +3.5%) -> langsung SELL ambil untung.
           - Cek Stop Loss (-1.5% s/d -2.0%) -> langsung SELL proteksi modal (asal tidak lose).
           - Cek End-of-Day Cash-out (15:40 - 15:55 WIB) -> amankan posisi jadi kas tunai sebelum tutup bursa.
        2. Cari Peluang Beli Baru (jika modal kas tersedia & belum jam tutup):
           - Scan market feed real-time.
           - Filter Gemini AI.
           - Eksekusi BUY untuk peluang dengan skor keyakinan tinggi.
        """
        logger.info("⚡ [INTRADAY CYCLE] Memulai evaluasi pasar & portofolio aktif...")
        
        # 1. EVALUASI POSISI AKTIF (EXIT MONITORING)
        positions = get_active_positions()
        is_closing_window = False
        if now:
            is_closing_window = (now.hour == 15 and now.minute >= 40)

        for pos in positions:
            quote = await self.screener.fetch_quote(pos["ticker"])
            current_price = quote["price"] if quote["success"] else pos["current_price"]
            
            entry_price = pos["entry_price"]
            lots = pos["lots"]
            invested = pos["invested_amount"]
            gross_return = current_price * lots * 100
            net_profit = gross_return - invested
            profit_pct = (net_profit / invested) * 100 if invested > 0 else 0

            # Kriteria Exit Cepat
            target_1 = pos.get("target_price_1") or (entry_price * 1.02)
            stop_loss = pos.get("stop_loss_price") or (entry_price * 0.985)
            
            should_sell = False
            exit_reason = ""
            status = "WIN" if net_profit >= 0 else "LOSS"

            if current_price >= target_1 or profit_pct >= 1.5:
                should_sell = True
                exit_reason = f"INTRADAY_TP_HIT (+{profit_pct:.2f}%)"
                status = "WIN"
            elif current_price <= stop_loss or profit_pct <= -1.5:
                should_sell = True
                exit_reason = f"STRICT_STOP_LOSS ({profit_pct:.2f}%)"
                status = "LOSS"
            elif is_closing_window:
                should_sell = True
                exit_reason = f"END_OF_DAY_CASHOUT ({profit_pct:+.2f}%)"

            if should_sell:
                logger.info(f"🎯 [AUTO-SELL] Menjual {pos['ticker']} @ Rp {current_price:,} | Alasan: {exit_reason}")
                req = OrderRequest(
                    ticker=pos["ticker"],
                    action="SELL",
                    price=current_price,
                    lots=lots,
                    strategy_name=pos.get("strategy_name", "Intraday")
                )
                result = await self.driver.place_order(
                    ticker=req.ticker,
                    action="SELL",
                    price=req.price,
                    lots=req.lots,
                    strategy_name=req.strategy_name
                )

                trade_log_item = {
                    "ticker": pos["ticker"],
                    "strategy_name": pos.get("strategy_name", "Intraday"),
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
                }

                close_position_to_trade_log(pos["id"], trade_log_item)
                await self.ai.reflect_on_closed_trade(trade_log_item)
                await self.notifier.notify_order_result(result, pos.get("strategy_name", "Intraday"))

        # 2. EVALUASI ENTRY / BELI BARU
        # Jangan buka posisi baru jika sudah mendekati penutupan (>= 15:20 WIB) kecuali dipaksa manual
        too_late = (now and now.hour == 15 and now.minute >= 20) and not force_scan
        if too_late:
            logger.info("Menjelang tutup bursa (>= 15:20 WIB). Menahan order baru, fokus mengamankan kas.")
            return

        # Hitung sisa modal kas
        total_capital = float(get_setting("capital_per_strategy", str(settings.CAPITAL_PER_STRATEGY)))
        current_active = get_active_positions()
        invested_capital = sum(p.get("invested_amount", 0) for p in current_active)
        free_capital = total_capital - invested_capital

        if free_capital < 200000 and not force_scan:
            logger.info(f"Modal terpakai optimal (Sisa kas: Rp {free_capital:,.0f}). Menunggu posisi ditutup.")
            return

        active_tickers = {p["ticker"] for p in current_active}
        raw_signals = await self.screener.scan_market_signals()
        candidates = [s for s in raw_signals if s["ticker"] not in active_tickers]
        if not candidates:
            logger.info("Tidak ada kandidat baru yang memenuhi kriteria saat ini.")
            return

        signals = await self.ai.analyze_and_rank_candidates(candidates)
        if not signals:
            logger.info("Gemini AI tidak menemukan kandidat aman saat ini.")
            return

        capital_per_stock = free_capital / max(1, len(signals))

        for sig in signals:
            lots = self.risk_manager.calculate_lots(capital_per_stock, sig["current_price"])
            if lots <= 0:
                logger.warning(f"Sisa kas tidak cukup untuk 1 lot {sig['ticker']} @ Rp {sig['current_price']:,}")
                continue

            req = OrderRequest(
                ticker=sig["ticker"],
                action="BUY",
                price=sig["current_price"],
                lots=lots,
                strategy_name=sig.get("strategy_name", "Intraday Momentum"),
                target_price=sig.get("target_price_1"),
                stop_loss_price=sig.get("stop_loss_price")
            )

            await self.execute_single_order(
                req,
                ai_score=sig.get("ai_score", 0),
                ai_reasoning=sig.get("ai_reasoning", "")
            )

    async def run_afternoon_auto_buy(self):
        """Kompatibilitas alias untuk run_intraday_cycle"""
        await self.run_intraday_cycle(force_scan=True)

    async def run_morning_auto_sell(self):
        """Kompatibilitas: evaluasi dan jual seluruh posisi terbuka"""
        positions = get_active_positions()
        for pos in positions:
            quote = await self.screener.fetch_quote(pos["ticker"])
            current_price = quote["price"] if quote["success"] else pos["entry_price"]
            req = OrderRequest(
                ticker=pos["ticker"],
                action="SELL",
                price=current_price,
                lots=pos["lots"],
                strategy_name=pos.get("strategy_name", "Intraday")
            )
            result = await self.driver.place_order(ticker=req.ticker, action="SELL", price=req.price, lots=req.lots)
            net_profit = (current_price * pos["lots"] * 100) - pos["invested_amount"]
            trade_log_item = {
                "ticker": pos["ticker"],
                "strategy_name": pos.get("strategy_name", "Intraday"),
                "action": "SELL",
                "entry_price": pos["entry_price"],
                "exit_price": current_price,
                "lots": pos["lots"],
                "invested_amount": pos["invested_amount"],
                "gross_return": current_price * pos["lots"] * 100,
                "net_profit": net_profit,
                "profit_percent": (net_profit / pos["invested_amount"] * 100) if pos["invested_amount"] > 0 else 0,
                "status": "WIN" if net_profit >= 0 else "LOSS",
                "exit_reason": "MANUAL_OR_MORNING_EXIT",
                "entry_date": pos["entry_date"],
                "exit_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "screenshot_path": result.screenshot_path
            }
            close_position_to_trade_log(pos["id"], trade_log_item)
            await self.ai.reflect_on_closed_trade(trade_log_item)
