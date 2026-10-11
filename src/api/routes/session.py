import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from src.drivers.stockbit_driver import StockbitDriver
from src.core.security import require_auth
from loguru import logger

router = APIRouter(prefix="/api/v1/session", tags=["Session Management"], dependencies=[Depends(require_auth)])
driver = StockbitDriver()

class ExportSessionPayload(BaseModel):
    passphrase: Optional[str] = None

class ImportSessionPayload(BaseModel):
    package: Dict[str, Any]
    passphrase: Optional[str] = None

@router.get("/status")
async def get_session_status():
    valid, msg = await driver.check_session_valid()
    return {"is_authenticated": valid, "message": msg}

@router.post("/export")
async def export_session(payload: Optional[ExportSessionPayload] = None):
    """
    Mengekspor sesi Stockbit terenkripsi (AES-256) untuk dipindahkan antar perangkat/server
    """
    passphrase = payload.passphrase if payload else None
    ok, package, msg = driver.export_session_package(passphrase=passphrase)
    if not ok:
        return {"success": False, "message": msg}
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"stockbit_session_{timestamp}.alugara"
    return {
        "success": True,
        "message": msg,
        "filename": filename,
        "package": package
    }

@router.post("/import")
async def import_session_json(payload: ImportSessionPayload):
    """
    Mengimpor paket sesi Stockbit dari payload JSON
    """
    ok, msg = driver.import_session_package(payload.package, payload.passphrase)
    if not ok:
        return {"success": False, "message": msg}
    
    # Verifikasi status setelah impor
    valid, verify_msg = await driver.check_session_valid()
    return {
        "success": True,
        "message": msg,
        "is_authenticated": valid,
        "session_status": verify_msg
    }

@router.post("/import-file")
async def import_session_file(
    file: UploadFile = File(...),
    passphrase: Optional[str] = Form(None)
):
    """
    Mengimpor file paket sesi Stockbit (.alugara atau .json) via multipart upload
    """
    try:
        content = await file.read()
        package = json.loads(content.decode("utf-8"))
    except Exception as e:
        logger.error(f"Gagal membaca file upload sesi: {e}")
        return {"success": False, "message": "File tidak terbaca atau format JSON rusak."}

    ok, msg = driver.import_session_package(package, passphrase)
    if not ok:
        return {"success": False, "message": msg}

    valid, verify_msg = await driver.check_session_valid()
    return {
        "success": True,
        "message": msg,
        "is_authenticated": valid,
        "session_status": verify_msg
    }