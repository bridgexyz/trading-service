"""EquitySnapshot model — periodic equity recordings per pair."""

from datetime import datetime, timezone
from sqlmodel import SQLModel, Field


class EquitySnapshot(SQLModel, table=True):
    __tablename__ = "equity_snapshot"

    id: int | None = Field(default=None, primary_key=True)
    pair_id: int = Field(foreign_key="trading_pair.id", index=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    equity: float
    drawdown_pct: float = 0.0
