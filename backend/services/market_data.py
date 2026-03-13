"""Market data fetching.

Short-interval candle data (≤1h) comes from Lighter DEX when market_id is available.
Longer intervals (2h, 4h, 8h, etc.) use Hyperliquid.
Orderbook and market listing still use Lighter.
"""

import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from hyperliquid.info import Info

from backend.utils.constants import LIGHTER_CANDLE_INTERVALS

logger = logging.getLogger(__name__)

# Reusable Hyperliquid Info client (no auth needed for public data)
_hl_info = Info(skip_ws=True)

# Cached Lighter ApiClient for candle data (no auth needed)
_lighter_candle_client = None


def _to_hl_ticker(asset: str) -> str:
    """Convert asset name to Hyperliquid ticker format.

    Hyperliquid uses 'kX' instead of '1000X' (e.g. kBONK, kPEPE).
    """
    if asset.startswith("1000"):
        return "k" + asset[4:]
    return asset


def _get_lighter_candle_client():
    """Get or create a reusable Lighter ApiClient for candle data."""
    global _lighter_candle_client
    if _lighter_candle_client is None:
        import lighter
        _lighter_candle_client = lighter.ApiClient()
    return _lighter_candle_client


async def fetch_candles_lighter(
    market_id: int,
    resolution: str,
    candles_needed: int,
) -> pd.Series:
    """Fetch close price series from Lighter DEX.

    Uses CandlestickApi with raw JSON parsing to avoid SDK Candle model
    field alias collision (c/C).

    Args:
        market_id: Lighter market ID (integer).
        resolution: Candle interval (e.g. "15m", "1h").
        candles_needed: Number of candles to fetch.

    Returns:
        pd.Series of close prices with datetime index.
    """
    from lighter.api import CandlestickApi

    client = _get_lighter_candle_client()
    interval_seconds = _resolution_to_seconds(resolution)
    now = datetime.now(timezone.utc)
    buffer_candles = int(candles_needed * 1.2)
    start_time = now - timedelta(seconds=buffer_candles * interval_seconds)

    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(now.timestamp() * 1000)

    try:
        api = CandlestickApi(client)
        # Use _without_preload_content to get raw response and parse JSON
        # manually, avoiding the SDK Candle model bug where field 'c' (close)
        # alias 'C' collides with the Candles container field 'c' (candles list).
        resp = await api.candles_without_preload_content(
            market_id=market_id,
            resolution=resolution,
            start_timestamp=start_ms,
            end_timestamp=end_ms,
            count_back=buffer_candles,
        )
        raw = await resp.json()
        candles = raw.get("c", [])
        series = _parse_lighter_candles(candles)
        logger.debug(
            f"Lighter candles for market {market_id} ({resolution}): "
            f"{len(series)} points"
        )
        return series
    except Exception as e:
        logger.error(f"Error fetching Lighter candles for market {market_id}: {e}")
        return pd.Series(dtype=float)


async def fetch_candles(
    ticker: str,
    resolution: str,
    candles_needed: int,
    market_id: int | None = None,
) -> pd.Series:
    """Fetch close price series.

    Routes to Lighter DEX for short intervals (≤1h) when market_id is
    provided, otherwise falls back to Hyperliquid.

    Args:
        ticker: Asset ticker (e.g. "SOL", "1000BONK").
        resolution: Candle interval (e.g. "1h", "4h", "8h").
        candles_needed: Number of candles to fetch.
        market_id: Optional Lighter market ID. When set and resolution is
            in LIGHTER_CANDLE_INTERVALS, uses Lighter DEX data.

    Returns:
        pd.Series of close prices with datetime index.
    """
    # Route to Lighter for short intervals when market_id is available
    if market_id is not None and resolution in LIGHTER_CANDLE_INTERVALS:
        return await fetch_candles_lighter(market_id, resolution, candles_needed)

    import asyncio

    hl_ticker = _to_hl_ticker(ticker)
    interval_seconds = _resolution_to_seconds(resolution)
    now = datetime.now(timezone.utc)
    buffer_candles = int(candles_needed * 1.2)  # 20% buffer
    start_time = now - timedelta(seconds=buffer_candles * interval_seconds)

    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(now.timestamp() * 1000)

    try:
        # candles_snapshot is synchronous — run in executor to avoid blocking
        candles = await asyncio.get_event_loop().run_in_executor(
            None, _hl_info.candles_snapshot, hl_ticker, resolution, start_ms, end_ms
        )
        return _parse_candles(candles)
    except Exception as e:
        logger.error(f"Error fetching candles for {ticker} ({hl_ticker}): {e}")
        return pd.Series(dtype=float)


async def _get_api_client():
    """Create a Lighter ApiClient (used for orderbook/markets)."""
    import lighter
    return lighter.ApiClient()


async def fetch_orderbook(market_id: int) -> dict:
    """Fetch current orderbook for a market.

    Returns dict with 'mid_price', 'best_bid', 'best_ask'.
    """
    import lighter
    from lighter.api import OrderApi

    client = await _get_api_client()
    try:
        api = OrderApi(client)
        result = await api.order_book_orders(market_id=market_id, limit=1)
        return _parse_orderbook(result)
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
    asset_a: str,
    asset_b: str,
    window_interval: str,
    window_candles: int,
    train_interval: str,
    train_candles: int,
    market_id_a: int | None = None,
    market_id_b: int | None = None,
) -> dict[str, pd.Series]:
    """Fetch all price data needed for signal computation.

    When market_id_a/b are provided, short-interval fetches (≤1h) use
    Lighter DEX data. Longer intervals always use Hyperliquid.

    Returns dict with keys: 'prices_a', 'prices_b', 'train_a', 'train_b'.
    """
    import asyncio

    if train_interval != window_interval:
        # Different intervals — fetch window and training data separately
        tasks = [
            fetch_candles(asset_a, window_interval, window_candles, market_id=market_id_a),
            fetch_candles(asset_b, window_interval, window_candles, market_id=market_id_b),
            fetch_candles(asset_a, train_interval, train_candles, market_id=market_id_a),
            fetch_candles(asset_b, train_interval, train_candles, market_id=market_id_b),
        ]
        results = await asyncio.gather(*tasks)
        # Align each pair by datetime index to handle mismatched candle counts
        prices_a, prices_b = results[0].align(results[1], join="inner")
        train_a, train_b = results[2].align(results[3], join="inner")
        return {
            "prices_a": prices_a,
            "prices_b": prices_b,
            "train_a": train_a,
            "train_b": train_b,
        }
    else:
        # Same interval — fetch once with enough candles for both
        needed = max(window_candles, train_candles)
        tasks = [
            fetch_candles(asset_a, window_interval, needed, market_id=market_id_a),
            fetch_candles(asset_b, window_interval, needed, market_id=market_id_b),
        ]
        results = await asyncio.gather(*tasks)
        # Align by datetime index to handle mismatched candle counts
        aligned_a, aligned_b = results[0].align(results[1], join="inner")
        return {
            "prices_a": aligned_a,
            "prices_b": aligned_b,
            "train_a": aligned_a,
            "train_b": aligned_b,
        }


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
        "12h": 43200,
        "1d": 86400,
        "1w": 604800,
    }
    return mapping.get(resolution, 14400)


def _parse_candles(candles: list[dict]) -> pd.Series:
    """Parse Hyperliquid candles_snapshot response into a close price Series.

    Each candle dict: {"t": 1772092800000, "s": "SOL", "i": "8h",
                       "o": "87.212", "c": "87.498", "h": "87.811", "l": "87.212", ...}
    """
    try:
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


def _parse_lighter_candles(candles: list[dict]) -> pd.Series:
    """Parse Lighter DEX raw candle dicts into a close price Series.

    Each candle dict has shortened keys: t (timestamp), O (open), H (high),
    L (low), C (close), V (volume). We use 'C' for close price.
    """
    try:
        if not candles:
            return pd.Series(dtype=float)

        records = []
        for c in candles:
            # Close price is in 'C' (aliased field in SDK)
            close = c.get("C") or c.get("c")
            ts = c.get("t")
            if close is not None and ts is not None:
                records.append({"t": ts, "close": close})

        if not records:
            return pd.Series(dtype=float)

        df = pd.DataFrame(records)
        df["t"] = pd.to_datetime(df["t"], unit="ms", utc=True)
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.set_index("t").sort_index()
        return df["close"].dropna()
    except Exception as e:
        logger.error(f"Failed to parse Lighter candles: {e}")
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

        def _get_price(order):
            if isinstance(order, dict):
                return float(order["price"])
            return float(order.price)

        best_bid = _get_price(bids[0]) if bids else 0.0
        best_ask = _get_price(asks[0]) if asks else 0.0
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
