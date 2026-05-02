"""Guardian for simple pair trades — monitors SL and TP via fast-polling."""

import asyncio
import logging

from sqlmodel import Session, select

from backend.database import engine
from backend.models.simple_trade import SimplePairTrade
from backend.models.guardian_settings import GuardianSettings
from backend.models.credential import Credential
from backend.services.encryption import decrypt

logger = logging.getLogger(__name__)


async def run_simple_trade_check():
    """Check all open simple trades for stop-loss and take-profit breaches."""
    with Session(engine) as session:
        settings = session.get(GuardianSettings, 1)
        if not settings or not settings.enabled:
            return

        trades = session.exec(
            select(SimplePairTrade).where(SimplePairTrade.status == "open")
        ).all()
        if not trades:
            return

    from backend.services.market_data import fetch_orderbook

    # Fetch mid prices for all needed markets
    market_ids = set()
    for t in trades:
        market_ids.add(t.lighter_market_a)
        market_ids.add(t.lighter_market_b)

    orderbook_tasks = {mid: fetch_orderbook(mid) for mid in market_ids}
    results = await asyncio.gather(*orderbook_tasks.values(), return_exceptions=True)
    mid_prices = {}
    for mid, result in zip(orderbook_tasks.keys(), results):
        if isinstance(result, Exception):
            logger.error(f"[simple-guardian] Failed to fetch orderbook for market {mid}: {result}")
            mid_prices[mid] = None
        else:
            mid_prices[mid] = result.get("mid_price", 0.0)

    # Check each open trade
    close_tasks = []
    for trade in trades:
        price_a = mid_prices.get(trade.lighter_market_a)
        price_b = mid_prices.get(trade.lighter_market_b)

        if not price_a or not price_b or price_a <= 0 or price_b <= 0:
            logger.warning(f"[simple-guardian] Skipping QT-{trade.id}: invalid prices (A={price_a}, B={price_b})")
            continue

        # Compute unrealized PnL
        pnl_a = _leg_pnl(trade.entry_price_a, price_a, trade.fill_size_a, trade.direction == 1)
        pnl_b = _leg_pnl(trade.entry_price_b, price_b, trade.fill_size_b, trade.direction == -1)
        total_pnl = pnl_a + pnl_b
        pnl_pct = total_pnl / trade.margin_usd * 100 if trade.margin_usd > 0 else 0

        if trade.stop_loss_pct > 0 and pnl_pct <= -trade.stop_loss_pct:
            logger.warning(
                f"[simple-guardian] STOP-LOSS QT-{trade.id}: "
                f"PnL=${total_pnl:.2f} ({pnl_pct:.2f}%) threshold=-{trade.stop_loss_pct}%"
            )
            close_tasks.append((trade.id, "stop_loss"))
        elif trade.take_profit_pct > 0 and pnl_pct >= trade.take_profit_pct:
            logger.warning(
                f"[simple-guardian] TAKE-PROFIT QT-{trade.id}: "
                f"PnL=${total_pnl:.2f} ({pnl_pct:.2f}%) threshold=+{trade.take_profit_pct}%"
            )
            close_tasks.append((trade.id, "take_profit"))
        else:
            logger.debug(f"[simple-guardian] QT-{trade.id}: PnL=${total_pnl:.2f} ({pnl_pct:.2f}%)")

    # Execute closes
    if close_tasks:
        from backend.api.quick_trades import _close_trade

        results = await asyncio.gather(
            *[_close_trade(tid, reason) for tid, reason in close_tasks],
            return_exceptions=True,
        )
        for (tid, reason), result in zip(close_tasks, results):
            if isinstance(result, Exception):
                logger.error(f"[simple-guardian] Close failed for QT-{tid}: {result}", exc_info=True)


def _leg_pnl(entry_price: float, current_price: float, size: float, is_long: bool) -> float:
    if is_long:
        return (current_price - entry_price) * size
    else:
        return (entry_price - current_price) * size
