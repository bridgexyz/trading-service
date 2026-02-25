"""Position sync — reconcile DB state with Lighter exchange on startup.

On server restart, the DB may have OpenPosition records that no longer match
the actual exchange state (e.g., orders were cancelled externally, manual trades
happened, or the server crashed mid-cycle). This module detects and resolves
discrepancies.

Scenarios handled:
1. DB has position, exchange has matching position → OK, no action
2. DB has position, exchange has NO position → stale DB record, clean up
3. Exchange has position not tracked in DB → auto-create OpenPosition if both legs match a pair
"""

import logging
from datetime import datetime, timezone

from sqlmodel import Session, select

from backend.database import engine
from backend.models.position import OpenPosition
from backend.models.trading_pair import TradingPair
from backend.models.job_log import JobLog
from backend.models.credential import Credential
from backend.services.encryption import decrypt

logger = logging.getLogger(__name__)


async def sync_positions_on_startup():
    """Compare DB positions against Lighter exchange and reconcile.

    Called once during scheduler startup before jobs begin running.
    """
    from backend.services.lighter_client import LighterClient

    # Get active credential
    with Session(engine) as session:
        cred = session.exec(
            select(Credential).where(Credential.is_active == True)
        ).first()

    if not cred:
        logger.info("Position sync: no active credential, skipping")
        return

    pk = decrypt(cred.private_key_encrypted)
    client = LighterClient(
        host=cred.lighter_host,
        private_key=pk,
        api_key_index=cred.api_key_index,
        account_index=cred.account_index,
    )

    try:
        exchange_positions = await client.get_positions()
    except Exception as e:
        logger.error(f"Position sync: failed to fetch exchange positions: {e}")
        return
    finally:
        await client.close()

    # Build lookup of exchange positions by market_index
    exchange_by_market: dict[int, dict] = {}
    for pos in exchange_positions:
        exchange_by_market[pos["market_index"]] = pos

    with Session(engine) as session:
        db_positions = session.exec(select(OpenPosition)).all()

        if not db_positions and not exchange_positions:
            logger.info("Position sync: no positions in DB or exchange, all clear")
            return

        logger.info(
            f"Position sync: {len(db_positions)} DB positions, "
            f"{len(exchange_positions)} exchange positions"
        )

        # Track which exchange markets are accounted for
        matched_markets: set[int] = set()

        for db_pos in db_positions:
            pair = session.get(TradingPair, db_pos.pair_id)
            if not pair:
                # Pair was deleted but position record remains
                logger.warning(
                    f"Position sync: orphaned DB position {db_pos.id} for deleted pair {db_pos.pair_id}, removing"
                )
                session.delete(db_pos)
                continue

            # Check if exchange has positions for both legs of this pair
            has_leg_a = pair.lighter_market_a in exchange_by_market
            has_leg_b = pair.lighter_market_b in exchange_by_market

            if has_leg_a:
                matched_markets.add(pair.lighter_market_a)
            if has_leg_b:
                matched_markets.add(pair.lighter_market_b)

            if has_leg_a and has_leg_b:
                # Both legs present on exchange — position is valid
                logger.info(
                    f"Position sync: pair {pair.name} position confirmed on exchange"
                )
            elif has_leg_a or has_leg_b:
                # Only one leg present — partial fill / orphan
                missing_leg = "B" if has_leg_a else "A"
                present_leg = "A" if has_leg_a else "B"
                logger.warning(
                    f"Position sync: pair {pair.name} has leg {present_leg} on exchange "
                    f"but missing leg {missing_leg}. Manual review recommended."
                )
                _log_sync_event(
                    session, db_pos.pair_id,
                    f"Partial position detected: leg {missing_leg} missing on exchange. "
                    f"Leg {present_leg} still open. Manual intervention may be needed.",
                )
            else:
                # Neither leg on exchange — stale DB record from unfilled orders.
                logger.warning(
                    f"Position sync: pair {pair.name} has DB position but no exchange positions. "
                    f"Removing stale DB record."
                )
                _log_sync_event(
                    session, db_pos.pair_id,
                    f"Stale position removed (direction={db_pos.direction}, "
                    f"notional=${db_pos.entry_notional:.0f}): exchange has no matching positions.",
                )
                session.delete(db_pos)

        # Auto-recover exchange positions not tracked in DB
        tracked_markets: set[int] = set()
        for db_pos in db_positions:
            p = session.get(TradingPair, db_pos.pair_id)
            if p:
                tracked_markets.add(p.lighter_market_a)
                tracked_markets.add(p.lighter_market_b)

        # Try to match untracked positions to enabled pair configs
        all_pairs = session.exec(
            select(TradingPair).where(TradingPair.is_enabled == True)
        ).all()
        for pair in all_pairs:
            # Skip pairs that already have a DB position
            if any(dp.pair_id == pair.id for dp in db_positions):
                continue
            has_a = pair.lighter_market_a in exchange_by_market
            has_b = pair.lighter_market_b in exchange_by_market
            if has_a and has_b:
                ex_a = exchange_by_market[pair.lighter_market_a]
                ex_b = exchange_by_market[pair.lighter_market_b]
                direction = 1 if ex_a["side"] == "long" else -1
                size_a = ex_a["size"]
                size_b = ex_b["size"]
                notional = ex_a["entry_price"] * size_a + ex_b["entry_price"] * size_b
                hedge_ratio = size_b / size_a if size_a > 0 else 0
                pos = OpenPosition(
                    pair_id=pair.id,
                    direction=direction,
                    entry_z=0,
                    entry_spread=0,
                    entry_price_a=ex_a["entry_price"],
                    entry_price_b=ex_b["entry_price"],
                    entry_hedge_ratio=hedge_ratio,
                    entry_notional=notional,
                )
                session.add(pos)
                tracked_markets.add(pair.lighter_market_a)
                tracked_markets.add(pair.lighter_market_b)
                logger.warning(
                    f"Position sync: auto-created DB position for {pair.name} "
                    f"(direction={direction}, notional=${notional:.0f})"
                )
                _log_sync_event(
                    session, pair.id,
                    f"Auto-recovered position from exchange "
                    f"(direction={direction}, hedge_ratio={hedge_ratio:.4f}, notional=${notional:.0f})",
                )
            elif has_a or has_b:
                present = "A" if has_a else "B"
                missing = "B" if has_a else "A"
                logger.warning(
                    f"Position sync: pair {pair.name} has leg {present} on exchange "
                    f"but no leg {missing} and no DB position. Manual review needed."
                )

        # Remaining unmatched exchange positions — warn only
        for market_idx, ex_pos in exchange_by_market.items():
            if market_idx not in tracked_markets:
                logger.warning(
                    f"Position sync: exchange has position in market {market_idx} "
                    f"({ex_pos['side']}, size={ex_pos['size']:.4f}) not tracked by any DB pair. "
                    f"This may be a manually opened position or from a deleted pair."
                )

        session.commit()

    logger.info("Position sync complete")


def _log_sync_event(session: Session, pair_id: int, message: str):
    """Write a sync event to the job log."""
    log = JobLog(
        pair_id=pair_id,
        status="warning",
        action="position_sync",
        message=message,
    )
    session.add(log)
