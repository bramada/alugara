import os
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from fastapi import Request, HTTPException, Depends
from cryptography.fernet import Fernet
from loguru import logger

from src.storage.db import (
    get_setting,
    set_setting,
    save_session,
    get_session,
    delete_session,
    clean_expired_sessions
)

def _get_fernet() -> Fernet:
    """Mengambil atau menginisialisasi Fernet AES-256 key untuk enkripsi credential lokal"""
    key = get_setting("master_app_secret")
    if not key:
        key = Fernet.generate_key().decode('utf-8')
        set_setting("master_app_secret", key)
    return Fernet(key.encode('utf-8'))

def encrypt_value(plain_text: str) -> str:
    """Enkripsi teks sensitif (Trading PIN, API Key, Token) dengan AES-256"""
    if not plain_text:
        return ""
    try:
        f = _get_fernet()
        enc = f.encrypt(plain_text.encode('utf-8')).decode('utf-8')
        return f"enc::{enc}"
    except Exception as e:
        logger.error(f"Gagal mengenkripsi data: {e}")
        return plain_text

def decrypt_value(cipher_text: str) -> str:
    """Dekripsi teks terenkripsi"""
    if not cipher_text:
        return ""
    if not cipher_text.startswith("enc::"):
        return cipher_text  # Belum dienkripsi (legacy plain text)
    try:
        f = _get_fernet()
        raw = cipher_text[5:]
        decrypted = f.decrypt(raw.encode('utf-8')).decode('utf-8')
        return decrypted
    except Exception as e:
        logger.error(f"Gagal mendekripsi data: {e}")
        return ""

def is_master_password_configured() -> bool:
    """Memeriksa apakah Master Password / PIN aplikasi sudah dibuat"""
    pwd_hash = get_setting("auth_password_hash")
    return bool(pwd_hash and len(pwd_hash) > 10)

def set_master_password(password: str) -> bool:
    """Menyimpan Master Password dengan PBKDF2-HMAC-SHA256 (100,000 iterasi + salt)"""
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100_000
    ).hex()
    set_setting("auth_password_hash", pwd_hash)
    set_setting("auth_password_salt", salt)
    return True

def verify_master_password(password: str) -> bool:
    """Verifikasi Master Password yang dimasukkan trader"""
    stored_hash = get_setting("auth_password_hash")
    salt = get_setting("auth_password_salt")
    if not stored_hash or not salt:
        return False
    computed_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100_000
    ).hex()
    return secrets.compare_digest(computed_hash, stored_hash)

def create_user_session(remember: bool = False) -> Tuple[str, datetime]:
    """Membuat sesi token autentikasi baru"""
    clean_expired_sessions()
    token = secrets.token_urlsafe(32)
    duration_days = 30 if remember else 1
    expires_at = datetime.now(timezone.utc) + timedelta(days=duration_days)
    save_session(token, expires_at.isoformat())
    return token, expires_at

def validate_user_session(token: str) -> bool:
    """Memeriksa validitas sesi token"""
    if not token:
        return False
    session = get_session(token)
    if not session:
        return False
    try:
        expires_at = datetime.fromisoformat(session["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at > datetime.now(timezone.utc):
            return True
        else:
            delete_session(token)
            return False
    except Exception:
        delete_session(token)
        return False

def get_auth_token_from_request(request: Request) -> Optional[str]:
    """Mengekstrak token autentikasi dari Header atau Cookie"""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ")[1].strip()

    cookie_token = request.cookies.get("alugara_session")
    if cookie_token:
        return cookie_token.strip()

    query_token = request.query_params.get("token")
    if query_token:
        return query_token.strip()

    return None

async def require_auth(request: Request) -> str:
    """FastAPI Dependency untuk melindungi endpoint trading & dashboard"""
    if not is_master_password_configured():
        raise HTTPException(
            status_code=401,
            detail="Aplikasi belum dikonfigurasi. Silakan buat Master Password terlebih dahulu."
        )

    token = get_auth_token_from_request(request)
    if not token or not validate_user_session(token):
        raise HTTPException(
            status_code=401,
            detail="Sesi tidak valid atau telah kedaluwarsa. Silakan login kembali."
        )
    return token
def delete_user_session(token: str):
    """Menghapus sesi token autentikasi (logout)"""
    delete_session(token)
