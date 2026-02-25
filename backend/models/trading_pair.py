"""TradingPair model — stores all configuration for a pair trading strategy."""

from datetime import datetime, timezone
from sqlmodel import SQLModel, Field


class TradingPair(SQLModel, table=True):
    __tablename__ = "trading_pair"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)  # e.g. "ETH-BTC"
    asset_a: str  # Hyperliquid ticker
    asset_b: str
    lighter_market_a: int = 0  # Lighter market index
    lighter_market_b: int = 0

    # Signal parameters
    entry_z: float = 2.0
    exit_z: float = 0.5
    stop_z: float = 4.0

    # Window configuration
    window_interval: str = "4h"
    window_candles: int = 40
    train_interval: str = "4h"
    train_candles: int = 100

    # Regime filters
    max_half_life: float = 50.0
    max_adx: float = 40.0
    rsi_upper: float = 70.0
    rsi_lower: float = 20.0
    rsi_period: int = 14

    # Risk & sizing
    stop_loss_pct: float = 10.0
    position_size_pct: float = 50.0  # Percentage of account balance
    tx_cost_bps: float = 0.0
    leverage: float = 5.0
    min_equity_pct: float = 40.0

    # Scheduling
    schedule_interval: str = "15m"
    is_enabled: bool = True

    # Runtime state
    current_equity: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
