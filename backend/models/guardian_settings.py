"""GuardianSettings model — single-row config for the stop-loss guardian job."""

from datetime import datetime, timezone
from sqlmodel import SQLModel, Field


class GuardianSettings(SQLModel, table=True):
    __tablename__ = "guardian_settings"

    id: int = Field(default=1, primary_key=True)
    enabled: bool = True
    interval_seconds: int = 60
    stop_loss_pct_override: float | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
