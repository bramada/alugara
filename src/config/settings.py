import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # Stockbit
    STOCKBIT_USERNAME: str = ""
    STOCKBIT_PASSWORD: str = ""
    STOCKBIT_TRADING_PIN: str = ""
    STOCKBIT_SESSION_DIR: str = "./sessions"

    # Gemini AI
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.1-pro"
    AI_REASONING_ENABLED: bool = True

    # Browser
    HEADLESS_MODE: bool = True
    BROWSER_TIMEOUT_MS: int = 30000

    # Telegram
    TELEGRAM_ENABLED: bool = False
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # Market Schedule
    MARKET_TIMEZONE: str = "Asia/Jakarta"
    MARKET_BUY_HOUR: int = 15
    MARKET_BUY_MINUTE: int = 40
    MARKET_SELL_HOUR: int = 9
    MARKET_SELL_MINUTE: int = 10

    # Capital & Risk Management
    CAPITAL_PER_STRATEGY: float = 9000000.0
    MAX_SLIPPAGE_PERCENT: float = 2.0
    AUTO_EXECUTE_ENABLED: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
