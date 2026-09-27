import os
import json
import httpx
from typing import List, Dict, Any, Optional
from loguru import logger
from src.config.settings import settings
from src.storage.db import (
    get_setting,
    get_top_ai_memories,
    save_ai_memory
)

class GeminiAnalyzer:
    """
    Mesin Analisis AI Mendalam berbasis Google Gemini
    Dilengkapi Long-Term Memory Playbook (Continuous Learning).
    """

    def __init__(self):
        pass

    def get_api_key(self) -> str:
        return get_setting("gemini_api_key") or settings.GEMINI_API_KEY or ""

    def get_model(self) -> str:
        return get_setting("gemini_model") or settings.GEMINI_MODEL or "gemini-1.5-flash"

    def is_enabled(self) -> bool:
        enabled_setting = get_setting("ai_reasoning_enabled", str(settings.AI_REASONING_ENABLED))
        return enabled_setting.lower() == "true" and bool(self.get_api_key())

    async def call_gemini(self, prompt: str) -> Optional[str]:
        api_key = self.get_api_key()
        if not api_key:
            return None

        model = self.get_model()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 2048,
            }
        }

        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        return text
                else:
                    logger.error(f"Gemini API Error ({res.status_code}): {res.text}")
        except Exception as e:
            logger.error(f"Failed to call Gemini API: {e}")

        return None

    async def analyze_and_rank_candidates(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        FASE 1 (Pre-Trade AI Gatekeeper):
        Menganalisis daftar kandidat saham sore hari, menyaring jebakan bandar,
        memberi skor keyakinan AI (1-100), dan memilih saham-saham yang benar-benar layak tanpa batasan kuota kaku.
        """
        if not candidates:
            return []

        if not self.is_enabled():
            logger.info("Gemini AI reasoning nonaktif/tanpa API Key. Menggunakan ranking teknikal standar tanpa batasan kuota.")
            return candidates

        # 1. Ambil Buku Pintar Memori Masa Lalu (RAG Memory Context)
        past_memories = get_top_ai_memories(limit=8)
        memory_context = ""
        if past_memories:
            memory_context = "BUKU PINTAR PENGALAMAN TRADE SEBELUMNYA:\n"
            for m in past_memories:
                memory_context += f"- [Pola #{m['ticker']} ({m['trade_outcome']} {m['profit_percent']:+.1f}%)]: {m['lesson_learned']}\n"

        prompt = f"""
Anda adalah Senior Quantitative Trader & Chief Risk Officer di Bursa Efek Indonesia (IDX) untuk sistem Full-Day Auto-Trading Alugara.

FILOSOFI UTAMA TRADING KITA:
"Cuan berapa persen pun asal tidak lose. Bebas pakai strategi apapun, bebas berapa kali trade sehari. Modal aman dan untung konsisten dari bursa buka sampai tutup."

Tugas Anda:
Analisis secara real-time kandidat saham yang terdeteksi aktif di jam bursa ini.
Saring dan rekomendasikan saham-saham yang BENAR-BENAR AMAN, memiliki konfirmasi buyer kuat, dan berprobabilitas tinggi untuk memberikan keuntungan intraday (+1.5% s/d +3.5%) dengan risiko sekecil mungkin.

PRINSIP SELEKSI:
1. Bebas menentukan jumlah saham yang layak (bisa 1, 2, 4, atau berapapun), JANGAN membatasi kuota secara kaku.
2. Hindari saham yang rentan guyuran bandar (fake bid, distribusi terselubung, pom-pom).
3. Hanya rekomendasikan jika Anda yakin saham ini bisa memberi profit positif tanpa membahayakan modal akun (ai_score >= 75).
4. Berikan 'ai_score' (1-100), 'strategy_name', dan 'ai_reasoning' singkat (1-2 kalimat).
5. Urutkan dari ai_score tertinggi ke terendah.

Tugas Anda:
Analisis kandidat saham sore hari berikut ini (jam 15:35 WIB) secara mandiri dan komprehensif.
Pilihlah saham-saham yang BENAR-BENAR LAYAK dan berprobabilitas tinggi untuk naik 2% - 5% di pembukaan pasar besok pagi.

ATURAN PENTING JUMLAH SAHAM:
- JANGAN MEMBATASI JUMLAH SAHAM. Jumlah saham yang Anda rekomendasikan BEBAS (bisa 1, 2, 3, 4, 5, atau lebih) sesuai murni hasil analisa teknikal, bandarmologi, dan manajemen risiko Anda.
- Jika ada banyak saham yang memenuhi syarat dan aman dari jebakan bandar, pilih semuanya.
- Jika hanya sedikit atau bahkan hanya 1 yang benar-benar bagus, pilih yang bagus saja. Prioritas mutlak adalah profit konsisten tanpa risiko tinggi.

{memory_context}

DAFTAR KANDIDAT SAHAM HARI INI:
{json.dumps(candidates, indent=2)}

INSTRUKSI ANALISIS:
1. Periksa momentum kenaikan harga, kestabilan tick harga, dan potensi fake breakout.
2. Berikan 'ai_score' (1 - 100) untuk setiap saham.
3. Berikan 'ai_reasoning' singkat (maksimal 2 kalimat) dalam Bahasa Indonesia.
3. Hanya masukkan saham yang memiliki skor keyakinan tinggi (ai_score >= 75) ke dalam rekomendasi final.
4. Urutkan dari ai_score tertinggi ke terendah tanpa membatasi jumlah rekomendasi.

Kembalikan HANYA format JSON murni array of objects tanpa markdown:
[
  {{
    "ticker": "BBCA",
    "action": "BUY",
    "current_price": 9850,
    "target_price_1": 10150,
    "target_price_2": 10350,
    "stop_loss_price": 9600,
    "strategy_name": "BSJP 1 - Breakout Momentum",
    "ai_score": 92,
    "ai_reasoning": "Akumulasi volume solid di 15 menit penutupan, tidak ada tanda guyuran bandar."
  }}
]
"""

        logger.info("Mengirim data kandidat saham ke Gemini AI untuk analisis mendalam...")
        raw_response = await self.call_gemini(prompt)

        if raw_response:
            try:
                # Bersihkan format jika ada code block markdown
                clean_json = raw_response.strip()
                if clean_json.startswith("```json"):
                    clean_json = clean_json[7:]
                if clean_json.startswith("```"):
                    clean_json = clean_json[3:]
                if clean_json.endswith("```"):
                    clean_json = clean_json[:-3]

                analyzed_signals = json.loads(clean_json.strip())
                logger.info(f"Gemini AI berhasil memilih {len(analyzed_signals)} saham rekomendasi terbaik!")
                return analyzed_signals
            except Exception as e:
                logger.error(f"Gagal mem-parsing JSON Gemini AI: {e}. Menggunakan ranking cadangan.")

        return candidates

    async def reflect_on_closed_trade(self, trade_data: Dict[str, Any]):
        """
        FASE 2 (Post-Trade Self-Reflection):
        Mengevaluasi hasil trade pagi hari (WIN/LOSS), merumuskan 'Pelajaran Emas',
        dan menyimpannya ke tabel `ai_market_memories` agar AI makin pintar.
        """
        if not self.is_enabled():
            return

        ticker = trade_data["ticker"]
        outcome = trade_data["status"] # WIN / LOSS
        profit_pct = trade_data["profit_percent"]
        entry_p = trade_data["entry_price"]
        exit_p = trade_data["exit_price"]
        strategy = trade_data.get("strategy_name", "BSJP")

        prompt = f"""
Anda adalah AI Evaluator Trading Saham BEI.
Sebuah transaksi baru saja selesai dieksekusi dengan data berikut:
- Emiten: {ticker}
- Strategi: {strategy}
- Harga Beli: Rp {entry_p:,}
- Harga Jual: Rp {exit_p:,}
- Hasil: {outcome} ({profit_pct:+.2f}%)
- Alasan Exit: {trade_data.get('exit_reason', 'NORMAL')}

TUGAS:
1. Tulis 'analysis' (1-2 kalimat): Mengapa trade ini menghasilkan {outcome}?
2. Tulis 'lesson_learned' (1 kalimat aturan emas): Apa kaidah penting yang harus selalu diingat oleh bot di masa depan terkait pola saham seperti ini?

Kembalikan HANYA format JSON murni:
{{
  "analysis": "...",
  "lesson_learned": "..."
}}
"""
        logger.info(f"Gemini AI sedang melakukan Post-Mortem Reflection untuk trade {ticker} ({outcome})...")
        raw_response = await self.call_gemini(prompt)

        if raw_response:
            try:
                clean_json = raw_response.strip()
                if clean_json.startswith("```json"): clean_json = clean_json[7:]
                if clean_json.startswith("```"): clean_json = clean_json[3:]
                if clean_json.endswith("```"): clean_json = clean_json[:-3]

                res = json.loads(clean_json.strip())
                analysis = res.get("analysis", f"Trade {outcome} dengan profit {profit_pct:.2f}%")
                lesson = res.get("lesson_learned", f"Pertahankan disiplin target profit dan batas risiko pada {ticker}.")

                # Simpan ke Database Memori Permanen
                save_ai_memory(
                    ticker=ticker,
                    strategy_name=strategy,
                    trade_outcome=outcome,
                    profit_percent=profit_pct,
                    entry_price=entry_p,
                    exit_price=exit_p,
                    ai_analysis=analysis,
                    lesson_learned=lesson
                )
                logger.info(f"✅ Pelajaran baru untuk #{ticker} berhasil diabadikan ke Buku Pintar AI!")
            except Exception as e:
                logger.error(f"Gagal mencatat memori AI: {e}")
