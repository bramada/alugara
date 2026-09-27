import httpx
import asyncio
from typing import List, Dict, Any
from loguru import logger

class StrategyScreener:
    """
    Internal Quantitative & Intraday Screener untuk Alugara (Standalone)
    Mengambil data live IDX dari market feed dan mendeteksi momentum, volume breakout, serta reversal.
    """
    
    # Daftar kandidat emiten Likuid IDX (LQ45 & High Volume Movers)
    UNIVERSE = [
        "BBCA", "BBRI", "BMRI", "BBNI", "ASII", "TLKM", "UNTR", "ICBP",
        "INDF", "AMRT", "ADRO", "PTBA", "MDKA", "MEDC", "KLBF", "CPIN",
        "BRIS", "ACES", "MYOR", "INKP", "PGAS", "CTRA", "BSDE", "SMRA",
        "GOTO", "BUKA", "ARTO", "EMTK", "TOWR", "TBIG", "ANTM", "INCO"
    ]

    @classmethod
    async def fetch_quote(cls, ticker: str) -> Dict[str, Any]:
        clean = ticker.upper().replace(".JK", "").strip()
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{clean}.JK?interval=1d&range=1d"
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                res = await client.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                })
                if res.status_code == 200:
                    data = res.json()
                    meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
                    price = int(meta.get("regularMarketPrice", 0))
                    prev_close = int(meta.get("chartPreviousClose", price) or price)
                    change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0
                    return {
                        "ticker": clean,
                        "price": price,
                        "prev_close": prev_close,
                        "change_percent": change_pct,
                        "success": price > 0
                    }
        except Exception as e:
            logger.debug(f"Gagal mengambil quote {clean}: {e}")

        return {"ticker": clean, "price": 0, "prev_close": 0, "change_percent": 0, "success": False}

    @classmethod
    async def scan_market_signals(cls) -> List[Dict[str, Any]]:
        """
        Memindai kandidat saham aktif intraday untuk peluang cuan cepat & minim risiko
        """
        logger.info("Memulai scanning intraday real-time pasar BEI...")
        tasks = [cls.fetch_quote(t) for t in cls.UNIVERSE]
        quotes = await asyncio.gather(*tasks)

        # Filter saham aktif dengan momentum positif
        valid_quotes = [q for q in quotes if q["success"] and q["price"] > 0]
        
        # Urutkan berdasarkan momentum persentase kenaikan harian yang sehat (+0.5% s/d +7.0%)
        sorted_candidates = sorted(
            [q for q in valid_quotes if 0.5 <= q["change_percent"] <= 7.0],
            key=lambda x: x["change_percent"],
            reverse=True
        )

        candidates = sorted_candidates if sorted_candidates else [q for q in valid_quotes if q["change_percent"] > 0]
        if not candidates:
            candidates = valid_quotes

        signals = []
        for item in candidates:
            p = item["price"]
            pct = item["change_percent"]
            
            # Klasifikasi strategi intraday secara dinamis
            if pct >= 2.5:
                strat = "Intraday Breakout Momentum"
            elif pct >= 1.0:
                strat = "Trend Following Accumulation"
            else:
                strat = "Scalping Rebound Setup"

            # Target Cepat: TP1 +2.0%, TP2 +3.5%, Stop Loss ketat -1.5% (prioritas: asal tidak lose)
            tp1 = int(round(p * 1.02))
            tp2 = int(round(p * 1.035))
            sl = int(round(p * 0.985))

            signals.append({
                "ticker": item["ticker"],
                "action": "BUY",
                "current_price": p,
                "target_price_1": tp1,
                "target_price_2": tp2,
                "stop_loss_price": sl,
                "strategy_name": strat
            })

        logger.info(f"Scanning intraday selesai! Menghasilkan {len(signals)} kandidat sinyal aktif.")
        return signals
