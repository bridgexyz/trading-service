"""Guardian API — settings and status for the global stop-loss guardian."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func as sa_func
from sqlmodel import Session, select

from backend.database import get_session
from backend.models.guardian_settings import GuardianSettings
from backend.models.position import OpenPosition
from backend.models.trading_pair import TradingPair
from backend.api.deps import get_current_user

router = APIRouter(
    prefix="/api/guardian",
    tags=["guardian"],
    dependencies=[Depends(get_current_user)],
)


def _get_or_create_settings(session: Session) -> GuardianSettings:
    settings = session.get(GuardianSettings, 1)
    if not settings:
        settings = GuardianSettings(id=1, updated_at=datetime.now(timezone.utc))
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings


@router.get("/settings")
def get_settings(session: Session = Depends(get_session)):
    return _get_or_create_settings(session)


class GuardianSettingsUpdate(BaseModel):
    enabled: bool | None = None
    interval_seconds: int | None = None
    stop_loss_pct_override: float | None = None


@router.patch("/settings")
def update_settings(
    body: GuardianSettingsUpdate,
    session: Session = Depends(get_session),
):
    settings = _get_or_create_settings(session)

    if body.enabled is not None:
        settings.enabled = body.enabled
    if body.interval_seconds is not None:
        settings.interval_seconds = max(10, min(body.interval_seconds, 300))
    # stop_loss_pct_override: allow setting to None (clear) or a value
    if "stop_loss_pct_override" in body.model_fields_set:
        settings.stop_loss_pct_override = body.stop_loss_pct_override

    settings.updated_at = datetime.now(timezone.utc)
    session.add(settings)
    session.commit()
    session.refresh(settings)

    # Update scheduler
    from backend.engine.scheduler import add_guardian_job, remove_guardian_job
    if settings.enabled:
        add_guardian_job(settings.interval_seconds)
    else:
        remove_guardian_job()

    return settings


@router.get("/status")
def guardian_status(session: Session = Depends(get_session)):
    from backend.engine.scheduler import scheduler, GUARDIAN_JOB_ID

    settings = _get_or_create_settings(session)
    job = scheduler.get_job(GUARDIAN_JOB_ID)

    # Count monitored positions with a single query
    position_count = session.exec(
        select(sa_func.count(OpenPosition.id))
        .join(TradingPair, OpenPosition.pair_id == TradingPair.id)
        .where(TradingPair.is_enabled == True)
        .where(TradingPair.guardian_excluded == False)
    ).one()

    return {
        "enabled": settings.enabled,
        "interval_seconds": settings.interval_seconds,
        "job_running": job is not None,
        "next_run": str(job.next_run_time) if job and job.next_run_time else None,
        "trigger": str(job.trigger) if job else None,
        "monitored_positions": position_count,
    }
