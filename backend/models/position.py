"""OpenPosition model — persists open position state across restarts."""

from datetime import datetime, timezone
from sqlmodel import SQLModel, Field


class OpenPosition(SQLModel, table=True):
    __tablename__ = "open_position"

    id: int | None = Field(default=None, primary_key=True)
    pair_id: int = Field(foreign_key="trading_pair.id", index=True, unique=True)
    direction: int  # 1 = long spread (long A, short B), -1 = short spread
    entry_z: float
    entry_spread: float
    entry_price_a: float
    entry_price_b: float
    entry_hedge_ratio: float
    entry_notional: float
    entry_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    lighter_order_id_a: str | None = None
    lighter_order_id_b: str | None = None
