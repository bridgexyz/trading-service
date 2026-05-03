"""SimplePairTrade model — tracks quick pair trades from open to close."""

from datetime import datetime, timezone
from sqlmodel import SQLModel, Field


class SimplePairTrade(SQLModel, table=True):
    __tablename__ = "simple_pair_trade"

    id: int | None = Field(default=None, primary_key=True)
    asset_a: str
    asset_b: str
    lighter_market_a: int
    lighter_market_b: int
    direction: int  # 1 = long A / short B, -1 = long B / short A
    ratio: float = Field(default=1.0)
    margin_usd: float = Field(default=100.0)
    leverage: float = Field(default=5.0)
    stop_loss_pct: float = Field(default=15.0)
    take_profit_pct: float = Field(default=5.0)
    order_mode: str = Field(default="limit")  # "market", "sliced", or "limit"
    slice_chunks: int = Field(default=5)
    slice_delay_sec: float = Field(default=2.0)
    credential_id: int | None = Field(default=None, foreign_key="credential.id")
    status: str = Field(default="pending")  # pending, open, closed, failed

    # Fill data (populated after execution)
    entry_price_a: float | None = None
    entry_price_b: float | None = None
    fill_size_a: float | None = None
    fill_size_b: float | None = None
    entry_notional: float | None = None
    entry_time: datetime | None = None

    # Exit data
    exit_price_a: float | None = None
    exit_price_b: float | None = None
    exit_time: datetime | None = None
    exit_reason: str | None = None  # stop_loss, take_profit, manual
    pnl: float | None = None
    pnl_pct: float | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
