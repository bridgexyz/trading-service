"""JobLog model — per-cycle execution log for each pair."""

from datetime import datetime, timezone
from typing import Any

from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON


class JobLog(SQLModel, table=True):
    __tablename__ = "job_log"

    id: int | None = Field(default=None, primary_key=True)
    pair_id: int = Field(foreign_key="trading_pair.id", index=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str  # "success", "error", "skipped"
    z_score: float | None = None
    hedge_ratio: float | None = None
    half_life: float | None = None
    adx: float | None = None
    rsi: float | None = None
    action: str | None = None  # "none", "entry_long", "entry_short", "exit", "stop_loss"
    close_a: float | None = None
    close_b: float | None = None
    message: str | None = None
    market_data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
