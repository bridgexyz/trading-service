"""System API — health check, scheduler status, job logs, manual trigger, emergency stop."""

import math
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func as sa_func
from sqlmodel import Session, func, select

from backend.database import get_session
from backend.models.job_log import JobLog
from backend.api.deps import get_current_user

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
def health_check():
    return {"status": "ok"}


@router.get("/scheduler", dependencies=[Depends(get_current_user)])
def scheduler_status():
    """Current scheduler state with job details."""
    from backend.engine.scheduler import get_scheduler_status
    return get_scheduler_status()


@router.post("/trigger/{pair_id}", dependencies=[Depends(get_current_user)])
async def trigger_pair(pair_id: int):
    """Manually trigger one cycle of a pair's trading job."""
    from backend.engine.pair_job import run_pair_cycle
    try:
        await run_pair_cycle(pair_id)
        return {"status": "ok", "message": f"Cycle completed for pair {pair_id}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/logs/actions", dependencies=[Depends(get_current_user)])
def log_actions(session: Session = Depends(get_session)):
    """Return distinct action values from job logs."""
    rows = session.exec(
        select(JobLog.action).where(JobLog.action.is_not(None)).distinct().order_by(JobLog.action)
    ).all()
    return [a for a in rows if a]


@router.get("/logs", dependencies=[Depends(get_current_user)])
def job_logs(
    pair_id: int | None = None,
    status: str | None = None,
    action: str | None = None,
    z_min: float | None = None,
    z_max: float | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    base = select(JobLog)
    if pair_id is not None:
        base = base.where(JobLog.pair_id == pair_id)
    if status is not None:
        base = base.where(JobLog.status == status)
    if action is not None:
        base = base.where(JobLog.action == action)
    if z_min is not None:
        base = base.where(sa_func.abs(JobLog.z_score) >= z_min)
    if z_max is not None:
        base = base.where(sa_func.abs(JobLog.z_score) <= z_max)
    if date_from is not None:
        base = base.where(JobLog.timestamp >= datetime.fromisoformat(date_from))
    if date_to is not None:
        end = datetime.fromisoformat(date_to) + timedelta(days=1)
        base = base.where(JobLog.timestamp < end)

    total = session.exec(select(func.count()).select_from(base.subquery())).one()

    stmt = base.order_by(JobLog.timestamp.desc()).offset(offset).limit(limit)
    rows = session.exec(stmt).all()
    # Replace inf/nan with None so JSON serialization doesn't blow up.
    float_fields = ("z_score", "hedge_ratio", "half_life", "adx", "rsi", "close_a", "close_b")
    for row in rows:
        for f in float_fields:
            v = getattr(row, f, None)
            if isinstance(v, float) and (math.isinf(v) or math.isnan(v)):
                setattr(row, f, None)
    return {"items": rows, "total": total}


class EmergencyStopRequest(BaseModel):
    close_positions: bool = True
    disable_pairs: bool = True


@router.post("/emergency-stop", dependencies=[Depends(get_current_user)])
async def emergency_stop(body: EmergencyStopRequest):
    """Emergency stop: close all positions and/or disable all pairs."""
    from backend.services.emergency_stop import run_emergency_stop

    result = await run_emergency_stop(
        close_positions=body.close_positions,
        disable_pairs=body.disable_pairs,
    )
    return result
