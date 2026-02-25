"""Market data fetching from Lighter DEX.

Uses the Lighter CandlestickApi and OrderApi for all market data.
"""

import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


async def _get_api_client():
    """Create a Lighter ApiClient."""
    import lighter
    return lighter.ApiClient()


async def fetch_candles(
    market_id: int,
    resolution: str,
    candles_needed: int,
) -> pd.Series:
    """Fetch close price series from Lighter CandlestickApi.

    Args:
        market_id: Lighter market index.
        resolution: Candle interval (e.g. "1h", "4h", "1d").
        candles_needed: Number of candles to fetch.

    Returns:
        pd.Series of close prices with datetime index.
    """
    import lighter
    from lighter.api import CandlestickApi

    # Calculate time range
    interval_seconds = _resolution_to_seconds(resolution)
    now = datetime.now(timezone.utc)
    buffer_candles = int(candles_needed * 1.2)  # 20% buffer
    start_time = now - timedelta(seconds=buffer_candles * interval_seconds)

    start_ts = int(start_time.timestamp())
    end_ts = int(now.timestamp())

    client = await _get_api_client()
    try:
        api = CandlestickApi(client)
        # Use _with_http_info to get raw JSON — the SDK model drops
        # lowercase OHLC keys due to an alias mismatch bug.
        resp = await api.candles_with_http_info(
            market_id=market_id,
            resolution=resolution,
            start_timestamp=start_ts,
            end_timestamp=end_ts,
            count_back=buffer_candles,
        )
        import json
        raw = json.loads(resp.raw_data)
        return _parse_candles(raw)
    except Exception as e:
        logger.error(f"Error fetching candles for market {market_id}: {e}")
        return pd.Series(dtype=float)
    finally:
        await client.close()


async def fetch_orderbook(market_id: int) -> dict:
    """Fetch current orderbook for a market.

    Returns dict with 'mid_price', 'best_bid', 'best_ask'.
    """
    import lighter
    from lighter.api import OrderApi

    client = await _get_api_client()
    try:
        api = OrderApi(client)
        details = await api.get_orderbook_details(market_id=market_id)
        return _parse_orderbook(details)
    except Exception as e:
        logger.error(f"Error fetching orderbook for market {market_id}: {e}")
        return {"mid_price": 0.0, "best_bid": 0.0, "best_ask": 0.0}
    finally:
        await client.close()


async def fetch_markets() -> list[dict]:
    """Fetch all available markets from Lighter."""
    import lighter
    from lighter.api import OrderApi

    client = await _get_api_client()
    try:
        api = OrderApi(client)
        result = await api.order_books()
        return _parse_markets(result.order_books)
    except Exception as e:
        logger.error(f"Error fetching markets: {e}")
        return []
    finally:
        await client.close()


async def fetch_pair_data(
    market_a: int,
    market_b: int,
    window_interval: str,
    window_candles: int,
    train_interval: str,
    train_candles: int,
) -> dict[str, pd.Series]:
    """Fetch all price data needed for signal computation.

    Uses Lighter market indices instead of Hyperliquid tickers.
    Returns dict with keys: 'prices_a', 'prices_b', 'train_a', 'train_b'.
    """
    import asyncio

    # Fetch trading-interval data for both assets
    tasks = [
        fetch_candles(market_a, window_interval, window_candles),
        fetch_candles(market_b, window_interval, window_candles),
    ]

    # If training interval differs, fetch separately
    if train_interval != window_interval:
        tasks.append(fetch_candles(market_a, train_interval, train_candles))
        tasks.append(fetch_candles(market_b, train_interval, train_candles))

    results = await asyncio.gather(*tasks)

    data = {
        "prices_a": results[0],
        "prices_b": results[1],
    }

    if train_interval != window_interval:
        data["train_a"] = results[2]
        data["train_b"] = results[3]
    else:
        data["train_a"] = results[0]
        data["train_b"] = results[1]

    return data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolution_to_seconds(resolution: str) -> int:
    mapping = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "2h": 7200,
        "4h": 14400,
        "8h": 28800,
        "1d": 86400,
    }
    return mapping.get(resolution, 14400)


def _parse_candles(result) -> pd.Series:
    """Parse Lighter candle response (raw JSON dict) into a close price Series.

    The raw JSON looks like:
        {"code": 200, "r": "4h", "c": [{"t": 17706..., "o": 0.006, ... "c": 0.006}, ...]}
    Timestamps are in milliseconds.
    """
    try:
        # result is a raw dict parsed from JSON
        candles = result.get("c", []) if isinstance(result, dict) else []
        if not candles:
            return pd.Series(dtype=float)

        records = [{"t": c["t"], "close": c["c"]} for c in candles if c.get("c") is not None]

        df = pd.DataFrame(records)
        if df.empty:
            return pd.Series(dtype=float)

        df["t"] = pd.to_datetime(df["t"], unit="ms", utc=True)
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.set_index("t").sort_index()
        return df["close"].dropna()
    except Exception as e:
        logger.error(f"Failed to parse candles: {e}")
        return pd.Series(dtype=float)


def _parse_orderbook(details) -> dict:
    """Parse orderbook details into mid/bid/ask prices."""
    try:
        if isinstance(details, dict):
            bids = details.get("bids", [])
            asks = details.get("asks", [])
        else:
            bids = getattr(details, "bids", [])
            asks = getattr(details, "asks", [])

        best_bid = float(bids[0]["price"]) if bids else 0.0
        best_ask = float(asks[0]["price"]) if asks else 0.0
        mid = (best_bid + best_ask) / 2 if best_bid and best_ask else best_bid or best_ask

        return {"mid_price": mid, "best_bid": best_bid, "best_ask": best_ask}
    except Exception as e:
        logger.error(f"Failed to parse orderbook: {e}")
        return {"mid_price": 0.0, "best_bid": 0.0, "best_ask": 0.0}


def _parse_markets(orderbooks) -> list[dict]:
    """Parse orderbooks response into a list of market info dicts."""
    try:
        markets = orderbooks if isinstance(orderbooks, list) else getattr(orderbooks, "markets", orderbooks)
        result = []
        for m in markets:
            if isinstance(m, dict):
                result.append({"market_id": m.get("market_id"), "symbol": m.get("symbol", "")})
            else:
                result.append({"market_id": getattr(m, "market_id", None), "symbol": getattr(m, "symbol", "")})
        return result
    except Exception as e:
        logger.error(f"Failed to parse markets: {e}")
        return []
