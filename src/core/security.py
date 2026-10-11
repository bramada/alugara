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
    """Memeriksa apakah akun (username & password) sudah dibuat"""
    username = get_setting("auth_username")
    pwd_hash = get_setting("auth_password_hash")
    return bool(username and pwd_hash and len(pwd_hash) > 10)

def set_user_credentials(username: str, password: str) -> bool:
    """Menyimpan Username & Password dengan PBKDF2-HMAC-SHA256 (100,000 iterasi + salt)"""
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100_000
    ).hex()
    set_setting("auth_username", username.strip())
    set_setting("auth_password_hash", pwd_hash)
    set_setting("auth_password_salt", salt)
    return True

def verify_user_credentials(username: str, password: str) -> bool:
    """Verifikasi kombinasi Username dan Password"""
    stored_username = get_setting("auth_username")
    stored_hash = get_setting("auth_password_hash")
    salt = get_setting("auth_password_salt")
    if not stored_username or not stored_hash or not salt:
        return False

    if username.strip().lower() != stored_username.strip().lower():
        return False

    computed_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100_000
    ).hex()
    return secrets.compare_digest(computed_hash, stored_hash)

def verify_master_password(password: str) -> bool:
    """Verifikasi Password saat ini (untuk penggantian password di settings)"""
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

def delete_user_session(token: str):
    """Menghapus sesi token autentikasi (logout)"""
    delete_session(token)

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
            detail="Aplikasi belum memiliki akun. Silakan setup akun terlebih dahulu."
        )

    token = get_auth_token_from_request(request)
    if not token or not validate_user_session(token):
        raise HTTPException(
            status_code=401,
            detail="Sesi tidak valid atau telah kedaluwarsa. Silakan login kembali."
        )
    return token

def create_session_export_package(raw_json_str: str, passphrase: Optional[str] = None) -> dict:
    """
    Membungkus session state JSON ke dalam paket terenkripsi AES-256 Fernet.
    Jika passphrase diisi, menggunakan key PBKDF2HMAC (100.000 iterasi) + salt acak.
    Jika passphrase kosong, menggunakan _get_fernet() master key lokal.
    """
    import base64
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    clean_pwd = passphrase.strip() if passphrase and passphrase.strip() else None
    if clean_pwd:
        salt = os.urandom(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        derived_key = base64.urlsafe_b64encode(kdf.derive(clean_pwd.encode('utf-8')))
        f = Fernet(derived_key)
        encrypted_payload = f.encrypt(raw_json_str.encode('utf-8')).decode('utf-8')
        return {
            "app": "alugara",
            "type": "stockbit_session",
            "version": "1.0",
            "kdf": "pbkdf2_sha256",
            "salt": base64.b64encode(salt).decode('utf-8'),
            "payload": encrypted_payload,
            "exported_at": datetime.now(timezone.utc).isoformat()
        }
    else:
        f = _get_fernet()
        encrypted_payload = f.encrypt(raw_json_str.encode('utf-8')).decode('utf-8')
        return {
            "app": "alugara",
            "type": "stockbit_session",
            "version": "1.0",
            "kdf": "system_secret",
            "payload": encrypted_payload,
            "exported_at": datetime.now(timezone.utc).isoformat()
        }

def decrypt_session_export_package(package: dict, passphrase: Optional[str] = None) -> str:
    """
    Mendekripsi paket sesi terenkripsi kembali ke format JSON raw Playwright session.
    """
    import base64
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    if not isinstance(package, dict) or package.get("app") != "alugara" or package.get("type") != "stockbit_session":
        raise ValueError("Format file tidak valid. Bukan paket sesi Alugara resmi.")

    payload = package.get("payload")
    if not payload:
        raise ValueError("Payload sesi dalam file kosong.")

    kdf = package.get("kdf")
    clean_pwd = passphrase.strip() if passphrase and passphrase.strip() else None

    if kdf == "pbkdf2_sha256":
        if not clean_pwd:
            raise ValueError("File sesi ini diproteksi passphrase. Silakan masukkan passphrase saat impor.")
        salt_b64 = package.get("salt")
        if not salt_b64:
            raise ValueError("Parameter salt kriptografi pada paket tidak ditemukan.")
        salt = base64.b64decode(salt_b64)
        kdf_inst = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        derived_key = base64.urlsafe_b64encode(kdf_inst.derive(clean_pwd.encode('utf-8')))
        try:
            f = Fernet(derived_key)
            return f.decrypt(payload.encode('utf-8')).decode('utf-8')
        except Exception:
            raise ValueError("Gagal mendekripsi file sesi. Passphrase yang dimasukkan salah!")

    elif kdf == "system_secret":
        try:
            f = _get_fernet()
            return f.decrypt(payload.encode('utf-8')).decode('utf-8')
        except Exception:
            raise ValueError("Kunci rahasia master berbeda dengan mesin asal. Jika mengekspor dari perangkat lain, disarankan gunakan passphrase saat ekspor.")

    else:
        raise ValueError(f"Algoritma enkripsi paket '{kdf}' tidak dikenali.")

