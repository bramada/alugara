
def _sanitize_discuss_reply(text: str) -> str:
    """Membersihkan pesan tips / embel-embel evo secara tuntas dari respon AI"""
    if not text:
        return ""
    import re
    cleaned = text.strip()
    # Hapus baris/paragraf penutup yang mengandung tips evo
    lines = cleaned.split("\n")
    filtered_lines = []
    for line in lines:
        l_lower = line.lower()
        if "evo:" in l_lower and ("awalan" in l_lower or "buku pintar" in l_lower or "catatan" in l_lower or "tip" in l_lower or "ingat" in l_lower or "memori" in l_lower):
            continue
        filtered_lines.append(line)
    
    res = "\n".join(filtered_lines).strip()
    
    # Hapus kurung penutup sisa jika ada
    res = re.sub(r'\n*\s*\([\s\S]*?evo:[\s\S]*?\)\s*$', '', res, flags=re.IGNORECASE).strip()
    res = re.sub(r'\n*\s*\*\*[\s\S]*?evo:[\s\S]*?\*\*\s*$', '', res, flags=re.IGNORECASE).strip()
    res = re.sub(r'\n*\s*\*[\s\S]*?evo:[\s\S]*?\*\s*$', '', res, flags=re.IGNORECASE).strip()
    return res

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
        self._key_index = 0

    def get_api_key(self) -> str:
        from src.core.security import decrypt_value
        stored = get_setting("gemini_api_key")
        if stored:
            decrypted = decrypt_value(stored)
            if decrypted:
                return decrypted
        return settings.GEMINI_API_KEY or ""

    def get_all_api_keys(self) -> List[str]:
        """Mengambil seluruh Gemini API Key aktif dari database pool (beserta fallback ke single key)"""
        from src.storage.db import get_gemini_api_keys
        try:
            keys_data = get_gemini_api_keys(active_only=True, decrypt=True)
            active_keys = [k["api_key"] for k in keys_data if k.get("api_key")]
            if active_keys:
                return active_keys
        except Exception as e:
            logger.debug(f"Gagal mengambil multi-keys: {e}")

        single = self.get_api_key()
        return [single] if single else []

    def get_model(self) -> str:
        return get_setting("gemini_model") or settings.GEMINI_MODEL or "gemini-flash-latest"

    def is_enabled(self) -> bool:
        enabled_setting = get_setting("ai_reasoning_enabled", str(settings.AI_REASONING_ENABLED))
        return enabled_setting.lower() == "true" and bool(self.get_all_api_keys())

    async def test_connection(self, api_key: Optional[str] = None, model: Optional[str] = None) -> tuple[bool, str]:
        """Uji koneksi ke Google Gemini API dengan auto-fallback tangguh jika model spesifik sedang 503/429/timeout"""
        keys = [api_key] if api_key else self.get_all_api_keys()
        if not keys:
            return False, "API Key kosong. Silakan masukkan Gemini API Key Anda."

        key = keys[0]
        target_model = model or self.get_model()

        # Prioritas model: target model, lalu model super-cepat & stabil (flash-lite, 3.6-flash, flash-latest)
        models_to_try = [target_model]
        for fallback in ["gemini-flash-lite-latest", "gemini-3.6-flash", "gemini-flash-latest"]:
            if fallback not in models_to_try:
                models_to_try.append(fallback)

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
                "maxOutputTokens": 20,
            }
        }

        last_err = ""
        for m in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}"
            try:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    res = await client.post(url, json=payload)
                    if res.status_code == 200:
                        log_ai_usage(model=m, prompt_tokens=15, response_tokens=15, status_code=200, is_success=True)
                        if m == target_model:
                            return True, f"Koneksi ke Google Gemini AI ({m}) aktif & siap melayani analisis saham!"
                        else:
                            return True, f"API Key Valid! Model '{target_model}' sedang antre/timeout di Google, otomatis fallback ke '{m}'."

                    err_json = res.json() if "application/json" in res.headers.get("content-type", "") else {}
                    err_msg = err_json.get("error", {}).get("message", res.text)
                    
                    # Jika API Key memang salah menurut Google, jangan fallback
                    if res.status_code in [400, 403] and ("API_KEY_INVALID" in err_msg or "not valid" in err_msg.lower()):
                        return False, f"API Key tidak valid (Ditolak Google): {err_msg}"
                    
                    last_err = f"Model {m} status {res.status_code}: {err_msg}"
            except Exception as e:
                err_detail = str(e) or type(e).__name__
                last_err = f"Model {m} ({err_detail})"

        return False, f"Gagal menghubungi server Gemini: {last_err}"

    async def call_gemini(self, prompt: str, api_key: Optional[str] = None, model: Optional[str] = None) -> Optional[str]:
        """
        Memanggil Gemini API dengan fitur:
        1. Multi-API Key Round-Robin & Failover otomatis saat kuota limit (429/403/503)
        2. Multi-Model Fallback jika model tertentu sedang lonjakan trafik
        3. Token output yang hemat & efisien (maxOutputTokens: 512)
        """
        from src.storage.db import record_gemini_key_usage

        keys = [api_key] if api_key else self.get_all_api_keys()
        if not keys:
            return None

        target_model = model or self.get_model()
        
        # Bangun urutan model fallback: Utamakan model super-cepat & stabil
        models_to_try = [target_model]
        for fb in ["gemini-flash-lite-latest", "gemini-3.6-flash", "gemini-flash-latest"]:
            if fb not in models_to_try:
                models_to_try.append(fb)

        # Rotasi Round-Robin antar API Key yang tersedia
        num_keys = len(keys)
        start_idx = self._key_index % num_keys
        self._key_index = (self._key_index + 1) % num_keys
        ordered_keys = [keys[(start_idx + i) % num_keys] for i in range(num_keys)]

        for current_key in ordered_keys:
            masked_key = (current_key[:8] + "..." + current_key[-4:]) if len(current_key) > 12 else "KEY"
            for m in models_to_try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={current_key}"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.2,
                        "maxOutputTokens": 512,  # Irit kuota & respon cepat
                    }
                }
                try:
                    # Timeout 6.0 detik: jika model sedang lag di Google, cepat beralih ke model fallback
                    async with httpx.AsyncClient(timeout=6.0) as client:
                        res = await client.post(url, json=payload)
                        usage_meta = res.json().get("usageMetadata", {}) if res.status_code == 200 else {}
                        p_tok = usage_meta.get("promptTokenCount", 0)
                        r_tok = usage_meta.get("candidatesTokenCount", 0)
                        log_ai_usage(model=m, prompt_tokens=p_tok, response_tokens=r_tok, status_code=res.status_code, is_success=(res.status_code == 200))

                        if res.status_code == 200:
                            record_gemini_key_usage(current_key, is_success=True)
                            data = res.json()
                            candidates = data.get("candidates", [])
                            if candidates:
                                return candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        elif res.status_code in [429, 403]:
                            logger.warning(f"Gemini API ({m}) limit/error ({res.status_code}) pada key ({masked_key}). Mencoba model berikutnya...")
                        elif res.status_code == 503:
                            logger.warning(f"Gemini API ({m}) overload (503). Mencoba model fallback berikutnya...")
                        else:
                            logger.warning(f"Gemini API ({m}) status {res.status_code}, mencoba fallback model berikutnya...")
                except Exception as e:
                    err_name = type(e).__name__
                    log_ai_usage(model=m, status_code=500, is_success=False)
                    logger.warning(f"Gemini API ({m}) {err_name}, mencoba model fallback berikutnya...")

            record_gemini_key_usage(current_key, is_success=False)

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
                    reply = _sanitize_discuss_reply(data.get("response_to_user", f"Kaidah baru untuk #{ticker} berhasil dipelajari dan disimpan ke Buku Pintar AI."))

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
- DILARANG menambahkan pesan tips, catatan pengingat, atau embel-embel tentang awalan 'evo:' / Buku Pintar di akhir jawaban. Jawab hanya apa yang ditanyakan secara bersih dan fokus.
"""
            raw_res = await self.call_gemini(prompt)
            if raw_res:
                return {
                    "success": True,
                    "reply": _sanitize_discuss_reply(raw_res.strip()),
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
        Menganalisis Top 5 kandidat saham, menyaring jebakan bandar,
        memberi skor keyakinan AI (1-100), dan memilih saham yang benar-benar layak.
        Prompt dioptimasi super irit token.
        """
        if not candidates:
            return []

        # Batasi tegas hanya TOP 5 kandidat untuk efisiensi kuota API
        candidates = candidates[:5]

        if not self.is_enabled():
            logger.info("Gemini AI reasoning nonaktif/tanpa API Key. Menggunakan ranking kuantitatif standar.")
            return candidates

        # 1. Ambil 3 Memori Terpenting Saja (Hemat Token RAG)
        past_memories = get_top_ai_memories(limit=3)
        memory_context = ""
        if past_memories:
            memory_context = "BUKU PINTAR ATURAN:\n" + "\n".join([f"- #{m['ticker']}: {m['lesson_learned']}" for m in past_memories])

        # Minifikasi data kandidat (hanya atribut esensial, tanpa whitespace berlebih)
        compact_candidates = [
            {
                "ticker": c.get("ticker"),
                "price": c.get("current_price") or c.get("price"),
                "change_pct": round(c.get("change_percent", 0), 2)
            }
            for c in candidates
        ]

        prompt = f"""Sebagai Chief Risk Officer IDX Alugara Auto-Trade, evaluasi Top {len(compact_candidates)} kandidat saham berikut.
Filosofi: Cuan aman (+1.5% s/d +3.5%), anti-jebakan bandar (fake bid/pom-pom).
Hanya pilih yang benar-benar layak (ai_score >= 75).

{memory_context}

KANDIDAT:
{json.dumps(compact_candidates)}

KEMBALIKAN HANYA format JSON murni array of objects:
[
  {{
    "ticker": "BBCA",
    "action": "BUY",
    "current_price": 9850,
    "target_price_1": 10150,
    "target_price_2": 10350,
    "stop_loss_price": 9600,
    "strategy_name": "Momentum Breakout",
    "ai_score": 85,
    "ai_reasoning": "Akumulasi buyer solid tanpa tekanan guyuran."
  }}
]"""
        logger.info("Mengirim data Top 5 kandidat saham ke Gemini AI (Prompt Ringkas & Irit Token)...")
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
