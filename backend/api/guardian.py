"""Guardian API — settings and status for the global stop-loss guardian."""

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func as sa_func
from sqlmodel import Session, select

from backend.database import get_session
from backend.models.guardian_settings import GuardianSettings
from backend.models.position import OpenPosition
from backend.models.trading_pair import TradingPair
from backend.models.credential import Credential
from backend.api.deps import get_current_user
from backend.services.encryption import decrypt

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
    interval_minutes: int | None = None
    stop_loss_pct_override: float | None = None


@router.patch("/settings")
def update_settings(
    body: GuardianSettingsUpdate,
    session: Session = Depends(get_session),
):
    settings = _get_or_create_settings(session)

    if body.enabled is not None:
        settings.enabled = body.enabled
    if body.interval_minutes is not None:
        settings.interval_minutes = max(1, min(body.interval_minutes, 15))
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
        add_guardian_job(settings.interval_minutes)
    else:
        remove_guardian_job()

    return settings


@router.get("/logs")
def guardian_logs(session: Session = Depends(get_session)):
    from backend.models.job_log import JobLog

    logs = session.exec(
        select(JobLog)
        .where(JobLog.action.like("guardian_%"))
        .order_by(JobLog.timestamp.desc())
        .limit(24)
    ).all()
    return logs


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
        "interval_minutes": settings.interval_minutes,
        "job_running": job is not None,
        "next_run": str(job.next_run_time) if job and job.next_run_time else None,
        "trigger": str(job.trigger) if job else None,
        "monitored_positions": position_count,
    }


@router.get("/live-pnl")
async def guardian_live_pnl(session: Session = Depends(get_session)):
    """Compute live PnL for each monitored pair using real exchange data.

    Uses the same logic as the guardian stop-loss check.
    """
    from backend.services.lighter_client import LighterClient
    from backend.services.market_data import fetch_orderbook

    settings = _get_or_create_settings(session)

    positions = session.exec(select(OpenPosition)).all()
    if not positions:
        return []

    pair_ids = [p.pair_id for p in positions]
    pairs = session.exec(
        select(TradingPair).where(TradingPair.id.in_(pair_ids))
    ).all()
    pair_map = {p.id: p for p in pairs}

    active_creds = session.exec(
        select(Credential).where(Credential.is_active == True)
    ).all()
    cred_map = {c.id: c for c in active_creds}
    default_cred_id = active_creds[0].id if active_creds else None

    # Resolve credential per pair
    checks = []
    for pos in positions:
        pair = pair_map.get(pos.pair_id)
        if not pair or not pair.is_enabled:
            continue
        cred_id = pair.credential_id if pair.credential_id is not None else default_cred_id
        checks.append((pair, pos, cred_id))

    if not checks:
        return []

    # Fetch exchange positions per credential
    needed_cred_ids = {cid for _, _, cid in checks if cid is not None}

    async def _fetch_for_cred(cred):
        pk = decrypt(cred.private_key_encrypted)
        client = LighterClient(
            host=cred.lighter_host,
            private_key=pk,
            api_key_index=cred.api_key_index,
            account_index=cred.account_index,
        )
        try:
            raw = await client.get_positions()
            return cred.id, {p["market_index"]: p for p in raw}
        finally:
            await client.close()

    cred_tasks = [_fetch_for_cred(cred_map[cid]) for cid in needed_cred_ids if cid in cred_map]

    # Fetch orderbook prices
    market_ids = set()
    for pair, _, _ in checks:
        market_ids.add(pair.lighter_market_a)
        market_ids.add(pair.lighter_market_b)

    ob_tasks = {mid: fetch_orderbook(mid) for mid in market_ids}
    cred_results, *ob_results = await asyncio.gather(
        asyncio.gather(*cred_tasks),
        *ob_tasks.values(),
    )

    exchange_by_cred = dict(cred_results)
    mid_prices = {mid: ob["mid_price"] for mid, ob in zip(ob_tasks.keys(), ob_results)}

    result = []
    for pair, pos, cred_id in checks:
        price_a = mid_prices.get(pair.lighter_market_a, 0.0)
        price_b = mid_prices.get(pair.lighter_market_b, 0.0)

        ex_positions = exchange_by_cred.get(cred_id, {})
        ex_a = ex_positions.get(pair.lighter_market_a)
        ex_b = ex_positions.get(pair.lighter_market_b)

        # Compute PnL from real exchange positions
        unreal_pnl = 0.0
        legs = []
        for label, ex_pos, current_price in [("A", ex_a, price_a), ("B", ex_b, price_b)]:
            if not ex_pos:
                legs.append({"leg": label, "side": "-", "size": 0, "entry_price": 0, "current_price": current_price, "pnl": 0})
                continue
            ep = ex_pos["entry_price"]
            sz = ex_pos["size"]
            side = ex_pos["side"]
            if ep > 0 and current_price > 0:
                leg_pnl = (current_price - ep) * sz if side == "long" else (ep - current_price) * sz
            else:
                leg_pnl = 0.0
            unreal_pnl += leg_pnl
            legs.append({"leg": label, "side": side, "size": round(sz, 6), "entry_price": round(ep, 4), "current_price": round(current_price, 4), "pnl": round(leg_pnl, 2)})

        entry_equity = pos.entry_notional / pair.leverage if pair.leverage > 0 else pos.entry_notional
        unreal_pct = unreal_pnl / entry_equity * 100 if entry_equity != 0 else 0

        stop_loss_pct = settings.stop_loss_pct_override if settings.stop_loss_pct_override is not None else pair.stop_loss_pct
        triggered = stop_loss_pct > 0 and unreal_pct <= -stop_loss_pct

        result.append({
            "pair_name": pair.name,
            "pair_id": pair.id,
            "excluded": pair.guardian_excluded,
            "stop_loss_pct": stop_loss_pct,
            "entry_equity": round(entry_equity, 2),
            "unrealized_pnl": round(unreal_pnl, 2),
            "unrealized_pct": round(unreal_pct, 2),
            "triggered": triggered,
            "legs": legs,
        })

    return result
