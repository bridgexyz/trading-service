"""APScheduler integration for FastAPI.

Manages per-pair interval jobs that run the trading engine.
"""

import logging

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


def _get_trigger(interval: str) -> IntervalTrigger:
    # Support arbitrary "<N>m" schedule intervals
    if interval.endswith("m") and interval[:-1].isdigit():
        return IntervalTrigger(minutes=int(interval[:-1]))
    hours = INTERVAL_HOURS.get(interval, 4.0)
    if hours < 1:
        return IntervalTrigger(minutes=int(hours * 60))
    return IntervalTrigger(hours=hours)


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


def start_scheduler():
    """Start the scheduler and load all enabled pairs."""
    with Session(engine) as session:
        pairs = session.exec(
            select(TradingPair).where(TradingPair.is_enabled == True)
        ).all()
        for pair in pairs:
            add_pair_job(pair.id, pair.schedule_interval)

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
