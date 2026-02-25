"""Trade model — immutable record of every completed trade."""

from datetime import datetime, timezone
from sqlmodel import SQLModel, Field


class Trade(SQLModel, table=True):
    __tablename__ = "trade"

    id: int | None = Field(default=None, primary_key=True)
    pair_id: int = Field(foreign_key="trading_pair.id", index=True)
    direction: str  # "Long A / Short B" or "Short A / Long B"
    entry_time: datetime
    exit_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    entry_price_a: float
    exit_price_a: float
    entry_price_b: float
    exit_price_b: float
    size_a: float
    size_b: float
    hedge_ratio: float
    pnl: float
    pnl_pct: float
    exit_reason: str  # "signal", "stop_loss", "stop_z", "manual"
    duration_candles: int = 0
