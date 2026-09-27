# 🦅 ALUGARA — Standalone Automated Stock Trading Engine

**Alugara** adalah sistem eksekusi trading otomatis (*Algorithmic Trading*) mandiri yang **100% berdiri sendiri dan terpisah**.

---

## 🌟 Fitur Utama (100% Mandiri)

1. **Internal Quantitative Screener**: Memindai bursa saham IDX secara mandiri dari feed data pasar dan memilih saham momentum terbaik.
2. **Internal SQLite Database (`data/alugara.db`)**: Menyimpan posisi saham aktif (`active_positions`) dan riwayat jual/beli (`trade_logs`) tanpa terhubung ke database luar.
3. **Automated Market Scheduler**:
   - **15:35 WIB**: Pre-Market Session Health Check.
   - **15:40 WIB**: Eksekusi otomatis Beli Sore (Stockbit Web).
   - **09:10 WIB**: Evaluasi & Eksekusi otomatis Jual Pagi (Take Profit / Stop Loss).
4. **Persistent Session & Stealth Driver**: Login 1x saja, cookies tersimpan permanen.
5. **Direct Telegram Alerts**: Mengirim notifikasi dan screenshot bukti order langsung ke HP Anda.

---

## 🚀 Perintah CLI Cepat

```bash
# 1. Login pairing 1x ke Stockbit
python cli.py login

# 2. Cek status sesi
python cli.py check-session

# 3. Jalankan scanning pasar mandiri
python cli.py scan

# 4. Lihat posisi saham aktif internal
python cli.py positions

# 5. Lihat riwayat trade internal
python cli.py history

# 6. Jalankan Server & Penjadwal Otomatis
python cli.py serve
```
