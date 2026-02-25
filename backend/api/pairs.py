"""CRUD API for trading pairs."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlmodel import Session, select

from backend.database import get_session
from backend.models.trading_pair import TradingPair
from backend.models.position import OpenPosition
from backend.schemas.trading_pair import TradingPairCreate, TradingPairUpdate, TradingPairRead
from backend.api.deps import get_current_user

router = APIRouter(prefix="/api/pairs", tags=["pairs"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[TradingPairRead])
def list_pairs(
    enabled: bool | None = None,
    session: Session = Depends(get_session),
):
    stmt = select(TradingPair)
    if enabled is not None:
        stmt = stmt.where(TradingPair.is_enabled == enabled)
    return session.exec(stmt).all()


@router.post("", response_model=TradingPairRead, status_code=201)
def create_pair(
    data: TradingPairCreate,
    session: Session = Depends(get_session),
):
    payload = data.model_dump()
    if not payload.get("name"):
        payload["name"] = f"{payload['asset_a']}-{payload['asset_b']}"
    pair = TradingPair(**payload)
    session.add(pair)
    session.commit()
    session.refresh(pair)

    # Add scheduler job if enabled
    if pair.is_enabled:
        from backend.engine.scheduler import add_pair_job
        add_pair_job(pair.id, pair.schedule_interval)

    return pair


@router.get("/{pair_id}", response_model=TradingPairRead)
def get_pair(pair_id: int, session: Session = Depends(get_session)):
    pair = session.get(TradingPair, pair_id)
    if not pair:
        raise HTTPException(status_code=404, detail="Pair not found")
    return pair


@router.put("/{pair_id}", response_model=TradingPairRead)
def update_pair(
    pair_id: int,
    data: TradingPairUpdate,
    session: Session = Depends(get_session),
):
    pair = session.get(TradingPair, pair_id)
    if not pair:
        raise HTTPException(status_code=404, detail="Pair not found")

    update_data = data.model_dump(exclude_unset=True)

    # Validate full merged config so partial updates cannot bypass cross-field rules.
    merged = {**pair.model_dump(), **update_data}
    try:
        TradingPairCreate.model_validate(merged)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    for key, value in update_data.items():
        setattr(pair, key, value)
    pair.updated_at = datetime.now(timezone.utc)

    session.add(pair)
    session.commit()
    session.refresh(pair)

    # Reschedule if interval changed or enablement toggled
    from backend.engine.scheduler import add_pair_job, remove_pair_job
    if pair.is_enabled:
        add_pair_job(pair.id, pair.schedule_interval)
    else:
        remove_pair_job(pair.id)

    return pair


@router.delete("/{pair_id}", status_code=204)
def delete_pair(pair_id: int, session: Session = Depends(get_session)):
    pair = session.get(TradingPair, pair_id)
    if not pair:
        raise HTTPException(status_code=404, detail="Pair not found")

    # Check for open positions
    pos = session.exec(
        select(OpenPosition).where(OpenPosition.pair_id == pair_id)
    ).first()
    if pos:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete pair with open position. Close it first.",
        )

    from backend.engine.scheduler import remove_pair_job
    remove_pair_job(pair_id)

    session.delete(pair)
    session.commit()


@router.post("/{pair_id}/toggle", response_model=TradingPairRead)
def toggle_pair(pair_id: int, session: Session = Depends(get_session)):
    pair = session.get(TradingPair, pair_id)
    if not pair:
        raise HTTPException(status_code=404, detail="Pair not found")

    pair.is_enabled = not pair.is_enabled
    pair.updated_at = datetime.now(timezone.utc)
    session.add(pair)
    session.commit()
    session.refresh(pair)

    from backend.engine.scheduler import add_pair_job, remove_pair_job
    if pair.is_enabled:
        add_pair_job(pair.id, pair.schedule_interval)
    else:
        remove_pair_job(pair.id)

    return pair
