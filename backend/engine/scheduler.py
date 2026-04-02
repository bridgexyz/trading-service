"""APScheduler integration for FastAPI.

Manages per-pair interval jobs that run the trading engine.
"""

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlmodel import Session, select

from backend.database import engine
from backend.models.trading_pair import TradingPair
from backend.utils.constants import INTERVAL_HOURS

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def _job_id(pair_id: int) -> str:
    return f"pair_{pair_id}"


def _interval_to_minutes(interval: str) -> int:
    """Parse an interval string to total minutes."""
    if interval.endswith("m") and interval[:-1].isdigit():
        return int(interval[:-1])
    hours = INTERVAL_HOURS.get(interval, 4.0)
    return int(hours * 60)


def _next_interval_boundary(minutes: int) -> datetime:
    """Compute the next clean UTC time boundary for a given interval."""
    now = datetime.now(timezone.utc)
    total_minutes = now.hour * 60 + now.minute
    next_boundary = ((total_minutes // minutes) + 1) * minutes
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight + timedelta(minutes=next_boundary)


def _get_trigger(interval: str) -> IntervalTrigger:
    minutes = _interval_to_minutes(interval)
    # Align to UTC boundaries for sub-2h intervals
    if minutes < 120:
        start = _next_interval_boundary(minutes)
        return IntervalTrigger(minutes=minutes, start_date=start)
    return IntervalTrigger(hours=minutes / 60)


def add_pair_job(pair_id: int, schedule_interval: str):
    """Add or replace a scheduler job for a trading pair."""
    from backend.engine.pair_job import run_pair_cycle

    job_id = _job_id(pair_id)

    # Remove existing job if present
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    trigger = _get_trigger(schedule_interval)
    scheduler.add_job(
        run_pair_cycle,
        trigger=trigger,
        args=[pair_id],
        id=job_id,
        name=f"Pair {pair_id}",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )
    logger.info(f"Scheduled pair {pair_id} every {schedule_interval}")


def remove_pair_job(pair_id: int):
    """Remove a scheduler job for a trading pair."""
    job_id = _job_id(pair_id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info(f"Removed job for pair {pair_id}")


def reschedule_pair_job(pair_id: int, schedule_interval: str):
    """Reschedule an existing job with a new interval."""
    job_id = _job_id(pair_id)
    if scheduler.get_job(job_id):
        trigger = _get_trigger(schedule_interval)
        scheduler.reschedule_job(job_id, trigger=trigger)
        logger.info(f"Rescheduled pair {pair_id} to {schedule_interval}")
    else:
        add_pair_job(pair_id, schedule_interval)


GUARDIAN_JOB_ID = "stop_loss_guardian"


def add_guardian_job(interval_minutes: int):
    """Add or replace the global stop-loss guardian job."""
    from backend.engine.stop_loss_guardian import run_stop_loss_check

    if scheduler.get_job(GUARDIAN_JOB_ID):
        scheduler.remove_job(GUARDIAN_JOB_ID)

    scheduler.add_job(
        run_stop_loss_check,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id=GUARDIAN_JOB_ID,
        name="Stop-Loss Guardian",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )
    logger.info(f"Guardian job scheduled every {interval_minutes}m")


def remove_guardian_job():
    """Remove the guardian job if running."""
    if scheduler.get_job(GUARDIAN_JOB_ID):
        scheduler.remove_job(GUARDIAN_JOB_ID)
        logger.info("Guardian job removed")


def start_scheduler():
    """Start the scheduler and load all enabled pairs."""
    from backend.models.position import OpenPosition
    from backend.models.guardian_settings import GuardianSettings

    with Session(engine) as session:
        pairs = session.exec(
            select(TradingPair).where(TradingPair.is_enabled == True)
        ).all()
        for pair in pairs:
            interval = pair.schedule_interval
            if pair.use_exit_schedule:
                has_pos = session.exec(
                    select(OpenPosition).where(OpenPosition.pair_id == pair.id)
                ).first()
                if has_pos:
                    interval = pair.exit_schedule_interval
            add_pair_job(pair.id, interval)

        # Start guardian job if enabled
        guardian = session.get(GuardianSettings, 1)
        if guardian and guardian.enabled:
            add_guardian_job(guardian.interval_minutes)

    scheduler.start()
    logger.info(f"Scheduler started with {len(scheduler.get_jobs())} jobs")


def stop_scheduler():
    """Shut down the scheduler."""
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")


def get_scheduler_status() -> dict:
    """Return current scheduler state for the API."""
    jobs = scheduler.get_jobs()
    return {
        "running": scheduler.running,
        "job_count": len(jobs),
        "jobs": [
            {
                "id": j.id,
                "name": j.name,
                "next_run": str(j.next_run_time) if j.next_run_time else None,
                "trigger": str(j.trigger),
            }
            for j in jobs
        ],
    }
