"""Stateless signal computation for live trading.

Ported from hedge-fund-claude/analysis/backtester.py and spread.py.
All functions are pure computation — no I/O, no database access.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Core computation helpers (ported from backtester.py)
# ---------------------------------------------------------------------------

def compute_hedge_ratio(prices_a: np.ndarray, prices_b: np.ndarray) -> float:
    """OLS hedge ratio: a = beta * b + alpha."""
    if len(prices_a) < 2:
        return 1.0
    return float(np.polyfit(prices_b, prices_a, 1)[0])


def compute_zscore_value(
    prices_a: np.ndarray,
    prices_b: np.ndarray,
    hedge_ratio: float,
    window: int,
) -> tuple[float, float, float, float]:
    """Compute current z-score from the last `window` candles.

    Returns: (z_score, current_spread, spread_mean, spread_std)
    """
    spread = prices_a - hedge_ratio * prices_b
    spread_window = spread[-window:]
    mean = float(np.mean(spread_window))
    std = float(np.std(spread_window, ddof=1))
    current = float(spread[-1])

    if std == 0 or np.isnan(std):
        return 0.0, current, mean, std
    z = (current - mean) / std
    return z, current, mean, std


def rolling_half_life(spread: np.ndarray) -> float:
    """Compute OU half-life from a spread array. Returns inf if not mean-reverting."""
    if len(spread) < 5:
        return float("inf")
    lag = spread[:-1]
    delta = np.diff(spread)
    beta = float(np.polyfit(lag, delta, 1)[0])
    if beta >= 0:
        return float("inf")
    return -np.log(2) / beta


def compute_rsi(values: np.ndarray, period: int = 14) -> float:
    """Compute current RSI value. Returns NaN if insufficient data."""
    n = len(values)
    if n < period + 2:
        return float("nan")

    deltas = np.diff(values)
    gains = np.maximum(deltas, 0.0)
    losses = np.maximum(-deltas, 0.0)

    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


# ---------------------------------------------------------------------------
# Signal result types
# ---------------------------------------------------------------------------

@dataclass
class SignalResult:
    """Result of signal computation for a single point in time."""
    z_score: float
    hedge_ratio: float
    half_life: float
    rsi: float
    current_spread: float
    spread_mean: float
    spread_std: float


@dataclass
class EntrySignal:
    """Entry decision."""
    should_enter: bool
    direction: int = 0  # 1 = long spread, -1 = short spread
    skip_reason: str | None = None  # "no_signal", "half_life", "rsi", "equity_floor"
    notional: float = 0.0


@dataclass
class ExitSignal:
    """Exit decision."""
    should_exit: bool
    exit_reason: str | None = None  # "signal", "stop_loss", "stop_z"
    unrealized_pnl: float = 0.0
    unrealized_pct: float = 0.0


# ---------------------------------------------------------------------------
# Main signal functions
# ---------------------------------------------------------------------------

def compute_signals(
    prices_a: np.ndarray,
    prices_b: np.ndarray,
    train_prices_a: np.ndarray,
    train_prices_b: np.ndarray,
    window_candles: int,
    train_candles: int,
    rsi_period: int = 14,
) -> SignalResult:
    """Compute all signal values for the current moment.

    Args:
        prices_a, prices_b: Trading-interval price arrays (most recent `window_candles` candles).
        train_prices_a, train_prices_b: Training-interval price arrays (most recent `train_candles` candles).
        window_candles: Number of candles for z-score window.
        train_candles: Number of candles for hedge ratio training.
        rsi_period: RSI lookback period.
    """
    # Hedge ratio from training data
    hr = compute_hedge_ratio(
        train_prices_a[-train_candles:],
        train_prices_b[-train_candles:],
    )

    # Z-score from trading data
    z, spread_now, spread_mean, spread_std = compute_zscore_value(
        prices_a[-window_candles:],
        prices_b[-window_candles:],
        hr,
        window_candles,
    )

    # Half-life on the trading window spread
    spread_window = prices_a[-window_candles:] - hr * prices_b[-window_candles:]
    hl = rolling_half_life(spread_window)

    # RSI on price ratio
    ratio = prices_a / prices_b
    rsi = compute_rsi(ratio, period=rsi_period)

    return SignalResult(
        z_score=z,
        hedge_ratio=hr,
        half_life=hl,
        rsi=rsi,
        current_spread=spread_now,
        spread_mean=spread_mean,
        spread_std=spread_std,
    )


def evaluate_entry(
    signals: SignalResult,
    entry_z: float,
    max_half_life: float,
    rsi_upper: float,
    rsi_lower: float,
    current_equity: float,
    equity_floor: float,
    leverage: float,
) -> EntrySignal:
    """Evaluate whether to enter a new position.

    Returns an EntrySignal with the decision and reason.
    """
    z = signals.z_score

    # Check for signal
    has_signal = abs(z) > entry_z
    if not has_signal:
        return EntrySignal(should_enter=False, skip_reason="no_signal")

    # Half-life filter
    use_hl = max_half_life > 0
    if use_hl and not (0 < signals.half_life <= max_half_life):
        return EntrySignal(should_enter=False, skip_reason="half_life")

    # RSI filter
    use_rsi = rsi_lower > 0 or rsi_upper < 100
    if use_rsi and not np.isnan(signals.rsi):
        if signals.rsi < rsi_lower or signals.rsi > rsi_upper:
            return EntrySignal(should_enter=False, skip_reason="rsi")

    # Equity floor
    if current_equity < equity_floor:
        return EntrySignal(should_enter=False, skip_reason="equity_floor")

    direction = -1 if z > entry_z else 1  # z > entry_z -> short spread
    notional = current_equity * leverage

    return EntrySignal(
        should_enter=True,
        direction=direction,
        notional=notional,
    )


def evaluate_exit(
    signals: SignalResult,
    position_direction: int,
    entry_spread: float,
    entry_price_a: float,
    entry_price_b: float,
    entry_hedge_ratio: float,
    entry_notional: float,
    current_equity: float,
    exit_z: float,
    stop_z: float,
    stop_loss_pct: float,
    current_price_a: float,
    current_price_b: float,
) -> ExitSignal:
    """Evaluate whether to exit an existing position.

    Returns an ExitSignal with the decision and PnL information.
    """
    z = signals.z_score

    # Compute unrealized PnL
    exit_spread = current_price_a - entry_hedge_ratio * current_price_b
    spread_change = exit_spread - entry_spread
    dollar_per_unit = entry_price_a + abs(entry_hedge_ratio) * entry_price_b
    spread_units = entry_notional / dollar_per_unit if dollar_per_unit != 0 else 0
    unreal_pnl = position_direction * spread_change * spread_units
    unreal_pct = unreal_pnl / current_equity * 100 if current_equity != 0 else 0

    # Stop loss
    if stop_loss_pct > 0 and unreal_pct <= -stop_loss_pct:
        return ExitSignal(
            should_exit=True,
            exit_reason="stop_loss",
            unrealized_pnl=unreal_pnl,
            unrealized_pct=unreal_pct,
        )

    # Z-score exit conditions
    if position_direction == 1 and (z > -exit_z or z > stop_z):
        return ExitSignal(
            should_exit=True,
            exit_reason="signal" if z > -exit_z else "stop_z",
            unrealized_pnl=unreal_pnl,
            unrealized_pct=unreal_pct,
        )

    if position_direction == -1 and (z < exit_z or z < -stop_z):
        return ExitSignal(
            should_exit=True,
            exit_reason="signal" if z < exit_z else "stop_z",
            unrealized_pnl=unreal_pnl,
            unrealized_pct=unreal_pct,
        )

    return ExitSignal(
        should_exit=False,
        unrealized_pnl=unreal_pnl,
        unrealized_pct=unreal_pct,
    )
