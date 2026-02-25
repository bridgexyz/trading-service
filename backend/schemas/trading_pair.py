"""Pydantic schemas for TradingPair API."""

from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator

from backend.utils.constants import VALID_INTERVALS


class TradingPairCreate(BaseModel):
    name: str = Field(default="", max_length=120)
    asset_a: str = Field(min_length=1, max_length=32)
    asset_b: str = Field(min_length=1, max_length=32)
    lighter_market_a: int = Field(default=0, ge=0)
    lighter_market_b: int = Field(default=0, ge=0)
    entry_z: float = Field(default=2.0, gt=0)
    exit_z: float = Field(default=0.5, ge=0)
    stop_z: float = Field(default=4.0, gt=0)
    window_interval: str = "4h"
    window_candles: int = Field(default=40, ge=2)
    train_interval: str = "4h"
    train_candles: int = Field(default=100, ge=2)
    max_half_life: float = Field(default=50.0, ge=0)
    rsi_upper: float = Field(default=70.0, ge=0, le=100)
    rsi_lower: float = Field(default=20.0, ge=0, le=100)
    rsi_period: int = Field(default=14, ge=2)
    stop_loss_pct: float = Field(default=10.0, ge=0)
    position_size_pct: float = Field(default=50.0, gt=0, le=100)
    tx_cost_bps: float = Field(default=0.0, ge=0)
    leverage: float = Field(default=5.0, gt=0)
    min_equity_pct: float = Field(default=40.0, ge=0, le=100)
    schedule_interval: str = "15m"
    is_enabled: bool = True

    @field_validator("asset_a", "asset_b")
    @classmethod
    def _trim_required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("window_interval", "train_interval", "schedule_interval")
    @classmethod
    def _validate_interval(cls, value: str) -> str:
        if value not in VALID_INTERVALS:
            allowed = ", ".join(VALID_INTERVALS)
            raise ValueError(f"must be one of: {allowed}")
        return value

    @model_validator(mode="after")
    def _validate_relationships(self):
        if self.rsi_lower >= self.rsi_upper:
            raise ValueError("rsi_lower must be less than rsi_upper")
        if self.train_candles < self.window_candles:
            raise ValueError("train_candles must be >= window_candles")
        return self


class TradingPairUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    asset_a: str | None = Field(default=None, min_length=1, max_length=32)
    asset_b: str | None = Field(default=None, min_length=1, max_length=32)
    lighter_market_a: int | None = Field(default=None, ge=0)
    lighter_market_b: int | None = Field(default=None, ge=0)
    entry_z: float | None = Field(default=None, gt=0)
    exit_z: float | None = Field(default=None, ge=0)
    stop_z: float | None = Field(default=None, gt=0)
    window_interval: str | None = None
    window_candles: int | None = Field(default=None, ge=2)
    train_interval: str | None = None
    train_candles: int | None = Field(default=None, ge=2)
    max_half_life: float | None = Field(default=None, ge=0)
    rsi_upper: float | None = Field(default=None, ge=0, le=100)
    rsi_lower: float | None = Field(default=None, ge=0, le=100)
    rsi_period: int | None = Field(default=None, ge=2)
    stop_loss_pct: float | None = Field(default=None, ge=0)
    position_size_pct: float | None = Field(default=None, gt=0, le=100)
    tx_cost_bps: float | None = Field(default=None, ge=0)
    leverage: float | None = Field(default=None, gt=0)
    min_equity_pct: float | None = Field(default=None, ge=0, le=100)
    schedule_interval: str | None = None
    is_enabled: bool | None = None

    @field_validator("name", "asset_a", "asset_b")
    @classmethod
    def _trim_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text

    @field_validator("window_interval", "train_interval", "schedule_interval")
    @classmethod
    def _validate_optional_interval(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in VALID_INTERVALS:
            allowed = ", ".join(VALID_INTERVALS)
            raise ValueError(f"must be one of: {allowed}")
        return value

    @model_validator(mode="after")
    def _validate_optional_relationships(self):
        if (
            self.rsi_lower is not None
            and self.rsi_upper is not None
            and self.rsi_lower >= self.rsi_upper
        ):
            raise ValueError("rsi_lower must be less than rsi_upper")
        if (
            self.window_candles is not None
            and self.train_candles is not None
            and self.train_candles < self.window_candles
        ):
            raise ValueError("train_candles must be >= window_candles")
        return self


class TradingPairRead(BaseModel):
    id: int
    name: str
    asset_a: str
    asset_b: str
    lighter_market_a: int
    lighter_market_b: int
    entry_z: float
    exit_z: float
    stop_z: float
    window_interval: str
    window_candles: int
    train_interval: str
    train_candles: int
    max_half_life: float
    rsi_upper: float
    rsi_lower: float
    rsi_period: int
    stop_loss_pct: float
    position_size_pct: float
    tx_cost_bps: float
    leverage: float
    min_equity_pct: float
    schedule_interval: str
    is_enabled: bool
    current_equity: float
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
