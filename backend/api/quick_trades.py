"""Quick Trades API — open/close simple pair trades with immediate execution."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from backend.database import engine as db_engine
from backend.api.deps import get_current_user
from backend.models.simple_trade import SimplePairTrade

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/quick-trades",
    tags=["quick-trades"],
    dependencies=[Depends(get_current_user)],
)

_trade_locks: dict[int, asyncio.Lock] = {}


def _get_lock(trade_id: int) -> asyncio.Lock:
    if trade_id not in _trade_locks:
        _trade_locks[trade_id] = asyncio.Lock()
    return _trade_locks[trade_id]


class QuickTradeCreate(BaseModel):
    asset_a: str
    asset_b: str
    direction: int = Field(description="1 = long A / short B, -1 = long B / short A")
    ratio: float = 1.0
    margin_usd: float = 100.0
    leverage: float = 5.0
    stop_loss_pct: float = 15.0
    take_profit_pct: float = 5.0
    order_mode: Literal["market", "sliced", "limit"] = "limit"
    slice_chunks: int = Field(default=5, ge=2, le=50)
    slice_delay_sec: float = Field(default=2.0, ge=0.5, le=30)
    credential_id: int | None = None


class QuickTradeUpdate(BaseModel):
    stop_loss_pct: float | None = Field(default=None, ge=0)
    take_profit_pct: float | None = Field(default=None, ge=0)


@router.post("")
async def open_quick_trade(data: QuickTradeCreate):
    """Open a new simple pair trade with immediate execution."""
    from backend.services.market_data import fetch_markets, fetch_orderbook
    from backend.engine.pair_job import _get_lighter_client
    from backend.engine.order_executor import MARKET_SLIPPAGE, execute_chunked_pair_orders

    if data.direction not in (1, -1):
        raise HTTPException(400, "direction must be 1 or -1")
    if data.margin_usd <= 0:
        raise HTTPException(400, "margin_usd must be positive")
    if data.leverage <= 0:
        raise HTTPException(400, "leverage must be positive")

    # Resolve market indices from ticker symbols
    markets = await fetch_markets()
    market_map = {m["symbol"]: m["market_id"] for m in markets}

    if data.asset_a not in market_map:
        raise HTTPException(400, f"Unknown asset: {data.asset_a}")
    if data.asset_b not in market_map:
        raise HTTPException(400, f"Unknown asset: {data.asset_b}")

    market_a = market_map[data.asset_a]
    market_b = market_map[data.asset_b]

    # Create pending trade record
    trade = SimplePairTrade(
        asset_a=data.asset_a,
        asset_b=data.asset_b,
        lighter_market_a=market_a,
        lighter_market_b=market_b,
        direction=data.direction,
        ratio=data.ratio,
        margin_usd=data.margin_usd,
        leverage=data.leverage,
        stop_loss_pct=data.stop_loss_pct,
        take_profit_pct=data.take_profit_pct,
        order_mode=data.order_mode,
        slice_chunks=data.slice_chunks,
        slice_delay_sec=data.slice_delay_sec,
        credential_id=data.credential_id,
        status="pending",
    )
    with Session(db_engine) as session:
        session.add(trade)
        session.commit()
        session.refresh(trade)
    trade_id = trade.id

    # Get lighter client
    client = await _get_lighter_client(data.credential_id)
    if not client:
        _update_trade_status(trade_id, "failed")
        raise HTTPException(400, "No valid credential found")

    # Compute position sizes
    notional = data.margin_usd * data.leverage
    notional_a = notional * data.ratio / (1 + data.ratio)
    notional_b = notional / (1 + data.ratio)

    # Fetch mid prices to convert notional to base amounts
    ob_a, ob_b = await asyncio.gather(
        fetch_orderbook(market_a),
        fetch_orderbook(market_b),
    )
    mid_a = ob_a["mid_price"]
    mid_b = ob_b["mid_price"]

    if mid_a <= 0 or mid_b <= 0:
        _update_trade_status(trade_id, "failed")
        raise HTTPException(400, f"Invalid mid prices: A={mid_a}, B={mid_b}")

    size_a = notional_a / mid_a
    size_b = notional_b / mid_b

    # direction=1: long A (buy), short B (sell)
    # direction=-1: long B (buy), short A (sell)
    is_ask_a = data.direction == -1  # sell A if direction is -1
    is_ask_b = data.direction == 1   # sell B if direction is 1

    # Execute entry orders
    try:
        if data.order_mode in ("sliced", "limit"):
            result_a, result_b, completed = await execute_chunked_pair_orders(
                client=client,
                market_a=market_a,
                market_b=market_b,
                size_a=size_a,
                size_b=size_b,
                is_ask_a=is_ask_a,
                is_ask_b=is_ask_b,
                chunks=data.slice_chunks,
                delay_sec=data.slice_delay_sec,
                reduce_only=False,
                market=(data.order_mode == "sliced"),
                label=f"QT-{trade_id}",
            )
        else:
            worst_price_a = mid_a * (1 - MARKET_SLIPPAGE) if is_ask_a else mid_a * (1 + MARKET_SLIPPAGE)
            worst_price_b = mid_b * (1 - MARKET_SLIPPAGE) if is_ask_b else mid_b * (1 + MARKET_SLIPPAGE)
            pair_result = await client.place_pair_orders(
                market_index_a=market_a,
                base_amount_a=size_a,
                price_a=worst_price_a,
                is_ask_a=is_ask_a,
                market_index_b=market_b,
                base_amount_b=size_b,
                price_b=worst_price_b,
                is_ask_b=is_ask_b,
                market=True,
            )
            result_a = pair_result.result_a
            result_b = pair_result.result_b
            completed = 1 if pair_result.success else 0
            if not pair_result.success:
                raise RuntimeError(pair_result.error or result_a.error or result_b.error or "Batch order failed")
    except Exception as e:
        logger.error(f"[QT-{trade_id}] Execution failed: {e}", exc_info=True)
        _update_trade_status(trade_id, "failed")
        raise HTTPException(500, f"Order execution failed: {e}")

    if completed == 0 or not result_a or not result_b:
        _update_trade_status(trade_id, "failed")
        raise HTTPException(500, "No chunks filled")

    # Scale notional by fill ratio
    actual_notional = notional if data.order_mode == "market" else notional * (completed / data.slice_chunks)

    # Update trade with fill data
    now = datetime.now(timezone.utc)
    with Session(db_engine) as session:
        t = session.get(SimplePairTrade, trade_id)
        t.status = "open"
        t.entry_price_a = result_a.filled_price
        t.entry_price_b = result_b.filled_price
        t.fill_size_a = result_a.filled_amount
        t.fill_size_b = result_b.filled_amount
        t.entry_notional = actual_notional
        t.entry_time = now
        session.add(t)
        session.commit()
        session.refresh(t)
        return t


@router.get("")
async def list_quick_trades(status: str | None = None):
    """List quick trades, optionally filtered by status."""
    with Session(db_engine) as session:
        stmt = select(SimplePairTrade).order_by(SimplePairTrade.created_at.desc())
        if status:
            stmt = stmt.where(SimplePairTrade.status == status)
        trades = session.exec(stmt).all()
        return trades


@router.get("/{trade_id}")
async def get_quick_trade(trade_id: int):
    """Get a single quick trade."""
    with Session(db_engine) as session:
        trade = session.get(SimplePairTrade, trade_id)
        if not trade:
            raise HTTPException(404, "Trade not found")
        return trade


@router.patch("/{trade_id}")
async def update_quick_trade(trade_id: int, data: QuickTradeUpdate):
    """Update editable thresholds for an open quick trade."""
    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(400, "No fields to update")
    if any(value is None for value in update_data.values()):
        raise HTTPException(422, "Threshold values must be numbers")

    with Session(db_engine) as session:
        trade = session.get(SimplePairTrade, trade_id)
        if not trade:
            raise HTTPException(404, "Trade not found")
        if trade.status != "open":
            raise HTTPException(400, f"Trade is not open (status={trade.status})")

        for key, value in update_data.items():
            setattr(trade, key, value)

        session.add(trade)
        session.commit()
        session.refresh(trade)
        return trade


@router.post("/{trade_id}/close")
async def close_quick_trade(trade_id: int):
    """Manually close an open quick trade."""
    with Session(db_engine) as session:
        trade = session.get(SimplePairTrade, trade_id)
        if not trade:
            raise HTTPException(404, "Trade not found")
        if trade.status != "open":
            raise HTTPException(400, f"Trade is not open (status={trade.status})")

    await _close_trade(trade_id, exit_reason="manual")

    with Session(db_engine) as session:
        return session.get(SimplePairTrade, trade_id)


async def _close_trade(trade_id: int, exit_reason: str):
    """Close an open simple trade by executing reverse orders."""
    from backend.engine.pair_job import _get_lighter_client
    from backend.engine.order_executor import MARKET_SLIPPAGE, execute_chunked_pair_orders
    from backend.services.market_data import fetch_orderbook

    lock = _get_lock(trade_id)
    async with lock:
        with Session(db_engine) as session:
            trade = session.get(SimplePairTrade, trade_id)
            if not trade or trade.status != "open":
                return

        client = await _get_lighter_client(trade.credential_id)
        if not client:
            logger.error(f"[QT-{trade_id}] No credential for close")
            return

        # Reverse direction: if we bought A and sold B, now sell A and buy B
        is_ask_a = trade.direction == 1   # sell A to close long
        is_ask_b = trade.direction == -1  # sell B to close long

        try:
            if trade.order_mode in ("sliced", "limit"):
                result_a, result_b, completed = await execute_chunked_pair_orders(
                    client=client,
                    market_a=trade.lighter_market_a,
                    market_b=trade.lighter_market_b,
                    size_a=trade.fill_size_a,
                    size_b=trade.fill_size_b,
                    is_ask_a=is_ask_a,
                    is_ask_b=is_ask_b,
                    chunks=trade.slice_chunks,
                    delay_sec=trade.slice_delay_sec,
                    reduce_only=True,
                    market=(trade.order_mode == "sliced"),
                    label=f"QT-{trade_id}-close",
                )
            else:
                ob_a, ob_b = await asyncio.gather(
                    fetch_orderbook(trade.lighter_market_a),
                    fetch_orderbook(trade.lighter_market_b),
                )
                mid_a = ob_a["mid_price"]
                mid_b = ob_b["mid_price"]
                if mid_a <= 0 or mid_b <= 0:
                    raise ValueError(f"Invalid mid prices: A={mid_a}, B={mid_b}")

                worst_price_a = mid_a * (1 - MARKET_SLIPPAGE) if is_ask_a else mid_a * (1 + MARKET_SLIPPAGE)
                worst_price_b = mid_b * (1 - MARKET_SLIPPAGE) if is_ask_b else mid_b * (1 + MARKET_SLIPPAGE)
                pair_result = await client.place_pair_orders(
                    market_index_a=trade.lighter_market_a,
                    base_amount_a=trade.fill_size_a,
                    price_a=worst_price_a,
                    is_ask_a=is_ask_a,
                    market_index_b=trade.lighter_market_b,
                    base_amount_b=trade.fill_size_b,
                    price_b=worst_price_b,
                    is_ask_b=is_ask_b,
                    market=True,
                    reduce_only=True,
                )
                result_a = pair_result.result_a
                result_b = pair_result.result_b
                completed = 1 if pair_result.success else 0
                if not pair_result.success:
                    raise RuntimeError(pair_result.error or result_a.error or result_b.error or "Batch close failed")
        except Exception as e:
            logger.error(f"[QT-{trade_id}] Close execution failed: {e}", exc_info=True)
            return

        if completed == 0 or not result_a or not result_b:
            logger.error(f"[QT-{trade_id}] Close: no chunks filled")
            return

        # Compute PnL
        pnl_a = _leg_pnl(trade.entry_price_a, result_a.filled_price, trade.fill_size_a, trade.direction == 1)
        pnl_b = _leg_pnl(trade.entry_price_b, result_b.filled_price, trade.fill_size_b, trade.direction == -1)
        total_pnl = pnl_a + pnl_b
        pnl_pct = total_pnl / trade.margin_usd * 100 if trade.margin_usd > 0 else 0

        now = datetime.now(timezone.utc)
        with Session(db_engine) as session:
            t = session.get(SimplePairTrade, trade_id)
            t.status = "closed"
            t.exit_price_a = result_a.filled_price
            t.exit_price_b = result_b.filled_price
            t.exit_time = now
            t.exit_reason = exit_reason
            t.pnl = total_pnl
            t.pnl_pct = pnl_pct
            session.add(t)
            session.commit()

        # Clean up lock
        _trade_locks.pop(trade_id, None)
        logger.info(f"[QT-{trade_id}] Closed ({exit_reason}): PnL=${total_pnl:.2f} ({pnl_pct:.2f}%)")


def _leg_pnl(entry_price: float, exit_price: float, size: float, is_long: bool) -> float:
    if is_long:
        return (exit_price - entry_price) * size
    else:
        return (entry_price - exit_price) * size


def _update_trade_status(trade_id: int, status: str):
    with Session(db_engine) as session:
        trade = session.get(SimplePairTrade, trade_id)
        if trade:
            trade.status = status
            session.add(trade)
            session.commit()
