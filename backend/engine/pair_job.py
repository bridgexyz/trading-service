"""Core per-pair trading cycle.

This is the function APScheduler calls on each interval. It orchestrates:
data fetch → signal computation → entry/exit decisions → order execution → DB persistence.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlmodel import Session, select

from backend.database import engine
from backend.models.trading_pair import TradingPair
from backend.models.position import OpenPosition
from backend.models.trade import Trade
from backend.models.equity_snapshot import EquitySnapshot
from backend.models.job_log import JobLog
from backend.models.credential import Credential
from backend.services import signal_engine
from backend.services.encryption import decrypt

logger = logging.getLogger(__name__)
_pair_locks: dict[int, asyncio.Lock] = {}
_pair_locks_guard = asyncio.Lock()


def _notify(message: str):
    """Send a Telegram notification (fire-and-forget)."""
    try:
        from backend.services.telegram_bot import get_bot
        bot = get_bot()
        if bot and bot._loop:
            asyncio.run_coroutine_threadsafe(bot.send_notification(message), bot._loop)
    except Exception as e:
        logger.debug(f"Telegram notification failed: {e}")


async def run_pair_cycle(pair_id: int):
    """Run one cycle per pair, skipping if a prior cycle is still in-flight."""
    lock = await _get_pair_lock(pair_id)
    if lock.locked():
        logger.warning(f"[pair_{pair_id}] Skipping overlapping cycle")
        _log_cycle(
            pair_id,
            "skipped",
            action="cycle_skipped_overlap",
            message="Skipped cycle because previous run is still in progress",
        )
        return

    async with lock:
        await _run_pair_cycle_once(pair_id)


async def _get_pair_lock(pair_id: int) -> asyncio.Lock:
    async with _pair_locks_guard:
        lock = _pair_locks.get(pair_id)
        if lock is None:
            lock = asyncio.Lock()
            _pair_locks[pair_id] = lock
        return lock


async def _run_pair_cycle_once(pair_id: int):
    """Execute one trading cycle for a pair.

    Steps:
    1. Load pair config and credential
    2. Fetch market data from Hyperliquid
    3. Compute signals (z-score, hedge ratio, regime filters)
    4. If flat: evaluate entry → place orders
    5. If in position: evaluate exit → close position
    6. Log everything
    """
    pair_name = f"pair_{pair_id}"
    with Session(engine) as session:
        pair = session.get(TradingPair, pair_id)
        if not pair or not pair.is_enabled:
            return

        pair_name = pair.name
        logger.info(f"[{pair_name}] Starting cycle")

    try:
        # Step 1: Fetch market data
        from backend.services.market_data import fetch_pair_data

        # Fetch enough candles for both z-score and RSI (RSI needs rsi_period + 2)
        fetch_candles = max(pair.window_candles, pair.rsi_period + 2)

        data = await fetch_pair_data(
            asset_a=pair.asset_a,
            asset_b=pair.asset_b,
            window_interval=pair.window_interval,
            window_candles=fetch_candles,
            train_interval=pair.train_interval,
            train_candles=pair.train_candles,
            market_id_a=pair.lighter_market_a or None,
            market_id_b=pair.lighter_market_b or None,
        )

        prices_a = data["prices_a"]
        prices_b = data["prices_b"]
        train_a = data["train_a"]
        train_b = data["train_b"]

        # Build market data summary for logging (includes full close arrays for replay)
        mkt = {
            "prices_a": {"count": len(prices_a), "first": str(prices_a.index[0]) if not prices_a.empty else None, "last": str(prices_a.index[-1]) if not prices_a.empty else None, "closes": prices_a.values.tolist()},
            "prices_b": {"count": len(prices_b), "first": str(prices_b.index[0]) if not prices_b.empty else None, "last": str(prices_b.index[-1]) if not prices_b.empty else None, "closes": prices_b.values.tolist()},
            "train_a": {"count": len(train_a), "first": str(train_a.index[0]) if not train_a.empty else None, "last": str(train_a.index[-1]) if not train_a.empty else None, "closes": train_a.values.tolist()},
            "train_b": {"count": len(train_b), "first": str(train_b.index[0]) if not train_b.empty else None, "last": str(train_b.index[-1]) if not train_b.empty else None, "closes": train_b.values.tolist()},
        }

        if prices_a.empty or prices_b.empty or train_a.empty or train_b.empty:
            _log_cycle(pair_id, "error", message="Empty candle data from exchange",
                       market_data=mkt)
            return

        close_a = float(prices_a.iloc[-1])
        close_b = float(prices_b.iloc[-1])

        if len(prices_a) < fetch_candles or len(prices_b) < fetch_candles:
            _log_cycle(pair_id, "error", message="Insufficient price data",
                       close_a=close_a, close_b=close_b, market_data=mkt)
            return

        if len(train_a) < pair.train_candles or len(train_b) < pair.train_candles:
            _log_cycle(pair_id, "error", message="Insufficient training data",
                       close_a=close_a, close_b=close_b, market_data=mkt)
            return

        # Step 2: Compute signals
        signals = signal_engine.compute_signals(
            prices_a=prices_a.values,
            prices_b=prices_b.values,
            train_prices_a=train_a.values,
            train_prices_b=train_b.values,
            window_candles=pair.window_candles,
            train_candles=pair.train_candles,
            rsi_period=pair.rsi_period,
        )

        logger.info(
            f"[{pair_name}] z={signals.z_score:.3f} hr={signals.hedge_ratio:.4f} "
            f"hl={signals.half_life:.1f} rsi={signals.rsi:.1f} rsi_a={signals.rsi_a:.1f} rsi_b={signals.rsi_b:.1f}"
        )

        # Step 3: Check for open position
        with Session(engine) as session:
            position = session.exec(
                select(OpenPosition).where(OpenPosition.pair_id == pair_id)
            ).first()

        if position is None:
            # FLAT — evaluate entry
            await _handle_entry(pair, signals, prices_a, prices_b, close_a, close_b, mkt)
        else:
            # IN POSITION — evaluate exit
            await _handle_exit(pair, position, signals, prices_a, prices_b, close_a, close_b, mkt)

    except Exception as e:
        logger.error(f"[{pair_name}] Cycle error: {e}", exc_info=True)
        _notify(f"[{pair_name}] ERROR: {e}")
        _log_cycle(pair_id, "error", message=str(e))


async def _place_pair_order(client, pair, market_index, base_amount, price, is_ask, reduce_only=False):
    """Place a market order for a pair leg."""
    return await client.place_order(
        market_index=market_index,
        base_amount=base_amount,
        price=price,
        is_ask=is_ask,
        market=True,
        reduce_only=reduce_only,
    )


async def _execute_sliced_orders(
    client, pair, size_a, size_b, is_ask_a, is_ask_b, reduce_only=False
):
    """Execute an order in N smaller chunks with delays between each.

    Returns (last_result_a, last_result_b, completed_chunks).
    """
    from backend.services.market_data import fetch_orderbook

    chunk_size_a = size_a / pair.slice_chunks
    chunk_size_b = size_b / pair.slice_chunks

    last_result_a = None
    last_result_b = None
    completed = 0
    total_fill_qty_a = 0.0
    total_fill_value_a = 0.0
    total_fill_qty_b = 0.0
    total_fill_value_b = 0.0

    for i in range(pair.slice_chunks):
        # Fetch fresh orderbook mid-prices for slippage calculation
        ob_a, ob_b = await asyncio.gather(
            fetch_orderbook(pair.lighter_market_a),
            fetch_orderbook(pair.lighter_market_b),
        )
        mid_a = ob_a["mid_price"]
        mid_b = ob_b["mid_price"]

        if mid_a <= 0 or mid_b <= 0:
            logger.error(f"[{pair.name}] Sliced chunk {i+1}: invalid mid prices (A={mid_a}, B={mid_b}), stopping")
            break

        SLIPPAGE = 0.01
        worst_a = mid_a * (1 - SLIPPAGE) if is_ask_a else mid_a * (1 + SLIPPAGE)
        worst_b = mid_b * (1 - SLIPPAGE) if is_ask_b else mid_b * (1 + SLIPPAGE)

        result_a = await client.place_order(
            market_index=pair.lighter_market_a,
            base_amount=chunk_size_a,
            price=worst_a,
            is_ask=is_ask_a,
            market=True,
            reduce_only=reduce_only,
        )

        if not result_a.success:
            logger.error(f"[{pair.name}] Sliced chunk {i+1} leg A failed: {result_a.error}")
            break

        result_b = await client.place_order(
            market_index=pair.lighter_market_b,
            base_amount=chunk_size_b,
            price=worst_b,
            is_ask=is_ask_b,
            market=True,
            reduce_only=reduce_only,
        )

        if not result_b.success:
            # Leg A succeeded but leg B failed — rollback this chunk's leg A
            logger.warning(f"[{pair.name}] Sliced chunk {i+1} leg B failed, rolling back leg A")
            await client.cancel_order(
                market_index=pair.lighter_market_a, order_id=result_a.order_id
            )
            break

        last_result_a = result_a
        last_result_b = result_b
        completed += 1

        if result_a.filled_price and result_a.filled_amount:
            total_fill_qty_a += result_a.filled_amount
            total_fill_value_a += result_a.filled_price * result_a.filled_amount
        if result_b.filled_price and result_b.filled_amount:
            total_fill_qty_b += result_b.filled_amount
            total_fill_value_b += result_b.filled_price * result_b.filled_amount
        logger.info(f"[{pair.name}] Sliced chunk {completed}/{pair.slice_chunks} complete")

        if i < pair.slice_chunks - 1:
            await asyncio.sleep(pair.slice_delay_sec)

    # Set VWAP on the last results for accurate fill price tracking
    if last_result_a and total_fill_qty_a > 0:
        last_result_a.filled_price = total_fill_value_a / total_fill_qty_a
        last_result_a.filled_amount = total_fill_qty_a
    if last_result_b and total_fill_qty_b > 0:
        last_result_b.filled_price = total_fill_value_b / total_fill_qty_b
        last_result_b.filled_amount = total_fill_qty_b

    return last_result_a, last_result_b, completed


async def _execute_limit_sliced_orders(
    client, pair, size_a, size_b, is_ask_a, is_ask_b, reduce_only=False
):
    """Execute limit orders in N smaller chunks, then clean up unfilled orders.

    Places limit orders at orderbook mid-price (no slippage). After all chunks,
    waits 30 seconds, cancels unfilled orders, and sweeps any orphaned legs
    with market orders to ensure no single-sided exposure remains.

    Returns (last_result_a, last_result_b, completed_chunks).
    """
    from backend.services.market_data import fetch_orderbook

    chunk_size_a = size_a / pair.slice_chunks
    chunk_size_b = size_b / pair.slice_chunks

    last_result_a = None
    last_result_b = None
    completed = 0
    total_fill_qty_a = 0.0
    total_fill_value_a = 0.0
    total_fill_qty_b = 0.0
    total_fill_value_b = 0.0
    order_ids_a = []
    order_ids_b = []

    for i in range(pair.slice_chunks):
        ob_a, ob_b = await asyncio.gather(
            fetch_orderbook(pair.lighter_market_a),
            fetch_orderbook(pair.lighter_market_b),
        )
        mid_a = ob_a["mid_price"]
        mid_b = ob_b["mid_price"]

        if mid_a <= 0 or mid_b <= 0:
            logger.error(f"[{pair.name}] Limit chunk {i+1}: invalid mid prices (A={mid_a}, B={mid_b}), stopping")
            break

        # For entries, offset price 0.02% to cross spread slightly for faster fills
        # For exits (reduce_only), use exact mid-price
        LIMIT_OFFSET = 0.0002
        if not reduce_only:
            price_a = mid_a * (1 - LIMIT_OFFSET) if is_ask_a else mid_a * (1 + LIMIT_OFFSET)
            price_b = mid_b * (1 - LIMIT_OFFSET) if is_ask_b else mid_b * (1 + LIMIT_OFFSET)
        else:
            price_a = mid_a
            price_b = mid_b

        result_a = await client.place_order(
            market_index=pair.lighter_market_a,
            base_amount=chunk_size_a,
            price=price_a,
            is_ask=is_ask_a,
            market=False,
            reduce_only=reduce_only,
        )

        if not result_a.success:
            logger.error(f"[{pair.name}] Limit chunk {i+1} leg A failed: {result_a.error}")
            break

        result_b = await client.place_order(
            market_index=pair.lighter_market_b,
            base_amount=chunk_size_b,
            price=price_b,
            is_ask=is_ask_b,
            market=False,
            reduce_only=reduce_only,
        )

        if not result_b.success:
            logger.warning(f"[{pair.name}] Limit chunk {i+1} leg B failed, cancelling leg A")
            await client.cancel_order(
                market_index=pair.lighter_market_a, order_id=result_a.order_id
            )
            break

        last_result_a = result_a
        last_result_b = result_b
        completed += 1
        if result_a.order_id:
            order_ids_a.append(result_a.order_id)
        if result_b.order_id:
            order_ids_b.append(result_b.order_id)

        if result_a.filled_price and result_a.filled_amount:
            total_fill_qty_a += result_a.filled_amount
            total_fill_value_a += result_a.filled_price * result_a.filled_amount
        if result_b.filled_price and result_b.filled_amount:
            total_fill_qty_b += result_b.filled_amount
            total_fill_value_b += result_b.filled_price * result_b.filled_amount
        logger.info(f"[{pair.name}] Limit chunk {completed}/{pair.slice_chunks} placed")

        if i < pair.slice_chunks - 1:
            await asyncio.sleep(pair.slice_delay_sec)

    if completed == 0:
        return last_result_a, last_result_b, 0

    # Limit orders may take minutes to fill as maker orders on the book.
    # Don't wait or sweep — trust that both legs were submitted and let
    # the normal trading cycle handle reconciliation.
    # Use the limit prices as fill estimates (actual fills happen async).
    logger.info(
        f"[{pair.name}] Limit orders placed: {completed}/{pair.slice_chunks} chunks. "
        f"Orders may fill over time as maker."
    )

    # Set VWAP from order responses as best-effort fill estimates
    if last_result_a and total_fill_qty_a > 0:
        last_result_a.filled_price = total_fill_value_a / total_fill_qty_a
        last_result_a.filled_amount = total_fill_qty_a
    if last_result_b and total_fill_qty_b > 0:
        last_result_b.filled_price = total_fill_value_b / total_fill_qty_b
        last_result_b.filled_amount = total_fill_qty_b

    return last_result_a, last_result_b, completed


def _check_cooldown(pair: TradingPair) -> bool:
    """Check if pair is in cooldown or should enter cooldown. Returns True if entry should be skipped."""
    if pair.cooldown_candles <= 0:
        return False
    if pair.cooldown_losses <= 0 and pair.cooldown_drawdown_pct <= 0:
        return False

    # Already in active cooldown?
    if pair.cooldown_until and datetime.now(timezone.utc) < pair.cooldown_until:
        return True

    # Check consecutive losses from Trade table
    with Session(engine) as session:
        recent_trades = session.exec(
            select(Trade).where(Trade.pair_id == pair.id)
            .order_by(Trade.exit_time.desc()).limit(max(pair.cooldown_losses, 20))
        ).all()

    consecutive_losses = 0
    cumulative_loss_pct = 0.0
    for t in recent_trades:
        if t.pnl >= 0:
            break
        consecutive_losses += 1
        cumulative_loss_pct += abs(t.pnl_pct)

    triggered = False
    # Trigger 1: N+ consecutive losses AND cumulative % exceeds threshold
    if (pair.cooldown_losses > 0 and pair.cooldown_loss_pct > 0
            and consecutive_losses >= pair.cooldown_losses
            and cumulative_loss_pct >= pair.cooldown_loss_pct):
        triggered = True
    # Trigger 2: cumulative consecutive loss % exceeds max drawdown (any count)
    if pair.cooldown_drawdown_pct > 0 and cumulative_loss_pct >= pair.cooldown_drawdown_pct:
        triggered = True

    if triggered:
        from backend.engine.scheduler import _interval_to_minutes
        interval_min = _interval_to_minutes(pair.schedule_interval)
        cooldown_end = datetime.now(timezone.utc) + timedelta(minutes=interval_min * pair.cooldown_candles)
        with Session(engine) as session:
            db_pair = session.get(TradingPair, pair.id)
            db_pair.cooldown_until = cooldown_end
            session.add(db_pair)
            session.commit()
        logger.info(f"Pair {pair.id}: cooldown triggered ({consecutive_losses} losses, {cumulative_loss_pct:.1f}% cumulative), until {cooldown_end}")
        return True

    return False


async def _handle_entry(pair: TradingPair, signals, prices_a, prices_b, close_a: float, close_b: float, market_data: dict | None = None):
    """Evaluate and execute entry if conditions are met."""
    # Cooldown check — short-circuit before any API calls
    if _check_cooldown(pair):
        _log_cycle(pair.id, "success", signals=signals, action="skip:cooldown",
                   message="Entry paused: cooldown active",
                   close_a=close_a, close_b=close_b, market_data=market_data)
        return

    # Compute position size from account balance percentage
    lighter_client = await _get_lighter_client(pair.credential_id)
    if lighter_client is None:
        _log_cycle(pair.id, "error", signals=signals, message="No active credential",
                   close_a=close_a, close_b=close_b)
        return

    balance = await lighter_client.get_balance()

    position_size = balance * (pair.position_size_pct / 100.0)
    if position_size <= 0:
        _log_cycle(pair.id, "error", signals=signals, message=f"Insufficient balance: ${balance:.2f}",
                   close_a=close_a, close_b=close_b)
        return

    equity_floor = position_size * pair.min_equity_pct / 100.0

    # Track equity from balance (position sizing capital).
    # PnL calculations use entry_notional/leverage, so deposits don't inflate PnL.
    with Session(engine) as session:
        db_pair = session.get(TradingPair, pair.id)
        db_pair.current_equity = position_size
        session.add(db_pair)
        session.commit()

    entry = signal_engine.evaluate_entry(
        signals=signals,
        entry_z=pair.entry_z,
        max_half_life=pair.max_half_life,
        rsi_upper=pair.rsi_upper,
        rsi_lower=pair.rsi_lower,
        current_equity=position_size,
        equity_floor=equity_floor,
        leverage=pair.leverage,
        rsi_a_lower=pair.rsi_a_lower,
        rsi_a_upper=pair.rsi_a_upper,
        rsi_b_lower=pair.rsi_b_lower,
        rsi_b_upper=pair.rsi_b_upper,
    )

    if not entry.should_enter:
        action = f"skip:{entry.skip_reason}" if entry.skip_reason != "no_signal" else "none"
        _log_cycle(
            pair.id, "success", signals=signals, action=action,
            message=f"No entry: {entry.skip_reason}",
            close_a=close_a, close_b=close_b, market_data=market_data,
        )
        return

    # Place entry orders on Lighter
    current_price_a = float(prices_a.iloc[-1])
    current_price_b = float(prices_b.iloc[-1])
    dollar_per_unit = current_price_a + abs(signals.hedge_ratio) * current_price_b
    units = entry.notional / dollar_per_unit if dollar_per_unit > 0 else 0

    lighter_client = await _get_lighter_client(pair.credential_id)
    if lighter_client is None:
        _log_cycle(pair.id, "error", signals=signals, message="No active credential",
                   close_a=close_a, close_b=close_b)
        return

    # For long spread: buy A, sell B. For short spread: sell A, buy B.
    is_ask_a = entry.direction == -1  # short spread = sell A
    is_ask_b = entry.direction == 1   # long spread = sell B

    size_a = abs(units)
    size_b = abs(units * signals.hedge_ratio)

    order_mode = getattr(pair, "order_mode", "market")

    if order_mode == "sliced":
        result_a, result_b, completed_chunks = await _execute_sliced_orders(
            lighter_client, pair, size_a, size_b, is_ask_a, is_ask_b
        )
        if completed_chunks == 0:
            _log_cycle(pair.id, "error", signals=signals, action="entry_failed",
                       message="Sliced entry: 0 chunks completed",
                       close_a=close_a, close_b=close_b)
            return
        if completed_chunks < pair.slice_chunks:
            entry.notional = entry.notional * (completed_chunks / pair.slice_chunks)
            logger.warning(
                f"[{pair.name}] Partial sliced entry: {completed_chunks}/{pair.slice_chunks} chunks, "
                f"notional reduced to ${entry.notional:.0f}"
            )
            _notify(
                f"[{pair.name}] Partial sliced entry: {completed_chunks}/{pair.slice_chunks} chunks. "
                f"Notional: ${entry.notional:.0f}"
            )
    elif order_mode == "limit":
        result_a, result_b, completed_chunks = await _execute_limit_sliced_orders(
            lighter_client, pair, size_a, size_b, is_ask_a, is_ask_b
        )
        if completed_chunks == 0 or result_a is None or result_b is None:
            _log_cycle(pair.id, "error", signals=signals, action="entry_failed",
                       message="Limit entry: no paired position established",
                       close_a=close_a, close_b=close_b)
            return
        if completed_chunks < pair.slice_chunks:
            entry.notional = entry.notional * (completed_chunks / pair.slice_chunks)
            logger.warning(
                f"[{pair.name}] Partial limit entry: {completed_chunks}/{pair.slice_chunks} chunks, "
                f"notional reduced to ${entry.notional:.0f}"
            )
            _notify(
                f"[{pair.name}] Partial limit entry: {completed_chunks}/{pair.slice_chunks} chunks. "
                f"Notional: ${entry.notional:.0f}"
            )
    else:
        # Worst price with slippage tolerance for IOC market orders
        SLIPPAGE = 0.01
        worst_price_a = current_price_a * (1 - SLIPPAGE) if is_ask_a else current_price_a * (1 + SLIPPAGE)
        worst_price_b = current_price_b * (1 - SLIPPAGE) if is_ask_b else current_price_b * (1 + SLIPPAGE)

        result_a = await _place_pair_order(
            lighter_client, pair, pair.lighter_market_a, size_a, worst_price_a, is_ask_a
        )
        result_b = await _place_pair_order(
            lighter_client, pair, pair.lighter_market_b, size_b, worst_price_b, is_ask_b
        )

        if not result_a.success or not result_b.success:
            err = result_a.error or result_b.error
            # Cancel the successful leg to avoid orphaned single-sided position
            await _rollback_partial_fill(
                lighter_client, pair, result_a, result_b, "entry", signals
            )
            _log_cycle(pair.id, "error", signals=signals, action="entry_failed",
                        message=f"Order failed (rolled back): {err}",
                        close_a=close_a, close_b=close_b)
            return

    # Verify positions actually exist on the exchange
    # (skip for limit — already verified inside _execute_limit_sliced_orders)
    if order_mode in ("market", "sliced"):
        settle_delay = 2 if order_mode == "sliced" else 1
        await asyncio.sleep(settle_delay)

        exchange_positions = await lighter_client.get_positions()
        exchange_by_market = {p["market_index"]: p for p in exchange_positions}

        has_leg_a = pair.lighter_market_a in exchange_by_market
        has_leg_b = pair.lighter_market_b in exchange_by_market

        if not has_leg_a or not has_leg_b:
            missing = []
            if not has_leg_a:
                missing.append(f"leg A (market {pair.lighter_market_a})")
            if not has_leg_b:
                missing.append(f"leg B (market {pair.lighter_market_b})")
            _log_cycle(pair.id, "error", signals=signals, action="entry_not_confirmed",
                       message=f"Orders accepted but positions not found on exchange: {', '.join(missing)}",
                       close_a=close_a, close_b=close_b, market_data=market_data)
            _notify(f"[{pair.name}] Entry orders accepted but NOT confirmed on exchange. Positions missing: {', '.join(missing)}")
            return

        # Use exchange avg_entry_price as the true fill price
        exchange_fill_a = exchange_by_market[pair.lighter_market_a]["entry_price"]
        exchange_fill_b = exchange_by_market[pair.lighter_market_b]["entry_price"]
        logger.info(f"[{pair.name}] Exchange entry prices: A={exchange_fill_a}, B={exchange_fill_b}")

    # Save open position (re-check to prevent duplicates from race conditions)
    with Session(engine) as session:
        existing = session.exec(
            select(OpenPosition).where(OpenPosition.pair_id == pair.id)
        ).first()
        if existing:
            logger.warning(f"[{pair.name}] Position already exists, aborting entry")
            _log_cycle(pair.id, "skipped", signals=signals, action="entry_aborted_duplicate",
                       message="Position already existed at commit time",
                       close_a=close_a, close_b=close_b)
            return
        pos = OpenPosition(
            pair_id=pair.id,
            direction=entry.direction,
            entry_z=signals.z_score,
            entry_spread=signals.current_spread,
            entry_price_a=current_price_a,
            entry_price_b=current_price_b,
            entry_hedge_ratio=signals.hedge_ratio,
            entry_notional=entry.notional,
            lighter_order_id_a=result_a.order_id,
            lighter_order_id_b=result_b.order_id,
            fill_price_a=exchange_fill_a if order_mode in ("market", "sliced") else result_a.filled_price,
            fill_price_b=exchange_fill_b if order_mode in ("market", "sliced") else result_b.filled_price,  # limit mode sets filled_price from exchange
            fill_amount_a=result_a.filled_amount,
            fill_amount_b=result_b.filled_amount,
        )
        session.add(pos)
        # Clear cooldown on successful entry
        db_pair = session.get(TradingPair, pair.id)
        if db_pair.cooldown_until is not None:
            db_pair.cooldown_until = None
            session.add(db_pair)
        session.commit()

    direction_str = "entry_long" if entry.direction == 1 else "entry_short"
    logger.info(f"[{pair.name}] Entered {direction_str} at z={signals.z_score:.3f}")
    _notify(f"[{pair.name}] Entry {direction_str} | z={signals.z_score:.3f} | ${entry.notional:.0f}")
    _log_cycle(pair.id, "success", signals=signals, action=direction_str,
                message=f"Notional: ${entry.notional:.0f}",
                close_a=close_a, close_b=close_b, market_data=market_data,
                order_results=_build_order_results(result_a, result_b))

    # Reschedule to exit interval if separate exit schedule is enabled
    if pair.use_exit_schedule and pair.exit_schedule_interval:
        from backend.engine.scheduler import reschedule_pair_job
        reschedule_pair_job(pair.id, pair.exit_schedule_interval)
        logger.info(f"[{pair.name}] Rescheduled to exit interval: {pair.exit_schedule_interval}")


async def _handle_exit(pair: TradingPair, position: OpenPosition, signals, prices_a, prices_b, close_a: float, close_b: float, market_data: dict | None = None):
    """Evaluate and execute exit if conditions are met."""
    current_price_a = float(prices_a.iloc[-1])
    current_price_b = float(prices_b.iloc[-1])

    # Use entry-time equity (notional / leverage) as PnL denominator,
    # not pair.current_equity which could be inflated by deposits.
    entry_equity = position.entry_notional / pair.leverage if pair.leverage > 0 else position.entry_notional

    entry_time = position.entry_time if position.entry_time.tzinfo else position.entry_time.replace(tzinfo=timezone.utc)
    hours_held = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600
    exit_z = pair.exit_z_late if hours_held >= 8 else pair.exit_z_early

    exit_sig = signal_engine.evaluate_exit(
        signals=signals,
        position_direction=position.direction,
        entry_spread=position.entry_spread,
        entry_price_a=position.entry_price_a,
        entry_price_b=position.entry_price_b,
        entry_hedge_ratio=position.entry_hedge_ratio,
        entry_notional=position.entry_notional,
        current_equity=entry_equity,
        exit_z=exit_z,
        stop_z=pair.stop_z,
        stop_loss_pct=pair.stop_loss_pct,
        current_price_a=current_price_a,
        current_price_b=current_price_b,
    )

    if not exit_sig.should_exit:
        _log_cycle(
            pair.id, "success", signals=signals, action="hold",
            message=f"Unrealized: ${exit_sig.unrealized_pnl:.2f} ({exit_sig.unrealized_pct:.2f}%)",
            close_a=close_a, close_b=close_b, market_data=market_data,
        )
        return

    await execute_exit(
        pair, position, current_price_a, current_price_b,
        exit_reason=exit_sig.exit_reason,
        signals=signals, market_data=market_data,
    )


async def execute_exit(
    pair: TradingPair,
    position: OpenPosition,
    current_price_a: float,
    current_price_b: float,
    exit_reason: str,
    signals=None,
    market_data: dict | None = None,
):
    """Shared exit helper — places closing orders, records trade, cleans up position.

    Called by both _handle_exit (signal-based) and the stop-loss guardian.
    """
    close_a = current_price_a
    close_b = current_price_b
    entry_equity = position.entry_notional / pair.leverage if pair.leverage > 0 else position.entry_notional

    lighter_client = await _get_lighter_client(pair.credential_id)
    if lighter_client is None:
        _log_cycle(pair.id, "error", signals=signals, message="No active credential for exit",
                   close_a=close_a, close_b=close_b)
        return

    # Calculate fallback sizes from entry notional
    dollar_per_unit = position.entry_price_a + abs(position.entry_hedge_ratio) * position.entry_price_b
    units = position.entry_notional / dollar_per_unit if dollar_per_unit > 0 else 0
    fallback_size_a = abs(units)
    fallback_size_b = abs(units * position.entry_hedge_ratio)

    # 1. Cancel all unfilled entry orders
    logger.info(f"[{pair.name}] Cancelling open orders before exit")
    await lighter_client.cancel_all_orders()
    await asyncio.sleep(2)

    # Snapshot realized PnL before exit (for delta calculation)
    pnl_before = await lighter_client.get_realized_pnl(
        [pair.lighter_market_a, pair.lighter_market_b]
    )

    # 2. Get actual open position sizes from exchange
    exchange_positions = await lighter_client.get_positions()
    exchange_by_market = {p["market_index"]: p for p in exchange_positions}

    pos_a = exchange_by_market.get(pair.lighter_market_a)
    pos_b = exchange_by_market.get(pair.lighter_market_b)
    size_a = pos_a["size"] if pos_a else fallback_size_a
    size_b = pos_b["size"] if pos_b else fallback_size_b

    if pos_a:
        logger.info(f"[{pair.name}] Exit leg A: exchange size {size_a:.6f}")
    else:
        logger.warning(f"[{pair.name}] Exit leg A: no exchange position, using calculated size {size_a:.6f}")
    if pos_b:
        logger.info(f"[{pair.name}] Exit leg B: exchange size {size_b:.6f}")
    else:
        logger.warning(f"[{pair.name}] Exit leg B: no exchange position, using calculated size {size_b:.6f}")

    # Reverse directions for close
    is_ask_a = position.direction == 1   # was buy A, now sell A
    is_ask_b = position.direction == -1  # was sell B, now buy B

    order_mode = getattr(pair, "order_mode", "market")

    if order_mode == "sliced":
        result_a, result_b, completed_chunks = await _execute_sliced_orders(
            lighter_client, pair, size_a, size_b, is_ask_a, is_ask_b, reduce_only=True
        )
        if completed_chunks == 0:
            _log_cycle(pair.id, "error", signals=signals, action="exit_failed",
                       message="Sliced exit: 0 chunks completed",
                       close_a=close_a, close_b=close_b)
            return
        if completed_chunks < pair.slice_chunks:
            logger.warning(
                f"[{pair.name}] Partial sliced exit: {completed_chunks}/{pair.slice_chunks} chunks"
            )
            _notify(
                f"[{pair.name}] Partial sliced exit: {completed_chunks}/{pair.slice_chunks} chunks. "
                f"Remaining position will be closed next cycle."
            )
            _log_cycle(pair.id, "error", signals=signals, action="exit_partial",
                       message=f"Sliced exit partial: {completed_chunks}/{pair.slice_chunks} chunks",
                       close_a=close_a, close_b=close_b)
            return
    elif order_mode == "limit":
        result_a, result_b, completed_chunks = await _execute_limit_sliced_orders(
            lighter_client, pair, size_a, size_b, is_ask_a, is_ask_b, reduce_only=True
        )
        if completed_chunks == 0:
            _log_cycle(pair.id, "error", signals=signals, action="exit_failed",
                       message="Limit exit: 0 chunks placed",
                       close_a=close_a, close_b=close_b)
            return
    else:
        # Worst price with slippage tolerance
        SLIPPAGE = 0.01
        worst_price_a = current_price_a * (1 - SLIPPAGE) if is_ask_a else current_price_a * (1 + SLIPPAGE)
        worst_price_b = current_price_b * (1 - SLIPPAGE) if is_ask_b else current_price_b * (1 + SLIPPAGE)

        # Place exit orders based on order_mode with reduce_only
        result_a = await _place_pair_order(
            lighter_client, pair, pair.lighter_market_a, size_a, worst_price_a, is_ask_a, reduce_only=True
        )
        result_b = await _place_pair_order(
            lighter_client, pair, pair.lighter_market_b, size_b, worst_price_b, is_ask_b, reduce_only=True
        )

        if not result_a.success or not result_b.success:
            err = result_a.error or result_b.error
            await _rollback_partial_fill(
                lighter_client, pair, result_a, result_b, "exit", signals
            )
            _log_cycle(pair.id, "error", signals=signals, action="exit_failed",
                        message=f"Close order failed (rolled back): {err}",
                        close_a=close_a, close_b=close_b)
            return

    # Verify positions are actually closed on the exchange (with retries)
    # (skip for limit — already verified inside _execute_limit_sliced_orders)
    if order_mode in ("market", "sliced"):
        settle_delays = [3, 6, 10] if order_mode == "market" else [3, 6, 15]
        positions_closed = False
        has_leg_a = False
        has_leg_b = False

        for attempt, delay in enumerate(settle_delays, 1):
            await asyncio.sleep(delay)
            exchange_positions = await lighter_client.get_positions()
            exchange_markets = {p["market_index"] for p in exchange_positions}

            has_leg_a = pair.lighter_market_a in exchange_markets
            has_leg_b = pair.lighter_market_b in exchange_markets

            if not has_leg_a and not has_leg_b:
                positions_closed = True
                break

            if attempt < len(settle_delays):
                logger.info(
                    f"[{pair.name}] Exit verification attempt {attempt}/{len(settle_delays)}: "
                    f"positions still open, retrying..."
                )

        if not positions_closed:
            still_open = []
            if has_leg_a:
                still_open.append(f"leg A (market {pair.lighter_market_a})")
            if has_leg_b:
                still_open.append(f"leg B (market {pair.lighter_market_b})")
            _log_cycle(pair.id, "error", signals=signals, action="exit_not_confirmed",
                       message=f"Exit orders accepted but positions still open after {len(settle_delays)} checks: {', '.join(still_open)}",
                       close_a=close_a, close_b=close_b)
            return

    # Wait for exchange to settle realized PnL (sliced orders need time)
    if order_mode == "sliced":
        await asyncio.sleep(5)

    # Compute PnL from exchange realized PnL delta
    pnl_after = await lighter_client.get_realized_pnl(
        [pair.lighter_market_a, pair.lighter_market_b]
    )
    pnl_delta_a = pnl_after[pair.lighter_market_a] - pnl_before[pair.lighter_market_a]
    pnl_delta_b = pnl_after[pair.lighter_market_b] - pnl_before[pair.lighter_market_b]
    pnl = pnl_delta_a + pnl_delta_b
    logger.info(
        f"[{pair.name}] Exchange realized PnL delta: "
        f"A={pnl_delta_a:.2f}, B={pnl_delta_b:.2f}, total={pnl:.2f}"
    )

    # Fallback to price-based PnL if exchange delta is 0 (not yet settled)
    entry_pa = position.entry_price_a
    entry_pb = position.entry_price_b
    exit_pa = current_price_a
    exit_pb = current_price_b

    if pnl == 0:
        if exit_reason == "stop_loss":
            pnl = -pair.stop_loss_pct / 100 * entry_equity
        else:
            pnl_a = (exit_pa - entry_pa) * size_a * (1 if position.direction == 1 else -1)
            pnl_b = (exit_pb - entry_pb) * size_b * (-1 if position.direction == 1 else 1)
            pnl = pnl_a + pnl_b
        logger.warning(
            f"[{pair.name}] Exchange PnL delta was 0, using price-based fallback: ${pnl:.2f}"
        )

    pnl_pct = pnl / entry_equity * 100 if entry_equity > 0 else 0

    # Compute duration in candles from entry_time
    from backend.utils.constants import INTERVAL_HOURS
    et = position.entry_time if position.entry_time.tzinfo else position.entry_time.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - et).total_seconds()
    interval_sec = INTERVAL_HOURS.get(pair.window_interval, 1.0) * 3600
    duration = int(elapsed / interval_sec) if interval_sec > 0 else 0

    direction_str = "Long A / Short B" if position.direction == 1 else "Short A / Long B"

    with Session(engine) as session:
        # Save trade record
        trade = Trade(
            pair_id=pair.id,
            direction=direction_str,
            entry_time=position.entry_time,
            exit_time=datetime.now(timezone.utc),
            entry_price_a=entry_pa,
            exit_price_a=exit_pa,
            entry_price_b=entry_pb,
            exit_price_b=exit_pb,
            size_a=round(size_a, 4),
            size_b=round(size_b, 4),
            hedge_ratio=position.entry_hedge_ratio,
            pnl=round(pnl, 2),
            pnl_pct=round(pnl_pct, 2),
            exit_reason=exit_reason or "unknown",
            duration_candles=duration,
        )
        session.add(trade)

        # Update pair equity
        db_pair = session.get(TradingPair, pair.id)
        db_pair.current_equity += pnl
        db_pair.updated_at = datetime.now(timezone.utc)
        session.add(db_pair)

        # Save equity snapshot with drawdown from peak
        from sqlalchemy import func
        peak_equity = session.exec(
            select(func.max(EquitySnapshot.equity))
            .where(EquitySnapshot.pair_id == pair.id)
        ).one_or_none() or db_pair.current_equity
        new_equity = round(db_pair.current_equity, 2)
        dd_pct = round((new_equity - peak_equity) / peak_equity * 100, 2) if peak_equity > 0 else 0.0

        snapshot = EquitySnapshot(
            pair_id=pair.id,
            equity=new_equity,
            drawdown_pct=min(dd_pct, 0.0),
        )
        session.add(snapshot)

        # Delete open position
        db_pos = session.get(OpenPosition, position.id)
        if db_pos:
            session.delete(db_pos)

        session.commit()

    logger.info(f"[{pair.name}] Exited ({exit_reason}): PnL=${pnl:.2f} ({pnl_pct:.2f}%)")
    _notify(f"[{pair.name}] Exit ({exit_reason}) | PnL: ${pnl:.2f} ({pnl_pct:.2f}%)")
    _log_cycle(pair.id, "success", signals=signals, action=f"exit:{exit_reason}",
                message=f"PnL: ${pnl:.2f} ({pnl_pct:.2f}%)",
                close_a=close_a, close_b=close_b, market_data=market_data,
                order_results=_build_order_results(result_a, result_b))

    # Reschedule back to entry interval if separate exit schedule is enabled
    if pair.use_exit_schedule:
        from backend.engine.scheduler import reschedule_pair_job
        reschedule_pair_job(pair.id, pair.schedule_interval)
        logger.info(f"[{pair.name}] Rescheduled to entry interval: {pair.schedule_interval}")


async def _rollback_partial_fill(
    lighter_client,
    pair: TradingPair,
    result_a,
    result_b,
    stage: str,
    signals=None,
):
    """Cancel the successful leg when the other leg fails.

    In pair trading, both legs must execute. If one fails, cancel the other
    to avoid an orphaned single-sided position.
    """
    if result_a.success and not result_b.success:
        # Leg A succeeded, leg B failed → cancel A
        logger.warning(
            f"[{pair.name}] {stage}: Leg B failed, cancelling leg A (order {result_a.order_id})"
        )
        cancelled = await lighter_client.cancel_order(
            market_index=pair.lighter_market_a, order_id=result_a.order_id
        )
        if not cancelled:
            logger.error(
                f"[{pair.name}] CRITICAL: Failed to cancel leg A order {result_a.order_id}. "
                f"Manual intervention required."
            )
            _log_cycle(
                pair.id, "error", signals=signals, action=f"{stage}_rollback_failed",
                message=f"Could not cancel leg A order {result_a.order_id}",
            )

    elif result_b.success and not result_a.success:
        # Leg B succeeded, leg A failed → cancel B
        logger.warning(
            f"[{pair.name}] {stage}: Leg A failed, cancelling leg B (order {result_b.order_id})"
        )
        cancelled = await lighter_client.cancel_order(
            market_index=pair.lighter_market_b, order_id=result_b.order_id
        )
        if not cancelled:
            logger.error(
                f"[{pair.name}] CRITICAL: Failed to cancel leg B order {result_b.order_id}. "
                f"Manual intervention required."
            )
            _log_cycle(
                pair.id, "error", signals=signals, action=f"{stage}_rollback_failed",
                message=f"Could not cancel leg B order {result_b.order_id}",
            )


_lighter_client_cache: dict[int, "LighterClient"] = {}


def invalidate_lighter_client(credential_id: int):
    """Remove a cached client when credential is updated or deleted."""
    _lighter_client_cache.pop(credential_id, None)


async def _get_lighter_client(credential_id: int | None = None):
    """Get a shared LighterClient for a credential (singleton per credential_id).

    Sharing one client ensures the signing lock serializes orders across
    concurrent pair jobs that use the same account, preventing nonce races.
    """
    from backend.services.lighter_client import LighterClient

    with Session(engine) as session:
        if credential_id is not None:
            cred = session.get(Credential, credential_id)
        else:
            cred = session.exec(
                select(Credential).where(Credential.is_active == True)
            ).first()
        if not cred:
            return None

        if cred.id in _lighter_client_cache:
            return _lighter_client_cache[cred.id]

        pk = decrypt(cred.private_key_encrypted)
        client = LighterClient(
            host=cred.lighter_host,
            private_key=pk,
            api_key_index=cred.api_key_index,
            account_index=cred.account_index,
        )
        _lighter_client_cache[cred.id] = client
        return client


def _build_order_results(result_a, result_b) -> dict:
    """Build a dict summarizing order execution results for both legs."""
    def _order_dict(r):
        return {
            "order_id": r.order_id,
            "success": r.success,
            "error": r.error,
            "filled_price": r.filled_price,
            "filled_amount": r.filled_amount,
            "order_status": r.order_status,
            "raw_response": r.raw_response,
        }
    return {"leg_a": _order_dict(result_a), "leg_b": _order_dict(result_b)}


def _safe_float(v: float | None) -> float | None:
    """Return None for inf/nan so they don't end up in the DB."""
    if v is None:
        return None
    import math
    if math.isinf(v) or math.isnan(v):
        return None
    return v


def _log_cycle(
    pair_id: int,
    status: str,
    signals=None,
    action: str | None = None,
    message: str | None = None,
    close_a: float | None = None,
    close_b: float | None = None,
    market_data: dict | None = None,
    order_results: dict | None = None,
):
    """Write a JobLog entry."""
    # Merge candle data and order results into a single JSON blob
    combined_market_data = None
    if market_data or order_results:
        combined_market_data = {}
        if market_data:
            combined_market_data["candles"] = market_data
        if order_results:
            combined_market_data["orders"] = order_results

    with Session(engine) as session:
        log = JobLog(
            pair_id=pair_id,
            status=status,
            z_score=_safe_float(signals.z_score) if signals else None,
            hedge_ratio=_safe_float(signals.hedge_ratio) if signals else None,
            half_life=_safe_float(signals.half_life) if signals else None,
            adx=None,
            rsi=_safe_float(signals.rsi) if signals else None,
            action=action,
            close_a=_safe_float(close_a),
            close_b=_safe_float(close_b),
            message=message,
            market_data=combined_market_data,
        )
        session.add(log)
        session.commit()
