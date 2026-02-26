"""Market data fetching.

Candle data comes from Hyperliquid (supports all intervals including 8h).
Orderbook and market listing still use Lighter.
"""

import logging
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from hyperliquid.info import Info

logger = logging.getLogger(__name__)

# Reusable Hyperliquid Info client (no auth needed for public data)
_hl_info = Info(skip_ws=True)


def _to_hl_ticker(asset: str) -> str:
    """Convert asset name to Hyperliquid ticker format.

    Hyperliquid uses 'kX' instead of '1000X' (e.g. kBONK, kPEPE).
    """
    if asset.startswith("1000"):
        return "k" + asset[4:]
    return asset


async def fetch_candles(
    ticker: str,
    resolution: str,
    candles_needed: int,
) -> pd.Series:
    """Fetch close price series from Hyperliquid.

    Args:
        ticker: Asset ticker (e.g. "SOL", "1000BONK").
        resolution: Candle interval (e.g. "1h", "4h", "8h").
        candles_needed: Number of candles to fetch.

    Returns:
        pd.Series of close prices with datetime index.
    """
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
    asset_a: str,
    asset_b: str,
    window_interval: str,
    window_candles: int,
    train_interval: str,
    train_candles: int,
) -> dict[str, pd.Series]:
    """Fetch all price data needed for signal computation.

    Uses asset ticker names via Hyperliquid.
    Returns dict with keys: 'prices_a', 'prices_b', 'train_a', 'train_b'.
    """
    import asyncio

    if train_interval != window_interval:
        # Different intervals — fetch window and training data separately
        tasks = [
            fetch_candles(asset_a, window_interval, window_candles),
            fetch_candles(asset_b, window_interval, window_candles),
            fetch_candles(asset_a, train_interval, train_candles),
            fetch_candles(asset_b, train_interval, train_candles),
        ]
        results = await asyncio.gather(*tasks)
        return {
            "prices_a": results[0],
            "prices_b": results[1],
            "train_a": results[2],
            "train_b": results[3],
        }
    else:
        # Same interval — fetch once with enough candles for both
        needed = max(window_candles, train_candles)
        tasks = [
            fetch_candles(asset_a, window_interval, needed),
            fetch_candles(asset_b, window_interval, needed),
        ]
        results = await asyncio.gather(*tasks)
        return {
            "prices_a": results[0],
            "prices_b": results[1],
            "train_a": results[0],
            "train_b": results[1],
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
        "1d": 86400,
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
