from fastapi import APIRouter, HTTPException, Depends, Response, Request
from pydantic import BaseModel
from typing import Optional
from src.core.security import (
    is_master_password_configured,
    set_master_password,
    verify_master_password,
    create_user_session,
    validate_user_session,
    delete_user_session,
    get_auth_token_from_request,
    require_auth
)

router = APIRouter(prefix="/api/v1/auth", tags=["Security & Authentication"])

class SetupPayload(BaseModel):
    password: str
    confirm_password: str

class LoginPayload(BaseModel):
    password: str
    remember: bool = True

class ChangePasswordPayload(BaseModel):
    current_password: str
    new_password: str
    confirm_new_password: str

@router.get("/status")
async def get_auth_status(request: Request):
    """Cek status konfigurasi master password dan autentikasi sesi saat ini"""
    configured = is_master_password_configured()
    token = get_auth_token_from_request(request)
    authenticated = bool(token and validate_user_session(token))

    return {
        "is_configured": configured,
        "is_authenticated": authenticated,
        "message": "Autentikasi aktif" if authenticated else ("Harap login" if configured else "Buat Master Password")
    }

@router.post("/setup")
async def setup_master_password(payload: SetupPayload, response: Response):
    """Setup Master Password / PIN pertama kali saat aplikasi dibuka"""
    if is_master_password_configured():
        raise HTTPException(
            status_code=400,
            detail="Master Password sudah dikonfigurasi. Silakan login."
        )

    if len(payload.password) < 4:
        raise HTTPException(
            status_code=400,
            detail="Password minimal 4 karakter (atau 6 digit PIN)."
        )

    if payload.password != payload.confirm_password:
        raise HTTPException(
            status_code=400,
            detail="Konfirmasi password tidak cocok."
        )

    set_master_password(payload.password)
    token, expires_at = create_user_session(remember=True)

    # Set cookie HttpOnly
    response.set_cookie(
        key="alugara_session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=30 * 86400,
        path="/"
    )

    return {
        "success": True,
        "token": token,
        "message": "Master Password berhasil dibuat! Selamat datang di Alugara."
    }

@router.post("/login")
async def login(payload: LoginPayload, response: Response):
    """Verifikasi Master Password untuk membuka akses Dashboard Alugara"""
    if not is_master_password_configured():
        raise HTTPException(
            status_code=400,
            detail="Aplikasi belum memiliki Master Password. Silakan setup terlebih dahulu."
        )

    if not verify_master_password(payload.password):
        raise HTTPException(
            status_code=401,
            detail="Master Password / PIN salah! Akses ditolak."
        )

    token, expires_at = create_user_session(remember=payload.remember)
    max_age = (30 if payload.remember else 1) * 86400

    response.set_cookie(
        key="alugara_session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=max_age,
        path="/"
    )

    return {
        "success": True,
        "token": token,
        "message": "Login berhasil! Dashboard terbuka."
    }

@router.post("/logout")
async def logout(request: Request, response: Response):
    """Mengunci dashboard dan membatalkan sesi token saat ini"""
    token = get_auth_token_from_request(request)
    if token:
        delete_user_session(token)

    response.delete_cookie(key="alugara_session", path="/")
    return {
        "success": True,
        "message": "Dashboard berhasil dikunci. Sesi telah diakhiri."
    }

@router.post("/change-password")
async def change_password(payload: ChangePasswordPayload, token: str = Depends(require_auth)):
    """Mengubah Master Password yang sedang aktif"""
    if not verify_master_password(payload.current_password):
        raise HTTPException(
            status_code=401,
            detail="Password saat ini salah."
        )

    if len(payload.new_password) < 4:
        raise HTTPException(
            status_code=400,
            detail="Password baru minimal 4 karakter."
        )

    if payload.new_password != payload.confirm_new_password:
        raise HTTPException(
            status_code=400,
            detail="Konfirmasi password baru tidak cocok."
        )

    set_master_password(payload.new_password)
    return {
        "success": True,
        "message": "Master Password berhasil diperbarui!"
    }