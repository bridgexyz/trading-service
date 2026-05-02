"""Shared chunked order execution for pair trades."""

import asyncio
import logging

logger = logging.getLogger(__name__)

MARKET_SLIPPAGE = 0.01
LIMIT_OFFSET = 0.0002


async def execute_chunked_pair_orders(
    client,
    market_a: int,
    market_b: int,
    size_a: float,
    size_b: float,
    is_ask_a: bool,
    is_ask_b: bool,
    chunks: int = 5,
    delay_sec: float = 2.0,
    reduce_only: bool = False,
    market: bool = True,
    label: str = "trade",
):
    """Execute orders in N smaller chunks with delays between each.

    For market=True: IOC orders with 1% slippage tolerance.
    For market=False: limit orders at mid-price (0.02% offset for entries).
    Both legs are batched atomically per chunk via place_pair_orders().

    Returns (last_result_a, last_result_b, completed_chunks).
    """
    from backend.services.market_data import fetch_orderbook

    chunk_size_a = size_a / chunks
    chunk_size_b = size_b / chunks

    last_result_a = None
    last_result_b = None
    completed = 0
    total_fill_qty_a = 0.0
    total_fill_value_a = 0.0
    total_fill_qty_b = 0.0
    total_fill_value_b = 0.0

    for i in range(chunks):
        ob_a, ob_b = await asyncio.gather(
            fetch_orderbook(market_a),
            fetch_orderbook(market_b),
        )
        mid_a = ob_a["mid_price"]
        mid_b = ob_b["mid_price"]

        if mid_a <= 0 or mid_b <= 0:
            logger.error(f"[{label}] Chunk {i+1}: invalid mid prices (A={mid_a}, B={mid_b}), stopping")
            break

        if market:
            price_a = mid_a * (1 - MARKET_SLIPPAGE) if is_ask_a else mid_a * (1 + MARKET_SLIPPAGE)
            price_b = mid_b * (1 - MARKET_SLIPPAGE) if is_ask_b else mid_b * (1 + MARKET_SLIPPAGE)
        elif not reduce_only:
            price_a = mid_a * (1 - LIMIT_OFFSET) if is_ask_a else mid_a * (1 + LIMIT_OFFSET)
            price_b = mid_b * (1 - LIMIT_OFFSET) if is_ask_b else mid_b * (1 + LIMIT_OFFSET)
        else:
            price_a = mid_a
            price_b = mid_b

        chunk_result = await client.place_pair_orders(
            market_index_a=market_a, base_amount_a=chunk_size_a,
            price_a=price_a, is_ask_a=is_ask_a,
            market_index_b=market_b, base_amount_b=chunk_size_b,
            price_b=price_b, is_ask_b=is_ask_b,
            market=market, reduce_only=reduce_only,
        )

        if not chunk_result.success:
            logger.error(f"[{label}] Chunk {i+1} batch failed: {chunk_result.error}")
            break

        result_a = chunk_result.result_a
        result_b = chunk_result.result_b
        last_result_a = result_a
        last_result_b = result_b
        completed += 1

        if result_a.filled_price and result_a.filled_amount:
            total_fill_qty_a += result_a.filled_amount
            total_fill_value_a += result_a.filled_price * result_a.filled_amount
        if result_b.filled_price and result_b.filled_amount:
            total_fill_qty_b += result_b.filled_amount
            total_fill_value_b += result_b.filled_price * result_b.filled_amount
        logger.info(f"[{label}] Chunk {completed}/{chunks} complete")

        if i < chunks - 1:
            await asyncio.sleep(delay_sec)

    if not market and completed > 0:
        logger.info(
            f"[{label}] Limit orders placed: {completed}/{chunks} chunks. "
            f"Orders may fill over time as maker."
        )

    if last_result_a and total_fill_qty_a > 0:
        last_result_a.filled_price = total_fill_value_a / total_fill_qty_a
        last_result_a.filled_amount = total_fill_qty_a
    if last_result_b and total_fill_qty_b > 0:
        last_result_b.filled_price = total_fill_value_b / total_fill_qty_b
        last_result_b.filled_amount = total_fill_qty_b

    return last_result_a, last_result_b, completed
