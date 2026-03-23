"""Global stop-loss guardian — fast-polling job that monitors all open positions."""

import asyncio
import logging

from sqlmodel import Session, select

from backend.database import engine
from backend.models.guardian_settings import GuardianSettings
from backend.models.position import OpenPosition
from backend.models.trading_pair import TradingPair

logger = logging.getLogger(__name__)


async def run_stop_loss_check():
    """Check all open positions for stop-loss breaches and close if triggered."""
    # Avoid circular import — pair_job imports from models/services that import engine
    from backend.engine.pair_job import execute_exit, _log_cycle

    with Session(engine) as session:
        settings = session.get(GuardianSettings, 1)
        if not settings or not settings.enabled:
            return

        positions = session.exec(select(OpenPosition)).all()
        if not positions:
            return

        # Load pairs for each position
        pair_ids = [p.pair_id for p in positions]
        pairs = session.exec(
            select(TradingPair).where(TradingPair.id.in_(pair_ids))
        ).all()
        pair_map = {p.id: p for p in pairs}

    # Filter out excluded pairs
    checks = []
    for pos in positions:
        pair = pair_map.get(pos.pair_id)
        if not pair or not pair.is_enabled or pair.guardian_excluded:
            continue
        checks.append((pair, pos))

    if not checks:
        return

    # Collect unique market IDs and fetch orderbook mid-prices in parallel
    from backend.services.market_data import fetch_orderbook

    market_ids = set()
    for pair, _ in checks:
        market_ids.add(pair.lighter_market_a)
        market_ids.add(pair.lighter_market_b)

    orderbook_tasks = {mid: fetch_orderbook(mid) for mid in market_ids}
    results = await asyncio.gather(*orderbook_tasks.values(), return_exceptions=True)
    mid_prices = {}
    for mid, result in zip(orderbook_tasks.keys(), results):
        if isinstance(result, Exception):
            logger.error(f"[guardian] Failed to fetch orderbook for market {mid}: {result}")
            mid_prices[mid] = None
        else:
            mid_prices[mid] = result.get("mid_price", 0.0)

    # Check each position for stop-loss breach, collect triggered exits
    exit_tasks = []
    for pair, pos in checks:
        price_a = mid_prices.get(pair.lighter_market_a)
        price_b = mid_prices.get(pair.lighter_market_b)

        if price_a is None or price_b is None or price_a <= 0 or price_b <= 0:
            logger.warning(f"[guardian] Skipping {pair.name}: invalid prices (A={price_a}, B={price_b})")
            _log_cycle(pair.id, "error", action="guardian_check",
                       message=f"Invalid prices (A={price_a}, B={price_b})",
                       close_a=price_a, close_b=price_b)
            continue

        # Compute unrealized PnL % using same formula as signal_engine.evaluate_exit
        entry_equity = pos.entry_notional / pair.leverage if pair.leverage > 0 else pos.entry_notional
        exit_spread = price_a - pos.entry_hedge_ratio * price_b
        spread_change = exit_spread - pos.entry_spread
        dollar_per_unit = pos.entry_price_a + abs(pos.entry_hedge_ratio) * pos.entry_price_b
        spread_units = pos.entry_notional / dollar_per_unit if dollar_per_unit != 0 else 0
        unreal_pnl = pos.direction * spread_change * spread_units
        unreal_pct = unreal_pnl / entry_equity * 100 if entry_equity != 0 else 0

        # Determine which stop_loss_pct to use
        stop_loss_pct = settings.stop_loss_pct_override if settings.stop_loss_pct_override is not None else pair.stop_loss_pct

        if stop_loss_pct > 0 and unreal_pct <= -stop_loss_pct:
            logger.warning(
                f"[guardian] STOP-LOSS triggered for {pair.name}: "
                f"unrealized={unreal_pct:.2f}% (threshold={-stop_loss_pct:.1f}%)"
            )
            _log_cycle(pair.id, "success", action="guardian_stop_loss",
                       message=f"Guardian triggered stop-loss: {unreal_pct:.2f}% (threshold: -{stop_loss_pct:.1f}%)",
                       close_a=price_a, close_b=price_b)
            exit_tasks.append((pair, pos, price_a, price_b))
        else:
            logger.debug(
                f"[guardian] {pair.name}: OK unrealized={unreal_pct:.2f}% (threshold: -{stop_loss_pct:.1f}%)"
            )

    # Execute all triggered exits in parallel
    if exit_tasks:
        results = await asyncio.gather(
            *[_guardian_exit(pair, pos, pa, pb, execute_exit, _log_cycle)
              for pair, pos, pa, pb in exit_tasks],
            return_exceptions=True,
        )
        for (pair, _, _, _), result in zip(exit_tasks, results):
            if isinstance(result, Exception):
                logger.error(f"[guardian] Exit gather error for {pair.name}: {result}", exc_info=True)


async def _guardian_exit(pair, pos, price_a, price_b, execute_exit, _log_cycle):
    """Execute a single guardian stop-loss exit with error handling."""
    try:
        await execute_exit(
            pair, pos, price_a, price_b,
            exit_reason="stop_loss",
        )
    except Exception as e:
        logger.error(f"[guardian] Failed to execute exit for {pair.name}: {e}", exc_info=True)
        _log_cycle(pair.id, "error", action="guardian_exit_failed",
                   message=f"Guardian exit failed: {e}",
                   close_a=price_a, close_b=price_b)
