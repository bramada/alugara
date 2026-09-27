import math
from typing import Tuple

class RiskManager:
    """
    Risk Management & Validasi Fraksi Harga Bursa Efek Indonesia (IDX)
    """

    @staticmethod
    def get_idx_tick_size(price: int) -> int:
        """
        Fraksi Harga Saham BEI:
        - Harga < Rp 200      : Fraksi Rp 1
        - Harga Rp 200 - 500  : Fraksi Rp 2
        - Harga Rp 500 - 2000 : Fraksi Rp 5
        - Harga Rp 2000 - 5000: Fraksi Rp 10
        - Harga >= Rp 5000    : Fraksi Rp 25
        """
        if price < 200:
            return 1
        elif price < 500:
            return 2
        elif price < 2000:
            return 5
        elif price < 5000:
            return 10
        else:
            return 25

    @classmethod
    def round_to_valid_tick(cls, price: int) -> int:
        """
        Membulatkan harga ke fraksi harga IDX terdekat
        """
        tick = cls.get_idx_tick_size(price)
        return int(round(price / tick) * tick)

    @classmethod
    def validate_price_tick(cls, price: int) -> Tuple[bool, str]:
        """
        Memastikan harga sesuai dengan fraksi harga resmi BEI
        """
        tick = cls.get_idx_tick_size(price)
        if price % tick != 0:
            valid_p = cls.round_to_valid_tick(price)
            return False, f"Harga Rp {price} tidak sesuai fraksi IDX (Tick Rp {tick}). Rekomendasi: Rp {valid_p}"
        return True, "Valid"

    @classmethod
    def calculate_lots(cls, capital: float, price: int) -> int:
        """
        Menghitung jumlah lot (1 lot = 100 lembar) dari alokasi modal
        """
        if price <= 0 or capital <= 0:
            return 0
        shares_needed = capital / price
        lots = math.floor(shares_needed / 100)
        return max(1, lots) if capital >= (price * 100) else 0

    @classmethod
    def validate_slippage(cls, expected_price: int, actual_price: int, max_slippage_percent: float = 2.0) -> Tuple[bool, float]:
        """
        Memeriksa apakah slippage harga masih dalam batas toleransi
        """
        if expected_price <= 0:
            return True, 0.0
        diff = abs(actual_price - expected_price)
        slippage_percent = (diff / expected_price) * 100.0
        is_ok = slippage_percent <= max_slippage_percent
        return is_ok, slippage_percent
