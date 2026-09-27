from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from src.config.settings import settings
from src.storage.db import init_db
from src.api.routes import trade, session
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
    description="Engine Automasi Trading Saham Indonesia (IDX) Mandiri & Terpisah 100%",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(trade.router)
app.include_router(session.router)

@app.get("/")
async def root():
    return {
        "service": "Alugara Standalone Auto-Trading Engine",
        "status": "ONLINE",
        "version": "1.0.0",
        "timezone": settings.MARKET_TIMEZONE,
        "auto_execute": settings.AUTO_EXECUTE_ENABLED
    }
