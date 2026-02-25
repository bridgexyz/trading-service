"""Dashboard API — summary stats and equity curves."""

import logging

from fastapi import APIRouter, Depends
from sqlmodel import Session, select, func

from backend.database import get_session
from backend.api.deps import get_current_user
from backend.models.trade import Trade
from backend.models.trading_pair import TradingPair
from backend.models.equity_snapshot import EquitySnapshot
from backend.models.credential import Credential
from backend.services.encryption import decrypt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(get_current_user)])


@router.get("/summary")
async def dashboard_summary(session: Session = Depends(get_session)):
    """Aggregated stats across all pairs."""
    pairs = session.exec(select(TradingPair)).all()
    trades = session.exec(select(Trade)).all()

    total_pnl = sum(t.pnl for t in trades)
    winning = [t for t in trades if t.pnl > 0]
    win_rate = len(winning) / len(trades) * 100 if trades else 0.0

    # Fetch real position count from exchange
    exchange_position_count = 0
    cred = session.exec(
        select(Credential).where(Credential.is_active == True)
    ).first()
    if cred:
        try:
            from backend.services.lighter_client import LighterClient

            pk = decrypt(cred.private_key_encrypted)
            client = LighterClient(
                host=cred.lighter_host,
                private_key=pk,
                api_key_index=cred.api_key_index,
                account_index=cred.account_index,
            )
            try:
                positions = await client.get_positions()
                exchange_position_count = len(positions)
            finally:
                await client.close()
        except Exception as e:
            logger.warning(f"Could not fetch exchange positions for summary: {e}")

    return {
        "total_pairs": len(pairs),
        "active_pairs": sum(1 for p in pairs if p.is_enabled),
        "open_positions": exchange_position_count,
        "total_trades": len(trades),
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(win_rate, 1),
    }


@router.get("/equity/{pair_id}")
def pair_equity_curve(pair_id: int, session: Session = Depends(get_session)):
    """Equity curve data for one pair."""
    snapshots = session.exec(
        select(EquitySnapshot)
        .where(EquitySnapshot.pair_id == pair_id)
        .order_by(EquitySnapshot.timestamp)
    ).all()
    return [
        {
            "timestamp": s.timestamp.isoformat(),
            "equity": round(s.equity, 2),
            "drawdown_pct": round(s.drawdown_pct, 2),
        }
        for s in snapshots
    ]
