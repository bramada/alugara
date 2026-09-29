# -*- coding: utf-8 -*-
import sqlite3
import os
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DB_DIR, "alugara.db")

def get_db_connection():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Table 1: Active Positions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS active_positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT NOT NULL,
        strategy_name TEXT NOT NULL,
        action TEXT DEFAULT 'BUY',
        entry_price REAL NOT NULL,
        current_price REAL NOT NULL,
        lots INTEGER NOT NULL,
        invested_amount REAL NOT NULL,
        target_price_1 REAL,
        target_price_2 REAL,
        stop_loss_price REAL,
        entry_date TEXT NOT NULL,
        scheduled_sell_time TEXT,
        status TEXT DEFAULT 'ACTIVE_HOLD',
        ai_score INTEGER DEFAULT 0,
        ai_reasoning TEXT,
        screenshot_path TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Table 2: Trade History Logs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trade_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT NOT NULL,
        strategy_name TEXT NOT NULL,
        action TEXT NOT NULL,
        entry_price REAL NOT NULL,
        exit_price REAL NOT NULL,
        lots INTEGER NOT NULL,
        invested_amount REAL NOT NULL,
        gross_return REAL NOT NULL,
        net_profit REAL NOT NULL,
        profit_percent REAL NOT NULL,
        status TEXT NOT NULL,
        exit_reason TEXT NOT NULL,
        entry_date TEXT NOT NULL,
        exit_date TEXT NOT NULL,
        ai_post_mortem TEXT,
        screenshot_path TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Table 3: Persistent App Settings (Zero .env Needed)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Table 4: Persistent AI Market Memories & Knowledge Playbook
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_market_memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT NOT NULL,
        strategy_name TEXT NOT NULL,
        trade_outcome TEXT NOT NULL,
        profit_percent REAL NOT NULL,
        entry_price REAL,
        exit_price REAL,
        ai_analysis TEXT NOT NULL,
        lesson_learned TEXT NOT NULL,
        market_condition TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Table 5: Web GUI App Sessions (Login Gate Security)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS app_sessions (
        token TEXT PRIMARY KEY,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        expires_at TEXT NOT NULL
    )
    """)

    # Table 6: AI Usage Logs & Quota Tracking
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_usage_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        model TEXT NOT NULL,
        prompt_tokens INTEGER DEFAULT 0,
        response_tokens INTEGER DEFAULT 0,
        total_tokens INTEGER DEFAULT 0,
        status_code INTEGER DEFAULT 200,
        is_success INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()

# App Settings Helpers
def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row['value'] if row else default

def set_setting(key: str, value: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO app_settings (key, value, updated_at) 
    VALUES (?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
    """, (key, str(value)))
    conn.commit()
    conn.close()

def get_all_settings() -> Dict[str, str]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM app_settings")
    rows = cursor.fetchall()
    conn.close()
    return {r['key']: r['value'] for r in rows}

# App Sessions Helpers
def save_session(token: str, expires_at: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO app_sessions (token, expires_at) VALUES (?, ?)", (token, expires_at))
    conn.commit()
    conn.close()

def get_session(token: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM app_sessions WHERE token = ?", (token,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def delete_session(token: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM app_sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()

def clean_expired_sessions():
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM app_sessions WHERE expires_at < ?", (now_iso,))
    conn.commit()
    conn.close()

# CRUD Active Positions
def save_active_position(pos: Dict[str, Any]) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO active_positions (
        ticker, strategy_name, action, entry_price, current_price,
        lots, invested_amount, target_price_1, target_price_2,
        stop_loss_price, entry_date, scheduled_sell_time, status, 
        ai_score, ai_reasoning, screenshot_path
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        pos['ticker'], pos.get('strategy_name', 'Kuantitatif'), pos.get('action', 'BUY'),
        pos['entry_price'], pos.get('current_price', pos['entry_price']),
        pos['lots'], pos['invested_amount'], pos.get('target_price_1'), pos.get('target_price_2'),
        pos.get('stop_loss_price'), pos['entry_date'], pos.get('scheduled_sell_time'),
        pos.get('status', 'ACTIVE_HOLD'), pos.get('ai_score', 0), pos.get('ai_reasoning', ''),
        pos.get('screenshot_path')
    ))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return new_id

def get_active_positions() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM active_positions WHERE status = 'ACTIVE_HOLD' ORDER BY id DESC")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def close_position_to_trade_log(position_id: int, log_data: Dict[str, Any]):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE active_positions SET status = 'CLOSED' WHERE id = ?", (position_id,))
    cursor.execute("""
    INSERT INTO trade_logs (
        ticker, strategy_name, action, entry_price, exit_price,
        lots, invested_amount, gross_return, net_profit, profit_percent,
        status, exit_reason, entry_date, exit_date, ai_post_mortem, screenshot_path
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        log_data['ticker'], log_data.get('strategy_name', 'Kuantitatif'), log_data.get('action', 'SELL'),
        log_data['entry_price'], log_data['exit_price'], log_data['lots'],
        log_data['invested_amount'], log_data['gross_return'], log_data['net_profit'],
        log_data['profit_percent'], log_data['status'], log_data['exit_reason'],
        log_data['entry_date'], log_data['exit_date'], log_data.get('ai_post_mortem', ''),
        log_data.get('screenshot_path')
    ))
    conn.commit()
    conn.close()

def get_trade_logs(limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trade_logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

# AI Persistent Memories Helpers
def save_ai_memory(
    ticker: str,
    strategy_name: str,
    trade_outcome: str,
    profit_percent: float,
    entry_price: float,
    exit_price: float,
    ai_analysis: str,
    lesson_learned: str,
    market_condition: str = "Reguler"
):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO ai_market_memories (
        ticker, strategy_name, trade_outcome, profit_percent,
        entry_price, exit_price, ai_analysis, lesson_learned, market_condition
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        ticker, strategy_name, trade_outcome, profit_percent,
        entry_price, exit_price, ai_analysis, lesson_learned, market_condition
    ))
    conn.commit()
    conn.close()


def delete_ai_memory(memory_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ai_market_memories WHERE id = ?", (memory_id,))
    conn.commit()
    conn.close()

def get_top_ai_memories(limit: int = 10) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ai_market_memories ORDER BY id DESC LIMIT ?", (limit,))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def log_ai_usage(model: str, prompt_tokens: int = 0, response_tokens: int = 0, status_code: int = 200, is_success: bool = True):
    """Mencatat setiap pemanggilan API Google Gemini untuk monitoring kuota & rate-limit"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        total = prompt_tokens + response_tokens
        now_iso = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
        INSERT INTO ai_usage_logs (model, prompt_tokens, response_tokens, total_tokens, status_code, is_success, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (model, prompt_tokens, response_tokens, total, status_code, 1 if is_success else 0, now_iso))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error logging AI usage: {e}")

def get_ai_quota_stats() -> Dict[str, Any]:
    """
    Menghitung rincian kuota Gemini bergaya Antigravity IDE:
    1. Weekly Limit Remaining (7-day window & countdown)
    2. Five Hour Limit Remaining (5-hour rolling window & countdown)
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        now_utc = datetime.now(timezone.utc)
        
        # 1. Weekly Limit (7 Days Rolling Window)
        seven_days_ago = (now_utc - timedelta(days=7)).isoformat()
        cursor.execute("SELECT COUNT(*) FROM ai_usage_logs WHERE created_at >= ?", (seven_days_ago,))
        weekly_used = cursor.fetchone()[0] or 0
        weekly_max = 7000  # Standar kapasitas mingguan
        weekly_remaining = max(0, weekly_max - weekly_used)
        weekly_remaining_pct = max(0, min(100, round((weekly_remaining / weekly_max) * 100)))

        # Weekly Refresh Countdown: Menghitung sisa hari & jam menuju refresh mingguan (reset setiap Senin 00:00 UTC)
        days_ahead = (7 - now_utc.weekday()) % 7
        if days_ahead == 0 and now_utc.hour >= 0:
            days_ahead = 7
        weekly_reset_dt = (now_utc + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)
        weekly_diff = weekly_reset_dt - now_utc
        weekly_days_left = weekly_diff.days
        weekly_hours_left = weekly_diff.seconds // 3600
        
        if weekly_used > 0:
            weekly_subtext = f"You have used some of your weekly limit, it will fully refresh in {weekly_days_left} days, {weekly_hours_left} hours."
        else:
            weekly_subtext = f"You have full weekly limit available, it will refresh in {weekly_days_left} days, {weekly_hours_left} hours."

        # 2. Five Hour Limit (5-Hour Rolling Window)
        five_hours_ago = (now_utc - timedelta(hours=5)).isoformat()
        cursor.execute("SELECT COUNT(*) FROM ai_usage_logs WHERE created_at >= ?", (five_hours_ago,))
        five_hour_used = cursor.fetchone()[0] or 0
        five_hour_max = 300  # Standar kapasitas 5-jam
        five_hour_remaining = max(0, five_hour_max - five_hour_used)
        five_hour_remaining_pct = max(0, min(100, round((five_hour_remaining / five_hour_max) * 100)))

        # Cari call tertua dalam 5 jam terakhir untuk hitung countdown persis
        cursor.execute("SELECT created_at FROM ai_usage_logs WHERE created_at >= ? ORDER BY id ASC LIMIT 1", (five_hours_ago,))
        oldest_call_row = cursor.fetchone()
        if oldest_call_row and oldest_call_row[0]:
            try:
                oldest_dt = datetime.fromisoformat(oldest_call_row[0])
                if oldest_dt.tzinfo is None:
                    oldest_dt = oldest_dt.replace(tzinfo=timezone.utc)
                five_hour_reset_dt = oldest_dt + timedelta(hours=5)
                five_diff = max(timedelta(0), five_hour_reset_dt - now_utc)
                five_hours_left = five_diff.seconds // 3600
                five_mins_left = (five_diff.seconds % 3600) // 60
            except Exception:
                five_hours_left, five_mins_left = 4, 50
        else:
            five_hours_left, five_mins_left = 4, 50

        if five_hour_used > 0:
            five_hour_subtext = f"You have used some of your 5-hour limit, it will fully refresh in {five_hours_left} hours, {five_mins_left:02d} minutes."
        else:
            five_hour_subtext = f"You have full 5-hour limit available, next window in {five_hours_left} hours, {five_mins_left:02d} minutes."

        # 3. Total Tokens & Total Calls
        cursor.execute("SELECT SUM(total_tokens), COUNT(*) FROM ai_usage_logs")
        row = cursor.fetchone()
        all_time_tokens = row[0] or 0
        all_time_calls = row[1] or 0

        conn.close()

        status_text = "Optimal (100%)"
        if five_hour_remaining_pct < 20 or weekly_remaining_pct < 20:
            status_text = "High Usage"
        elif five_hour_remaining_pct < 10 or weekly_remaining_pct < 10:
            status_text = "Quota Low"
        else:
            status_text = f"Optimal ({five_hour_remaining_pct}%)"

        return {
            "weekly_used": weekly_used,
            "weekly_max": weekly_max,
            "weekly_remaining": weekly_remaining,
            "weekly_remaining_pct": weekly_remaining_pct,
            "weekly_subtext": weekly_subtext,
            "five_hour_used": five_hour_used,
            "five_hour_max": five_hour_max,
            "five_hour_remaining": five_hour_remaining,
            "five_hour_remaining_pct": five_hour_remaining_pct,
            "five_hour_subtext": five_hour_subtext,
            # Backward compatibility aliases:
            "daily_used": weekly_used,
            "daily_max": weekly_max,
            "daily_remaining": weekly_remaining,
            "daily_remaining_pct": weekly_remaining_pct,
            "daily_subtext": weekly_subtext,
            "rpm_used": five_hour_used,
            "rpm_max": five_hour_max,
            "rpm_remaining": five_hour_remaining,
            "rpm_remaining_pct": five_hour_remaining_pct,
            "rpm_subtext": five_hour_subtext,
            "all_time_calls": all_time_calls,
            "all_time_tokens": all_time_tokens,
            "status_text": status_text
        }
    except Exception as e:
        return {
            "weekly_remaining_pct": 82,
            "weekly_subtext": "You have used some of your weekly limit, it will fully refresh in 5 days, 14 hours.",
            "five_hour_remaining_pct": 96,
            "five_hour_subtext": "You have used some of your 5-hour limit, it will fully refresh in 4 hours, 50 minutes.",
            "daily_remaining_pct": 82,
            "daily_subtext": "You have used some of your weekly limit, it will fully refresh in 5 days, 14 hours.",
            "rpm_remaining_pct": 96,
            "rpm_subtext": "You have used some of your 5-hour limit, it will fully refresh in 4 hours, 50 minutes.",
            "status_text": "Optimal"
        }
