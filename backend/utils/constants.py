"""Shared constants and defaults, ported from hedge-fund-claude."""

VALID_INTERVALS = ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "8h", "1d"]

# Interval to hours mapping for APScheduler
INTERVAL_HOURS: dict[str, float] = {
    "1m": 1 / 60,
    "5m": 5 / 60,
    "15m": 0.25,
    "30m": 0.5,
    "1h": 1.0,
    "2h": 2.0,
    "4h": 4.0,
    "8h": 8.0,
    "1d": 24.0,
}
