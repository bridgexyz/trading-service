"""Telegram bot for trading service notifications and remote control."""

import asyncio
import logging
import threading
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from sqlmodel import Session, select

from backend.config import settings

logger = logging.getLogger(__name__)

_bot_instance: Optional["TelegramBot"] = None


class TelegramBot:
    """Telegram bot running in a background thread with its own event loop."""

    def __init__(self, token: str, chat_ids: list[int]):
        self.token = token
        self.chat_ids = set(chat_ids)
        self._app: Optional[Application] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _is_authorized(self, user_id: int) -> bool:
        return user_id in self.chat_ids

    async def _check_auth(self, update: Update) -> bool:
        if not update.effective_user or not self._is_authorized(update.effective_user.id):
            if update.message:
                await update.message.reply_text("Unauthorized.")
            return False
        return True

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return

        from backend.engine.scheduler import get_scheduler_status
        from backend.database import engine
        from backend.models.position import OpenPosition

        status = get_scheduler_status()
        with Session(engine) as session:
            positions = session.exec(select(OpenPosition)).all()
            pos_count = len(positions)

        scheduler_str = "running" if status["running"] else "stopped"
        text = (
            f"Scheduler: {scheduler_str}\n"
            f"Jobs: {status['job_count']}\n"
            f"Open positions: {pos_count}"
        )
        await update.message.reply_text(text)

    async def _cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return

        from backend.database import engine
        from backend.models.position import OpenPosition
        from backend.models.trading_pair import TradingPair

        with Session(engine) as session:
            positions = session.exec(select(OpenPosition)).all()
            if not positions:
                await update.message.reply_text("No open positions.")
                return

            lines = []
            for pos in positions:
                pair = session.get(TradingPair, pos.pair_id)
                name = pair.name if pair else f"#{pos.pair_id}"
                direction = "Long" if pos.direction == 1 else "Short"
                lines.append(
                    f"{name}: {direction} | z={pos.entry_z:.3f} | ${pos.entry_notional:.0f}"
                )

        await update.message.reply_text("\n".join(lines))

    async def _cmd_close_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Yes, close all", callback_data="confirm_close_all"),
                InlineKeyboardButton("Cancel", callback_data="cancel"),
            ]
        ])
        await update.message.reply_text(
            "Close all positions (keep pairs enabled)?",
            reply_markup=keyboard,
        )

    async def _cmd_stop_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Yes, stop everything", callback_data="confirm_stop_all"),
                InlineKeyboardButton("Cancel", callback_data="cancel"),
            ]
        ])
        await update.message.reply_text(
            "Close all positions AND disable all pairs?",
            reply_markup=keyboard,
        )

    async def _cmd_start_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return

        from backend.database import engine
        from backend.models.trading_pair import TradingPair
        from backend.engine.scheduler import add_pair_job
        from datetime import datetime, timezone

        with Session(engine) as session:
            pairs = session.exec(
                select(TradingPair).where(TradingPair.is_enabled == False)
            ).all()
            count = 0
            for pair in pairs:
                pair.is_enabled = True
                pair.updated_at = datetime.now(timezone.utc)
                session.add(pair)
                add_pair_job(pair.id, pair.schedule_interval)
                count += 1
            session.commit()

        await update.message.reply_text(f"Re-enabled {count} pairs.")

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query or not query.from_user or not self._is_authorized(query.from_user.id):
            return

        await query.answer()

        if query.data == "cancel":
            await query.edit_message_text("Cancelled.")
            return

        from backend.services.emergency_stop import run_emergency_stop

        if query.data == "confirm_close_all":
            await query.edit_message_text("Closing all positions...")
            result = await run_emergency_stop(close_positions=True, disable_pairs=False)
            errors = f"\nErrors: {len(result['errors'])}" if result["errors"] else ""
            await query.edit_message_text(
                f"Closed {result['positions_closed']} positions.{errors}"
            )

        elif query.data == "confirm_stop_all":
            await query.edit_message_text("Emergency stop in progress...")
            result = await run_emergency_stop(close_positions=True, disable_pairs=True)
            errors = f"\nErrors: {len(result['errors'])}" if result["errors"] else ""
            await query.edit_message_text(
                f"Closed {result['positions_closed']} positions, "
                f"disabled {result['pairs_disabled']} pairs.{errors}"
            )

    async def send_notification(self, message: str):
        """Send a message to all whitelisted chat IDs."""
        if not self._app or not self._app.bot:
            return
        for chat_id in self.chat_ids:
            try:
                await self._app.bot.send_message(chat_id=chat_id, text=message)
            except Exception as e:
                logger.warning(f"Failed to send Telegram notification to {chat_id}: {e}")

    def _run_bot(self):
        """Run the bot in a background thread with its own event loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        self._app = (
            Application.builder()
            .token(self.token)
            .build()
        )

        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("positions", self._cmd_positions))
        self._app.add_handler(CommandHandler("close_all", self._cmd_close_all))
        self._app.add_handler(CommandHandler("stop_all", self._cmd_stop_all))
        self._app.add_handler(CommandHandler("start_all", self._cmd_start_all))
        self._app.add_handler(CallbackQueryHandler(self._handle_callback))

        logger.info("Telegram bot starting...")
        self._loop.run_until_complete(self._app.initialize())
        self._loop.run_until_complete(self._app.start())
        self._loop.run_until_complete(self._app.updater.start_polling())
        self._loop.run_forever()

    def start(self):
        self._thread = threading.Thread(target=self._run_bot, daemon=True)
        self._thread.start()

    def stop(self):
        if self._loop and self._app:
            async def _shutdown():
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()

            asyncio.run_coroutine_threadsafe(_shutdown(), self._loop).result(timeout=10)
            self._loop.call_soon_threadsafe(self._loop.stop)


def init_bot() -> TelegramBot:
    """Initialize and return the bot singleton."""
    global _bot_instance
    _bot_instance = TelegramBot(
        token=settings.telegram_bot_token,
        chat_ids=settings.telegram_chat_ids,
    )
    return _bot_instance


def get_bot() -> Optional[TelegramBot]:
    """Get the bot singleton, or None if not initialized."""
    return _bot_instance
