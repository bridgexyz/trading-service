"""Shared constants and defaults, ported from hedge-fund-claude."""

VALID_INTERVALS = ["1m", "5m", "15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d", "1w"]

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
    "12h": 12.0,
    "1d": 24.0,
    "1w": 168.0,
}

# Intervals routed to Lighter DEX candle data (short timeframes)
LIGHTER_CANDLE_INTERVALS = {"1m", "5m", "15m", "30m", "1h"}

DEFAULT_LIGHTER_HOST = "https://mainnet.zklighter.elliot.ai"
