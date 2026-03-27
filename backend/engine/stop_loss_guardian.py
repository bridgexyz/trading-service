"""Global stop-loss guardian — fast-polling job that monitors all open positions."""

import asyncio
import logging

from sqlmodel import Session, select

from backend.database import engine
from backend.models.guardian_settings import GuardianSettings
from backend.models.position import OpenPosition
from backend.models.trading_pair import TradingPair
from backend.models.credential import Credential
from backend.services.encryption import decrypt

logger = logging.getLogger(__name__)


async def run_stop_loss_check():
    """Check all open positions for stop-loss breaches and close if triggered."""
    from backend.engine.pair_job import execute_exit, _log_cycle

    with Session(engine) as session:
        settings = session.get(GuardianSettings, 1)
        if not settings or not settings.enabled:
            return

        positions = session.exec(select(OpenPosition)).all()
        if not positions:
            return

        # Load pairs and credentials
        pair_ids = [p.pair_id for p in positions]
        pairs = session.exec(
            select(TradingPair).where(TradingPair.id.in_(pair_ids))
        ).all()
        pair_map = {p.id: p for p in pairs}

        active_creds = session.exec(
            select(Credential).where(Credential.is_active == True)
        ).all()
        cred_map = {c.id: c for c in active_creds}
        default_cred_id = active_creds[0].id if active_creds else None

    # Filter out excluded pairs, resolve credentials
    checks = []
    for pos in positions:
        pair = pair_map.get(pos.pair_id)
        if not pair or not pair.is_enabled or pair.guardian_excluded:
            continue
        cred_id = pair.credential_id if pair.credential_id is not None else default_cred_id
        checks.append((pair, pos, cred_id))

    if not checks:
        return

    # Fetch exchange positions from each needed credential
    needed_cred_ids = {cid for _, _, cid in checks if cid is not None}
    exchange_positions_by_cred = {}
    for cid in needed_cred_ids:
        cred = cred_map.get(cid)
        if not cred:
            continue
        try:
            exchange_positions_by_cred[cid] = await _fetch_exchange_positions(cred)
        except Exception as e:
            logger.error(f"[guardian] Failed to fetch exchange positions for credential {cid}: {e}")
            exchange_positions_by_cred[cid] = {}

    # Fetch orderbook mid-prices for current prices
    from backend.services.market_data import fetch_orderbook

    market_ids = set()
    for pair, _, _ in checks:
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

    # Check each position for stop-loss breach using real exchange data
    exit_tasks = []
    for pair, pos, cred_id in checks:
        price_a = mid_prices.get(pair.lighter_market_a)
        price_b = mid_prices.get(pair.lighter_market_b)

        if price_a is None or price_b is None or price_a <= 0 or price_b <= 0:
            logger.warning(f"[guardian] Skipping {pair.name}: invalid prices (A={price_a}, B={price_b})")
            _log_cycle(pair.id, "error", action="guardian_check",
                       message=f"Invalid prices (A={price_a}, B={price_b})",
                       close_a=price_a, close_b=price_b)
            continue

        # Compute unrealized PnL from real exchange positions
        ex_positions = exchange_positions_by_cred.get(cred_id, {})
        ex_a = ex_positions.get(pair.lighter_market_a)
        ex_b = ex_positions.get(pair.lighter_market_b)

        if not ex_a and not ex_b:
            logger.debug(f"[guardian] {pair.name}: no exchange positions found on credential {cred_id}")
            continue

        # Sum PnL from each leg using real entry prices and sizes
        unreal_pnl = 0.0
        total_notional = 0.0
        for ex_pos, current_price in [(ex_a, price_a), (ex_b, price_b)]:
            if not ex_pos:
                continue
            entry_price = ex_pos["entry_price"]
            size = ex_pos["size"]
            side = ex_pos["side"]
            if entry_price > 0 and current_price > 0:
                if side == "long":
                    unreal_pnl += (current_price - entry_price) * size
                else:
                    unreal_pnl += (entry_price - current_price) * size
                total_notional += entry_price * size

        entry_equity = pos.entry_notional / pair.leverage if pair.leverage > 0 else pos.entry_notional
        unreal_pct = unreal_pnl / entry_equity * 100 if entry_equity != 0 else 0

        # Determine which stop_loss_pct to use
        stop_loss_pct = settings.stop_loss_pct_override if settings.stop_loss_pct_override is not None else pair.stop_loss_pct

        if stop_loss_pct > 0 and unreal_pct <= -stop_loss_pct:
            logger.warning(
                f"[guardian] STOP-LOSS triggered for {pair.name}: "
                f"unrealized=${unreal_pnl:.2f} ({unreal_pct:.2f}%) (threshold={-stop_loss_pct:.1f}%)"
            )
            _log_cycle(pair.id, "success", action="guardian_stop_loss",
                       message=f"Guardian triggered stop-loss: ${unreal_pnl:.2f} ({unreal_pct:.2f}%) (threshold: -{stop_loss_pct:.1f}%)",
                       close_a=price_a, close_b=price_b)
            exit_tasks.append((pair, pos, price_a, price_b))
        else:
            logger.debug(
                f"[guardian] {pair.name}: OK unrealized=${unreal_pnl:.2f} ({unreal_pct:.2f}%) (threshold: -{stop_loss_pct:.1f}%)"
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


async def _fetch_exchange_positions(cred: Credential) -> dict[int, dict]:
    """Fetch exchange positions for a credential, keyed by market_index."""
    from backend.services.lighter_client import LighterClient

    pk = decrypt(cred.private_key_encrypted)
    client = LighterClient(
        host=cred.lighter_host,
        private_key=pk,
        api_key_index=cred.api_key_index,
        account_index=cred.account_index,
    )
    try:
        raw = await client.get_positions()
        return {p["market_index"]: p for p in raw}
    finally:
        await client.close()


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
