"""Core per-pair trading cycle.

This is the function APScheduler calls on each interval. It orchestrates:
data fetch → signal computation → entry/exit decisions → order execution → DB persistence.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone

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
    except Exception:
        pass


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
    2. Fetch market data from Lighter
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

        data = await fetch_pair_data(
            market_a=pair.lighter_market_a,
            market_b=pair.lighter_market_b,
            window_interval=pair.window_interval,
            window_candles=pair.window_candles,
            train_interval=pair.train_interval,
            train_candles=pair.train_candles,
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

        if len(prices_a) < pair.window_candles or len(prices_b) < pair.window_candles:
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
            f"hl={signals.half_life:.1f} rsi={signals.rsi:.1f}"
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


async def _place_pair_order(client, pair, market_index, base_amount, price, is_ask):
    """Place a market or TWAP order depending on pair config."""
    if pair.twap_minutes > 0:
        return await client.place_twap_order(
            market_index=market_index,
            base_amount=base_amount,
            price=price,
            is_ask=is_ask,
            duration_minutes=pair.twap_minutes,
        )
    return await client.place_order(
        market_index=market_index,
        base_amount=base_amount,
        price=price,
        is_ask=is_ask,
        market=True,
    )


async def _handle_entry(pair: TradingPair, signals, prices_a, prices_b, close_a: float, close_b: float, market_data: dict | None = None):
    """Evaluate and execute entry if conditions are met."""
    # Compute position size from account balance percentage
    lighter_client = await _get_lighter_client()
    if lighter_client is None:
        _log_cycle(pair.id, "error", signals=signals, message="No active credential",
                   close_a=close_a, close_b=close_b)
        return

    try:
        balance = await lighter_client.get_balance()
    finally:
        await lighter_client.close()

    position_size = balance * (pair.position_size_pct / 100.0)
    if position_size <= 0:
        _log_cycle(pair.id, "error", signals=signals, message=f"Insufficient balance: ${balance:.2f}",
                   close_a=close_a, close_b=close_b)
        return

    equity_floor = position_size * pair.min_equity_pct / 100.0

    # Update tracked equity from balance-derived position size
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

    lighter_client = await _get_lighter_client()
    if lighter_client is None:
        _log_cycle(pair.id, "error", signals=signals, message="No active credential",
                   close_a=close_a, close_b=close_b)
        return

    try:
        # For long spread: buy A, sell B. For short spread: sell A, buy B.
        is_ask_a = entry.direction == -1  # short spread = sell A
        is_ask_b = entry.direction == 1   # long spread = sell B

        size_a = abs(units)
        size_b = abs(units * signals.hedge_ratio)

        result_a = await _place_pair_order(
            lighter_client, pair, pair.lighter_market_a, size_a, current_price_a, is_ask_a
        )
        result_b = await _place_pair_order(
            lighter_client, pair, pair.lighter_market_b, size_b, current_price_b, is_ask_b
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
        # (market orders can be accepted by SDK but cancelled by exchange)
        await asyncio.sleep(1)  # Brief delay for exchange settlement

        exchange_positions = await lighter_client.get_positions()
        exchange_markets = {p["market_index"] for p in exchange_positions}

        has_leg_a = pair.lighter_market_a in exchange_markets
        has_leg_b = pair.lighter_market_b in exchange_markets

        if not has_leg_a or not has_leg_b:
            missing = []
            if not has_leg_a:
                missing.append(f"leg A (market {pair.lighter_market_a})")
            if not has_leg_b:
                missing.append(f"leg B (market {pair.lighter_market_b})")
            _log_cycle(pair.id, "error", signals=signals, action="entry_not_confirmed",
                       message=f"Orders accepted but positions not found on exchange: {', '.join(missing)}",
                       close_a=close_a, close_b=close_b)
            _notify(f"[{pair.name}] Entry orders accepted but NOT confirmed on exchange. Positions missing: {', '.join(missing)}")
            return

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
            )
            session.add(pos)
            session.commit()

        direction_str = "entry_long" if entry.direction == 1 else "entry_short"
        logger.info(f"[{pair.name}] Entered {direction_str} at z={signals.z_score:.3f}")
        _notify(f"[{pair.name}] Entry {direction_str} | z={signals.z_score:.3f} | ${entry.notional:.0f}")
        _log_cycle(pair.id, "success", signals=signals, action=direction_str,
                    message=f"Notional: ${entry.notional:.0f}",
                    close_a=close_a, close_b=close_b, market_data=market_data,
                    order_results=_build_order_results(result_a, result_b))

    finally:
        await lighter_client.close()


async def _handle_exit(pair: TradingPair, position: OpenPosition, signals, prices_a, prices_b, close_a: float, close_b: float, market_data: dict | None = None):
    """Evaluate and execute exit if conditions are met."""
    current_price_a = float(prices_a.iloc[-1])
    current_price_b = float(prices_b.iloc[-1])

    exit_sig = signal_engine.evaluate_exit(
        signals=signals,
        position_direction=position.direction,
        entry_spread=position.entry_spread,
        entry_price_a=position.entry_price_a,
        entry_price_b=position.entry_price_b,
        entry_hedge_ratio=position.entry_hedge_ratio,
        entry_notional=position.entry_notional,
        current_equity=pair.current_equity,
        exit_z=pair.exit_z,
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

    # Place closing orders (reverse of entry)
    lighter_client = await _get_lighter_client()
    if lighter_client is None:
        _log_cycle(pair.id, "error", signals=signals, message="No active credential for exit",
                   close_a=close_a, close_b=close_b)
        return

    try:
        dollar_per_unit = position.entry_price_a + abs(position.entry_hedge_ratio) * position.entry_price_b
        units = position.entry_notional / dollar_per_unit if dollar_per_unit > 0 else 0

        # Reverse directions for close
        is_ask_a = position.direction == 1   # was buy A, now sell A
        is_ask_b = position.direction == -1  # was sell B, now buy B

        size_a = abs(units)
        size_b = abs(units * position.entry_hedge_ratio)

        result_a = await _place_pair_order(
            lighter_client, pair, pair.lighter_market_a, size_a, current_price_a, is_ask_a
        )
        result_b = await _place_pair_order(
            lighter_client, pair, pair.lighter_market_b, size_b, current_price_b, is_ask_b
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

        # Verify positions are actually closed on the exchange
        await asyncio.sleep(1)  # Brief delay for exchange settlement

        exchange_positions = await lighter_client.get_positions()
        exchange_markets = {p["market_index"] for p in exchange_positions}

        has_leg_a = pair.lighter_market_a in exchange_markets
        has_leg_b = pair.lighter_market_b in exchange_markets

        if has_leg_a or has_leg_b:
            still_open = []
            if has_leg_a:
                still_open.append(f"leg A (market {pair.lighter_market_a})")
            if has_leg_b:
                still_open.append(f"leg B (market {pair.lighter_market_b})")
            _log_cycle(pair.id, "error", signals=signals, action="exit_not_confirmed",
                       message=f"Exit orders accepted but positions still open: {', '.join(still_open)}",
                       close_a=close_a, close_b=close_b)
            return

        # Compute PnL
        if exit_sig.exit_reason == "stop_loss":
            pnl = -pair.stop_loss_pct / 100 * pair.current_equity
        else:
            spread_change = (current_price_a - position.entry_hedge_ratio * current_price_b) - position.entry_spread
            spread_units = units
            pnl = position.direction * spread_change * spread_units

        pnl_pct = pnl / pair.current_equity * 100 if pair.current_equity > 0 else 0

        # Determine duration (approximate in candles — we don't track entry index in live)
        duration = 0

        direction_str = "Long A / Short B" if position.direction == 1 else "Short A / Long B"

        with Session(engine) as session:
            # Save trade record
            trade = Trade(
                pair_id=pair.id,
                direction=direction_str,
                entry_time=position.entry_time,
                exit_time=datetime.now(timezone.utc),
                entry_price_a=position.entry_price_a,
                exit_price_a=current_price_a,
                entry_price_b=position.entry_price_b,
                exit_price_b=current_price_b,
                size_a=round(size_a, 4),
                size_b=round(size_b, 4),
                hedge_ratio=position.entry_hedge_ratio,
                pnl=round(pnl, 2),
                pnl_pct=round(pnl_pct, 2),
                exit_reason=exit_sig.exit_reason or "unknown",
                duration_candles=duration,
            )
            session.add(trade)

            # Update pair equity
            db_pair = session.get(TradingPair, pair.id)
            db_pair.current_equity += pnl
            db_pair.updated_at = datetime.now(timezone.utc)
            session.add(db_pair)

            # Save equity snapshot
            snapshot = EquitySnapshot(
                pair_id=pair.id,
                equity=round(db_pair.current_equity, 2),
                drawdown_pct=0.0,  # TODO: compute from peak
            )
            session.add(snapshot)

            # Delete open position
            db_pos = session.get(OpenPosition, position.id)
            if db_pos:
                session.delete(db_pos)

            session.commit()

        logger.info(f"[{pair.name}] Exited ({exit_sig.exit_reason}): PnL=${pnl:.2f} ({pnl_pct:.2f}%)")
        _notify(f"[{pair.name}] Exit ({exit_sig.exit_reason}) | PnL: ${pnl:.2f} ({pnl_pct:.2f}%)")
        _log_cycle(pair.id, "success", signals=signals, action=f"exit:{exit_sig.exit_reason}",
                    message=f"PnL: ${pnl:.2f} ({pnl_pct:.2f}%)",
                    close_a=close_a, close_b=close_b, market_data=market_data,
                    order_results=_build_order_results(result_a, result_b))

    finally:
        await lighter_client.close()


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


async def _get_lighter_client():
    """Get a LighterClient from the active credential."""
    from backend.services.lighter_client import LighterClient

    with Session(engine) as session:
        cred = session.exec(
            select(Credential).where(Credential.is_active == True)
        ).first()
        if not cred:
            return None

        pk = decrypt(cred.private_key_encrypted)
        return LighterClient(
            host=cred.lighter_host,
            private_key=pk,
            api_key_index=cred.api_key_index,
            account_index=cred.account_index,
        )


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
