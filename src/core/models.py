from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, Field

class OrderRequest(BaseModel):
    ticker: str = Field(..., description="Kode saham, contoh: BBCA, BBRI")
    action: Literal["BUY", "SELL"] = Field(..., description="Aksi: BUY atau SELL")
    price: int = Field(..., description="Harga per lembar saham dalam Rupiah")
    lots: int = Field(..., description="Jumlah lot yang dipesan (1 lot = 100 lembar)")
    trading_pin: Optional[str] = Field(None, description="PIN Trading Stockbit")
    strategy_id: Optional[str] = Field(None, description="ID Strategi Kuantitatif")
    strategy_name: Optional[str] = Field(None, description="Nama Strategi Kuantitatif")
    target_price: Optional[int] = Field(None, description="Target harga Take Profit")
    stop_loss_price: Optional[int] = Field(None, description="Target harga Stop Loss")

class OrderResult(BaseModel):
    success: bool
    order_id: Optional[str] = None
    ticker: str
    action: Literal["BUY", "SELL"]
    price: int
    lots: int
    total_amount: int
    status: Literal["SUBMITTED", "MATCHED", "REJECTED", "FAILED"]
    message: str
    screenshot_path: Optional[str] = None
    executed_at: datetime = Field(default_factory=datetime.now)

class SignalItem(BaseModel):
    ticker: str
    company_name: Optional[str] = None
    action: Literal["BUY", "SELL"]
    current_price: int
    target_price: Optional[int] = None
    stop_loss: Optional[int] = None
    strategy_id: str
    strategy_name: str
    allocated_capital: float = 3000000.0

class SignalWebhookPayload(BaseModel):
    secret_key: str
    timestamp: str
    signals: List[SignalItem]
    execution_type: Literal["BUY_SESSION", "SELL_SESSION", "MANUAL"] = "BUY_SESSION"

class SessionStatusResponse(BaseModel):
    is_authenticated: bool
    username: Optional[str] = None
    session_file_exists: bool
    last_validated_at: Optional[datetime] = None
    message: str

class PortfolioHoldingItem(BaseModel):
    ticker: str
    lots: int
    avg_buy_price: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_percent: float
