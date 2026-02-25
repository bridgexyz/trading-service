"""System API — health check, scheduler status, job logs, manual trigger, emergency stop."""

import math

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

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


@router.get("/logs", dependencies=[Depends(get_current_user)])
def job_logs(
    pair_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    stmt = select(JobLog).order_by(JobLog.timestamp.desc())
    if pair_id is not None:
        stmt = stmt.where(JobLog.pair_id == pair_id)
    if status is not None:
        stmt = stmt.where(JobLog.status == status)
    stmt = stmt.offset(offset).limit(limit)
    rows = session.exec(stmt).all()
    # Replace inf/nan with None so JSON serialization doesn't blow up.
    float_fields = ("z_score", "hedge_ratio", "half_life", "adx", "rsi", "close_a", "close_b")
    for row in rows:
        for f in float_fields:
            v = getattr(row, f, None)
            if isinstance(v, float) and (math.isinf(v) or math.isnan(v)):
                setattr(row, f, None)
    return rows


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
