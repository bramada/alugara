# -*- coding: utf-8 -*-
import os
import json
import httpx
from typing import List, Dict, Any, Optional
from loguru import logger
from src.config.settings import settings
from src.storage.db import (
    get_setting,
    get_top_ai_memories,
    save_ai_memory,
    log_ai_usage,
    get_active_positions
)

class GeminiAnalyzer:
    """
    Mesin Analisis AI Mendalam berbasis Google Gemini
    Dilengkapi Multi-Model Auto-Fallback, Continuous Coaching Memory ('evo:'), dan Long-Term Memory Playbook.
    """

    # Model resmi Google AI Studio berkinerja tinggi
    RECOMMENDED_MODELS = [
        "gemini-flash-latest",
        "gemini-3.8-flash",
        "gemini-3.6-flash",
        "gemini-flash-lite-latest",
        "gemini-3.7-flash",
        "gemini-pro-latest"
    ]

    def __init__(self):
        pass

    def get_api_key(self) -> str:
        from src.core.security import decrypt_value
        stored = get_setting("gemini_api_key")
        if stored:
            decrypted = decrypt_value(stored)
            if decrypted:
                return decrypted
        return settings.GEMINI_API_KEY or ""

    def get_model(self) -> str:
        return get_setting("gemini_model") or settings.GEMINI_MODEL or "gemini-flash-latest"

    def is_enabled(self) -> bool:
        enabled_setting = get_setting("ai_reasoning_enabled", str(settings.AI_REASONING_ENABLED))
        return enabled_setting.lower() == "true" and bool(self.get_api_key())

    async def test_connection(self, api_key: Optional[str] = None, model: Optional[str] = None) -> tuple[bool, str]:
        """Uji koneksi ke Google Gemini API dengan auto-fallback jika model spesifik sedang 503/429"""
        key = api_key or self.get_api_key()
        if not key:
            return False, "API Key kosong. Silakan masukkan Gemini API Key Anda."

        target_model = model or self.get_model()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent?key={key}"

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": "Halo Gemini, verifikasi koneksi sistem Alugara IDX Auto-Trading."}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 256,
            }
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    log_ai_usage(model=target_model, prompt_tokens=15, response_tokens=15, status_code=200, is_success=True)
                    return True, f"Koneksi ke Google Gemini AI ({target_model}) aktif & siap melayani analisis saham!"
                
                # Jika model utama mengalami 503 (High Demand) atau 429 (Rate Limit), uji coba fallback
                if res.status_code in [503, 429]:
                    for fallback in ["gemini-flash-latest", "gemini-3.8-flash", "gemini-flash-lite-latest"]:
                        if fallback == target_model:
                            continue
                        fb_url = f"https://generativelanguage.googleapis.com/v1beta/models/{fallback}:generateContent?key={key}"
                        fb_res = await client.post(fb_url, json=payload)
                        if fb_res.status_code == 200:
                            log_ai_usage(model=fallback, prompt_tokens=15, response_tokens=15, status_code=200, is_success=True)
                            return True, f"API Key Valid! Model '{target_model}' sedang lonjakan trafik ({res.status_code}). Sistem otomatis mem-fallback ke '{fallback}' sehingga trading tetap aman."
                
                err_json = res.json() if "application/json" in res.headers.get("content-type", "") else {}
                err_msg = err_json.get("error", {}).get("message", res.text)
                return False, f"Google Gemini Error ({res.status_code}): {err_msg}"
        except Exception as e:
            return False, f"Gagal menghubungi server Gemini: {e}"

    async def call_gemini(self, prompt: str, api_key: Optional[str] = None, model: Optional[str] = None) -> Optional[str]:
        key = api_key or self.get_api_key()
        if not key:
            return None

        target_model = model or self.get_model()
        
        # Bangun urutan model fallback
        models_to_try = [target_model]
        for fb in ["gemini-flash-latest", "gemini-3.8-flash", "gemini-3.6-flash", "gemini-flash-lite-latest"]:
            if fb not in models_to_try:
                models_to_try.append(fb)

        for m in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 2048,
                }
            }
            try:
                async with httpx.AsyncClient(timeout=25.0) as client:
                    res = await client.post(url, json=payload)
                    usage_meta = res.json().get("usageMetadata", {}) if res.status_code == 200 else {}
                    p_tok = usage_meta.get("promptTokenCount", 0)
                    r_tok = usage_meta.get("candidatesTokenCount", 0)
                    log_ai_usage(model=m, prompt_tokens=p_tok, response_tokens=r_tok, status_code=res.status_code, is_success=(res.status_code == 200))

                    if res.status_code == 200:
                        data = res.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            return candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    else:
                        logger.warning(f"Gemini API ({m}) status {res.status_code}, mencoba fallback model berikutnya...")
            except Exception as e:
                log_ai_usage(model=m, status_code=500, is_success=False)
                logger.warning(f"Gemini API ({m}) exception: {e}")

        return None

    async def discuss_and_evolve(
        self,
        user_message: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
        context_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Menu Discuss & AI Coaching:
        - Jika diawali 'evo:' -> Mengajari AI kaidah trading baru, otomatis disimpan ke Buku Pintar AI.
        - Jika tanpa 'evo:' -> Diskusi & tanya jawab cerdas tanpa menyimpan ke memori.
        """
        if not self.is_enabled():
            return {
                "success": False,
                "reply": "Google Gemini AI belum aktif atau API Key belum diisi. Silakan masukkan Gemini API Key di menu Pengaturan & Keamanan terlebih dahulu.",
                "is_evolved": False
            }

        msg = user_message.strip()
        is_evo = msg.lower().startswith("evo:")

        if is_evo:
            # Mode Coaching / Mengajari AI
            instruction = msg[4:].strip()
            prompt = f"""
Anda adalah Alugara AI Trading Engine untuk Bursa Efek Indonesia (IDX).
Pengguna (Master Trader) sedang mengajari Anda kaidah/pantangan trading baru melalui instruksi coaching 'evo:'.

INSTRUKSI PENGGUNA:
"{instruction}"

TUGAS ANDA:
1. Pahami instruksi ini secara mendalam untuk diterapkan pada evaluasi & penyaringan saham IDX.
2. Tentukan 'ticker' emiten terkait (misal "BBCA", "ANTM", atau "GLOBAL" jika berlaku untuk semua saham).
3. Tentukan 'strategy_name' (misal "Evo: Filter Bandar", "Evo: Price Action", atau nama strategi yang relevan).
4. Rumuskan 'lesson_learned' (1-2 kalimat tegas dan ringkas berisi aturan emas/pantangan yang wajib Anda patuhi saat trading).
5. Rumuskan 'ai_analysis' (penjelasan mengapa aturan ini penting dan bagaimana Anda akan menerapkannya saat menyaring saham).
6. Rumuskan 'response_to_user' (konfirmasi ramah dalam Bahasa Indonesia bahwa Anda telah menyerap aturan ini dan mengabadikannya ke Buku Pintar AI).

Kembalikan HANYA format JSON murni tanpa markdown:
{{
  "is_evolved": true,
  "ticker": "GLOBAL",
  "strategy_name": "Evo: Aturan Pengguna",
  "lesson_learned": "...",
  "ai_analysis": "...",
  "response_to_user": "..."
}}
"""
            raw_res = await self.call_gemini(prompt)
            if raw_res:
                try:
                    clean_json = raw_res.strip()
                    if clean_json.startswith("```json"): clean_json = clean_json[7:]
                    if clean_json.startswith("```"): clean_json = clean_json[3:]
                    if clean_json.endswith("```"): clean_json = clean_json[:-3]
                    
                    data = json.loads(clean_json.strip())
                    ticker = data.get("ticker", "GLOBAL").upper()
                    strategy = data.get("strategy_name", "Evo: Aturan Pengguna")
                    lesson = data.get("lesson_learned", instruction)
                    analysis = data.get("ai_analysis", f"Aturan diajarkan oleh pengguna: {instruction}")
                    reply = data.get("response_to_user", f"Kaidah baru untuk #{ticker} berhasil dipelajari dan disimpan ke Buku Pintar AI.")

                    # Simpan permanen ke tabel ai_market_memories
                    save_ai_memory(
                        ticker=ticker,
                        strategy_name=strategy,
                        trade_outcome="COACHED",
                        profit_percent=0.0,
                        entry_price=0.0,
                        exit_price=0.0,
                        ai_analysis=analysis,
                        lesson_learned=lesson,
                        market_condition="User Evo Rule"
                    )
                    logger.info(f"Kaidah Evo baru untuk #{ticker} berhasil disimpan ke Buku Pintar AI: {lesson}")

                    return {
                        "success": True,
                        "reply": reply,
                        "is_evolved": True,
                        "evolved_data": {
                            "ticker": ticker,
                            "strategy_name": strategy,
                            "lesson_learned": lesson,
                            "ai_analysis": analysis
                        }
                    }
                except Exception as e:
                    logger.error(f"Gagal memproses instruksi evo: {e}")
                    # Fallback simpan langsung
                    save_ai_memory(
                        ticker="GLOBAL",
                        strategy_name="Evo: Aturan Pengguna",
                        trade_outcome="COACHED",
                        profit_percent=0.0,
                        entry_price=0.0,
                        exit_price=0.0,
                        ai_analysis=instruction,
                        lesson_learned=instruction,
                        market_condition="User Evo Rule"
                    )
                    return {
                        "success": True,
                        "reply": f"Kaidah baru berhasil dicatat dan disimpan ke Buku Pintar AI: '{instruction}'",
                        "is_evolved": True,
                        "evolved_data": {
                            "ticker": "GLOBAL",
                            "strategy_name": "Evo: Aturan Pengguna",
                            "lesson_learned": instruction,
                            "ai_analysis": instruction
                        }
                    }
            return {
                "success": False,
                "reply": "Maaf, terjadi gangguan saat memproses instruksi evo ke Gemini AI. Silakan periksa koneksi atau API Key Anda.",
                "is_evolved": False
            }

        else:
            # Mode Diskusi / Q&A Standar (Tanpa Simpan ke Memori)
            history_text = ""
            if chat_history:
                for h in chat_history[-6:]:
                    role = "Pengguna" if h.get("role") == "user" else "Alugara AI"
                    history_text += f"{role}: {h.get('content')}\n"

            positions = get_active_positions()
            pos_summary = ", ".join([f"{p['ticker']} ({p['lots']} lot @ Rp {p['entry_price']:,})" for p in positions]) if positions else "Tidak ada (Cash 100%)"
            
            memories = get_top_ai_memories(limit=8)
            mem_summary = "\n".join([f"- [#{m['ticker']}]: {m['lesson_learned']}" for m in memories]) if memories else "Belum ada kaidah tercatat."

            prompt = f"""
Anda adalah Alugara AI Co-Pilot & Quantitative Trading Assistant untuk Bursa Efek Indonesia (IDX).
Karakter Anda: Cerdas, disiplin, berorientasi risiko modal (filosofi: cuan berapa pun asal aman dan konsisten).

KONTEKS SISTEM ALUGARA SAAT INI:
- Posisi Saham Aktif: {pos_summary}
- Kaidah di Buku Pintar AI:
{mem_summary}

RIWAYAT PERCAKAPAN:
{history_text}

PESAN PENGGUNA TERBARU:
"{msg}"

PETUNJUK JAWABAN:
- Jawablah dengan jelas, ringkas, profesional, dan to the point dalam Bahasa Indonesia.
- Jika pengguna bertanya tentang saham, berikan pandangan berbasis teknikal, volume, atau manajemen risiko yang baik.
- Anda dapat menyarankan penggunaan awalan 'evo:' jika pengguna ingin menyimpan aturan tertentu ke memori permanen bot.
"""
            raw_res = await self.call_gemini(prompt)
            if raw_res:
                return {
                    "success": True,
                    "reply": raw_res.strip(),
                    "is_evolved": False
                }
            return {
                "success": False,
                "reply": "Maaf, Gemini AI tidak dapat merespons saat ini. Coba periksa koneksi internet atau ganti model AI di menu Pengaturan.",
                "is_evolved": False
            }

    async def analyze_and_rank_candidates(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        FASE 1 (Pre-Trade AI Gatekeeper):
        Menganalisis daftar kandidat saham, menyaring jebakan bandar,
        memberi skor keyakinan AI (1-100), dan memilih saham-saham yang benar-benar layak.
        """
        if not candidates:
            return []

        if not self.is_enabled():
            logger.info("Gemini AI reasoning nonaktif/tanpa API Key. Menggunakan ranking kuantitatif standar.")
            return candidates

        # 1. Ambil Buku Pintar Memori Masa Lalu (RAG Memory Context)
        past_memories = get_top_ai_memories(limit=10)
        memory_context = ""
        if past_memories:
            memory_context = "BUKU PINTAR PENGALAMAN & ATURAN TRADE (RAG MEMORY):\n"
            for m in past_memories:
                memory_context += f"- [Pola #{m['ticker']} ({m['strategy_name']})]: {m['lesson_learned']}\n"

        prompt = f"""
Anda adalah Senior Quantitative Trader & Chief Risk Officer di Bursa Efek Indonesia (IDX) untuk sistem Auto-Trading Alugara.

FILOSOFI UTAMA TRADING:
"Cuan berapa persen pun asal tidak lose. Modal aman dan untung konsisten."

Tugas Anda:
Analisis secara real-time kandidat saham yang terdeteksi aktif di jam bursa ini.
Saring dan rekomendasikan saham-saham yang BENAR-BENAR AMAN, memiliki konfirmasi akumulasi buyer kuat, dan berprobabilitas tinggi untuk memberikan keuntungan (+1.5% s/d +3.5%) dengan risiko sekecil mungkin.

PRINSIP SELEKSI:
1. Bebas menentukan jumlah saham yang layak (bisa 1, 2, 4, atau berapapun), JANGAN membatasi kuota secara kaku.
2. Hindari saham yang rentan guyuran bandar (fake bid, distribusi terselubung, pom-pom).
3. Hanya rekomendasikan jika Anda yakin saham ini aman dan berpotensi naik (ai_score >= 75).
4. Berikan 'ai_score' (1-100), 'strategy_name', dan 'ai_reasoning' singkat (1-2 kalimat).
5. Patuhi semua aturan di Buku Pintar Pengalaman.
6. Urutkan dari ai_score tertinggi ke terendah.

{memory_context}

DAFTAR KANDIDAT SAHAM HARI INI:
{json.dumps(candidates, indent=2)}

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
        Mengevaluasi hasil trade (WIN/LOSS) dan menyimpannya ke tabel `ai_market_memories`.
        """
        if not self.is_enabled():
            return

        ticker = trade_data["ticker"]
        outcome = trade_data["status"]
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
                logger.info(f"Pelajaran baru untuk #{ticker} berhasil diabadikan ke Buku Pintar AI!")
            except Exception as e:
                logger.error(f"Gagal mencatat memori AI: {e}")
