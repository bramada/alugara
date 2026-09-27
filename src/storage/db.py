import sqlite3
import os
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

DB_DIR = os.path.abspath("data")
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

# CRUD Active Positions
def save_active_position(pos: Dict[str, Any]) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO active_positions (
        ticker, strategy_name, action, entry_price, current_price,
        lots, invested_amount, target_price_1, target_price_2,
        stop_loss_price, entry_date, scheduled_sell_time, status, screenshot_path
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        pos['ticker'], pos.get('strategy_name', 'Kuantitatif'), pos.get('action', 'BUY'),
        pos['entry_price'], pos.get('current_price', pos['entry_price']),
        pos['lots'], pos['invested_amount'], pos.get('target_price_1'), pos.get('target_price_2'),
        pos.get('stop_loss_price'), pos['entry_date'], pos.get('scheduled_sell_time'),
        pos.get('status', 'ACTIVE_HOLD'), pos.get('screenshot_path')
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
        status, exit_reason, entry_date, exit_date, screenshot_path
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        log_data['ticker'], log_data.get('strategy_name', 'Kuantitatif'), log_data.get('action', 'SELL'),
        log_data['entry_price'], log_data['exit_price'], log_data['lots'],
        log_data['invested_amount'], log_data['gross_return'], log_data['net_profit'],
        log_data['profit_percent'], log_data['status'], log_data['exit_reason'],
        log_data['entry_date'], log_data['exit_date'], log_data.get('screenshot_path')
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
