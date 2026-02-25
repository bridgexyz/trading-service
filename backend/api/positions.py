"""Open positions API."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.database import get_session
from backend.models.position import OpenPosition
from backend.models.trading_pair import TradingPair
from backend.models.credential import Credential
from backend.services.market_data import fetch_orderbook, fetch_markets
from backend.services.encryption import decrypt
from backend.api.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/positions", tags=["positions"], dependencies=[Depends(get_current_user)])


@router.get("")
def list_positions(
    pair_id: int | None = None,
    session: Session = Depends(get_session),
):
    stmt = select(OpenPosition)
    if pair_id is not None:
        stmt = stmt.where(OpenPosition.pair_id == pair_id)
    return session.exec(stmt).all()


@router.post("/{pair_id}/close")
def close_position(pair_id: int, session: Session = Depends(get_session)):
    """Manually close an open position."""
    pos = session.exec(
        select(OpenPosition).where(OpenPosition.pair_id == pair_id)
    ).first()
    if not pos:
        raise HTTPException(status_code=404, detail="No open position for this pair")

    # TODO Phase 4: actually send closing orders to Lighter, create Trade record
    return {"status": "pending", "message": "Manual close will be implemented in Phase 4."}


@router.get("/enriched")
async def enriched_positions(session: Session = Depends(get_session)):
    """Return open positions enriched with current prices and unrealized P&L."""
    positions = session.exec(select(OpenPosition)).all()
    if not positions:
        return []

    # Load all referenced pairs
    pair_ids = {p.pair_id for p in positions}
    pairs = session.exec(select(TradingPair).where(TradingPair.id.in_(pair_ids))).all()  # type: ignore[attr-defined]
    pair_map = {p.id: p for p in pairs}

    # Collect unique market IDs to fetch
    market_ids: set[int] = set()
    for pos in positions:
        pair = pair_map.get(pos.pair_id)
        if pair:
            market_ids.add(pair.lighter_market_a)
            market_ids.add(pair.lighter_market_b)

    # Fetch all orderbooks in parallel
    market_list = list(market_ids)
    orderbooks = await asyncio.gather(
        *(fetch_orderbook(mid) for mid in market_list)
    )
    price_map = {mid: ob["mid_price"] for mid, ob in zip(market_list, orderbooks)}

    result = []
    for pos in positions:
        pair = pair_map.get(pos.pair_id)
        if not pair:
            continue

        current_price_a = price_map.get(pair.lighter_market_a, 0.0)
        current_price_b = price_map.get(pair.lighter_market_b, 0.0)

        # Approximate unrealized P&L based on entry notional and price changes
        pnl = 0.0
        if pos.entry_price_a > 0 and pos.entry_price_b > 0:
            # Size in asset A terms
            size_a = pos.entry_notional / pos.entry_price_a / 2
            size_b = size_a * pos.entry_hedge_ratio
            pnl_a = (current_price_a - pos.entry_price_a) * pos.direction * size_a
            pnl_b = (pos.entry_price_b - current_price_b) * pos.direction * size_b
            pnl = pnl_a + pnl_b

        pnl_pct = (pnl / pos.entry_notional * 100) if pos.entry_notional else 0.0

        result.append({
            "id": pos.id,
            "pair_id": pos.pair_id,
            "pair_name": pair.name,
            "direction": pos.direction,
            "entry_z": pos.entry_z,
            "entry_price_a": pos.entry_price_a,
            "entry_price_b": pos.entry_price_b,
            "current_price_a": current_price_a,
            "current_price_b": current_price_b,
            "entry_notional": pos.entry_notional,
            "entry_time": pos.entry_time.isoformat(),
            "unrealized_pnl": round(pnl, 4),
            "unrealized_pnl_pct": round(pnl_pct, 2),
        })

    return result


@router.get("/exchange")
async def exchange_positions(session: Session = Depends(get_session)):
    """Return actual open positions from the Lighter exchange.

    Each individual market position is returned independently (not grouped by pair).
    This reflects the real state on the exchange, not the DB.
    """
    from backend.services.lighter_client import LighterClient

    # Get active credential
    cred = session.exec(
        select(Credential).where(Credential.is_active == True)
    ).first()
    if not cred:
        return []

    pk = decrypt(cred.private_key_encrypted)
    client = LighterClient(
        host=cred.lighter_host,
        private_key=pk,
        api_key_index=cred.api_key_index,
        account_index=cred.account_index,
    )

    try:
        # Fetch exchange positions and market list in parallel
        exchange_positions_raw, markets = await asyncio.gather(
            client.get_positions(),
            fetch_markets(),
        )
    finally:
        await client.close()

    if not exchange_positions_raw:
        return []

    # Build market_index → symbol lookup
    symbol_map = {}
    for m in markets:
        mid = m.get("market_id")
        if mid is not None:
            symbol_map[int(mid)] = m.get("symbol", f"Market {mid}")

    # Fetch current prices for all position markets
    market_indices = [p["market_index"] for p in exchange_positions_raw]
    orderbooks = await asyncio.gather(
        *(fetch_orderbook(mid) for mid in market_indices)
    )
    price_map = {mid: ob["mid_price"] for mid, ob in zip(market_indices, orderbooks)}

    result = []
    for pos in exchange_positions_raw:
        mid = pos["market_index"]
        current_price = price_map.get(mid, 0.0)
        entry_price = pos["entry_price"]
        size = pos["size"]
        side = pos["side"]

        # Compute unrealized PnL
        if entry_price > 0 and current_price > 0:
            if side == "long":
                pnl = (current_price - entry_price) * size
            else:
                pnl = (entry_price - current_price) * size
        else:
            pnl = 0.0

        notional = entry_price * size if entry_price > 0 else 0.0
        pnl_pct = (pnl / notional * 100) if notional > 0 else 0.0

        result.append({
            "market_index": mid,
            "symbol": symbol_map.get(mid, f"Market {mid}"),
            "side": side,
            "size": round(size, 6),
            "entry_price": entry_price,
            "current_price": current_price,
            "notional": round(notional, 2),
            "unrealized_pnl": round(pnl, 4),
            "unrealized_pnl_pct": round(pnl_pct, 2),
        })

    return result
