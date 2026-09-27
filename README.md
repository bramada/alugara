# ⚡ ALUGARA — Standalone Automated Stock Trading Engine

**Alugara** adalah sistem eksekusi trading otomatis (*Algorithmic Trading*) mandiri berbasis Python & FastAPI yang **100% berdiri sendiri dan terpisah** dengan Web GUI Dashboard terintegrasi.

---

## 🚀 Cara Menjalankan & Menghentikan Server

### 1. Menjalankan Server (Start)
Buka terminal (PowerShell / CMD), masuk ke direktori project, lalu jalankan:
```powershell
# Masuk ke direktori alugara
cd "e:\Web Project\alugara"

# Jalankan server dashboard & scheduler otomatis
python cli.py serve
```
Setelah server aktif, buka browser dan akses Web GUI Dashboard di:  
👉 **[http://localhost:8000](http://localhost:8000)**

---

### 2. Menghentikan Server (Stop)
Anda dapat menghentikan server dengan beberapa cara berikut:

- **Cara 1 (CLI Alugara):**
  Buka terminal baru di direktori alugara, lalu jalankan perintah:
  ```powershell
  python cli.py stop
  ```

- **Cara 2 (Shortcut Keyboard):**  
  Tekan **`Ctrl + C`** pada jendela terminal tempat server sedang berjalan.

- **Cara 3 (PowerShell Langsung):**
  ```powershell
  Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
  ```

---

## 🛠️ Perintah CLI Lengkap

| Perintah | Deskripsi |
| :--- | :--- |
| `python cli.py serve` | **Start Server**: Menjalankan Web Dashboard & Penjadwal Trading Otomatis (Port 8000) |
| `python cli.py stop` | **Stop Server**: Menghentikan server Alugara yang sedang berjalan pada port 8000 |
| `python cli.py login` | Membuka jendela Google Chrome interaktif untuk login/pairing ke Stockbit |
| `python cli.py check-session` | Memeriksa apakah sesi login Stockbit masih aktif dan valid |
| `python cli.py scan` | Menjalankan pemindaian sinyal saham intraday BEI secara instan |
| `python cli.py positions` | Menampilkan daftar seluruh posisi saham aktif di portofolio internal |
| `python cli.py history` | Melihat riwayat transaksi jual/beli beserta keuntungan/kerugian (P/L) |

---

## 🌟 Fitur Utama (100% Mandiri)

1. **Internal Quantitative Screener**: Memindai bursa saham IDX secara mandiri dari feed data pasar real-time.
2. **Google Gemini AI Reasoning**: Analisis mendalam multi-faktor dan penyaring jebakan bandar dengan sistem fallback otomatis.
3. **Gemini Quota & Rate Limit Monitor**: Pemantau kuota real-time (1,500 RPD harian & 15 RPM) bergaya Antigravity.
4. **Internal SQLite Database (`data/alugara.db`)**: Menyimpan posisi saham aktif, riwayat transaksi, dan memori AI dengan enkripsi AES-256.
5. **Automated Market Scheduler**:
   - **Intraday Scanning**: Memindai peluang saham sepanjang jam bursa.
   - **09:10 WIB**: Evaluasi & Eksekusi otomatis Jual Pagi (Take Profit / Stop Loss).
   - **15:40 WIB**: Eksekusi otomatis Beli Sore (Stockbit Web).
6. **Persistent Session & Stealth Driver**: Login pairing 1x saja, sesi tersimpan permanen.
7. **Direct Telegram Alerts**: Notifikasi live dan konfirmasi order langsung ke grup/chat Telegram Anda.
