"""Trade history API."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.database import get_session
from backend.models.trade import Trade
from backend.api.deps import get_current_user

router = APIRouter(prefix="/api/trades", tags=["trades"], dependencies=[Depends(get_current_user)])


@router.get("")
def list_trades(
    pair_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    stmt = select(Trade).order_by(Trade.exit_time.desc())
    if pair_id is not None:
        stmt = stmt.where(Trade.pair_id == pair_id)
    stmt = stmt.offset(offset).limit(limit)
    return session.exec(stmt).all()


@router.get("/{trade_id}")
def get_trade(trade_id: int, session: Session = Depends(get_session)):
    trade = session.get(Trade, trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    return trade
