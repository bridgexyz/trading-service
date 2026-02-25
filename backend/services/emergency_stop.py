"""Emergency stop: close all positions and optionally disable all pairs."""

import logging
from datetime import datetime, timezone

from sqlmodel import Session, select

from backend.database import engine
from backend.models.position import OpenPosition
from backend.models.trade import Trade
from backend.models.trading_pair import TradingPair
from backend.models.equity_snapshot import EquitySnapshot
from backend.models.credential import Credential
from backend.services.encryption import decrypt

logger = logging.getLogger(__name__)


async def run_emergency_stop(
    close_positions: bool = True,
    disable_pairs: bool = True,
) -> dict:
    """Execute emergency stop across all pairs.

    Returns dict with positions_closed, errors, pairs_disabled counts.
    """
    result = {"positions_closed": 0, "errors": [], "pairs_disabled": 0}

    if close_positions:
        with Session(engine) as session:
            positions = session.exec(select(OpenPosition)).all()

        for pos in positions:
            try:
                await _close_position(pos)
                result["positions_closed"] += 1
            except Exception as e:
                error_msg = f"Failed to close position {pos.id} (pair {pos.pair_id}): {e}"
                logger.error(error_msg)
                result["errors"].append(error_msg)

    if disable_pairs:
        from backend.engine.scheduler import remove_pair_job

        with Session(engine) as session:
            pairs = session.exec(
                select(TradingPair).where(TradingPair.is_enabled == True)
            ).all()

            for pair in pairs:
                pair.is_enabled = False
                pair.updated_at = datetime.now(timezone.utc)
                session.add(pair)
                remove_pair_job(pair.id)
                result["pairs_disabled"] += 1

            session.commit()

    return result


async def _close_position(position: OpenPosition):
    """Close a single position by placing reverse orders."""
    from backend.services.lighter_client import LighterClient

    with Session(engine) as session:
        pair = session.get(TradingPair, position.pair_id)
        if not pair:
            raise ValueError(f"Pair {position.pair_id} not found")

        cred = session.exec(
            select(Credential).where(Credential.is_active == True)
        ).first()
        if not cred:
            raise ValueError("No active credential")

        pk = decrypt(cred.private_key_encrypted)
        client = LighterClient(
            host=cred.lighter_host,
            private_key=pk,
            api_key_index=cred.api_key_index,
            account_index=cred.account_index,
        )

    try:
        from backend.services.market_data import fetch_pair_data

        data = await fetch_pair_data(
            market_a=pair.lighter_market_a,
            market_b=pair.lighter_market_b,
            window_interval=pair.window_interval,
            window_candles=5,
            train_interval=pair.train_interval,
            train_candles=5,
        )
        current_price_a = float(data["prices_a"].iloc[-1])
        current_price_b = float(data["prices_b"].iloc[-1])

        dollar_per_unit = position.entry_price_a + abs(position.entry_hedge_ratio) * position.entry_price_b
        units = position.entry_notional / dollar_per_unit if dollar_per_unit > 0 else 0

        # Reverse directions for close
        is_ask_a = position.direction == 1
        is_ask_b = position.direction == -1

        size_a = abs(units)
        size_b = abs(units * position.entry_hedge_ratio)

        result_a = await client.place_order(
            market_index=pair.lighter_market_a,
            base_amount=size_a,
            price=current_price_a,
            is_ask=is_ask_a,
        )
        result_b = await client.place_order(
            market_index=pair.lighter_market_b,
            base_amount=size_b,
            price=current_price_b,
            is_ask=is_ask_b,
        )

        if not result_a.success or not result_b.success:
            err = result_a.error or result_b.error
            raise RuntimeError(f"Close order failed: {err}")

        # Compute PnL
        spread_change = (
            (current_price_a - position.entry_hedge_ratio * current_price_b)
            - position.entry_spread
        )
        pnl = position.direction * spread_change * units
        pnl_pct = pnl / pair.current_equity * 100 if pair.current_equity > 0 else 0

        direction_str = "Long A / Short B" if position.direction == 1 else "Short A / Long B"

        with Session(engine) as session:
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
                exit_reason="emergency_stop",
                duration_candles=0,
            )
            session.add(trade)

            db_pair = session.get(TradingPair, pair.id)
            db_pair.current_equity += pnl
            db_pair.updated_at = datetime.now(timezone.utc)
            session.add(db_pair)

            snapshot = EquitySnapshot(
                pair_id=pair.id,
                equity=round(db_pair.current_equity, 2),
                drawdown_pct=0.0,
            )
            session.add(snapshot)

            db_pos = session.get(OpenPosition, position.id)
            if db_pos:
                session.delete(db_pos)

            session.commit()

        logger.info(f"[emergency_stop] Closed position for pair {pair.name}: PnL=${pnl:.2f}")

    finally:
        await client.close()
