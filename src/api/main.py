import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from loguru import logger
from src.config.settings import settings
from src.storage.db import init_db
from src.api.routes import trade, session, gui, auth
from src.scheduler.market_scheduler import MarketScheduler
from src.core.execution_engine import ExecutionEngine

engine = ExecutionEngine()
scheduler = MarketScheduler(execution_engine=engine)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Memulai Alugara Standalone Trading Engine...")
    init_db()
    scheduler.start()
    yield
    logger.info("Menghentikan Alugara Engine...")
    scheduler.shutdown()

app = FastAPI(
    title="Alugara - Standalone Automated Stock Trading Engine",
    description="Engine Automasi Trading Saham Indonesia (IDX) dengan Web GUI Dashboard & Login Security Gate",
    version="1.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static Files for Screenshots & Web GUI
os.makedirs("screenshots", exist_ok=True)
os.makedirs("src/static", exist_ok=True)
app.mount("/screenshots", StaticFiles(directory="screenshots"), name="screenshots")
app.mount("/static", StaticFiles(directory="src/static"), name="static")

# Include Routers
app.include_router(auth.router)
app.include_router(gui.router)
app.include_router(trade.router)
app.include_router(session.router)

@app.get("/favicon.ico", include_in_schema=False)
async def serve_favicon():
    fav_path = os.path.join(os.path.dirname(__file__), "..", "static", "favicon.ico")
    if os.path.exists(fav_path):
        return FileResponse(fav_path, media_type="image/x-icon", headers={"Cache-Control": "public, max-age=3600"})
    return {"status": "not found"}

@app.get("/")
async def serve_gui_dashboard():
    """Menyajikan antarmuka Web Dashboard Alugara"""
    index_path = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "service": "Alugara Auto-Trading Engine",
        "status": "ONLINE",
        "gui_status": "Template index.html not found"
    }

@app.get("/health")
async def health():
    return {"status": "healthy"}