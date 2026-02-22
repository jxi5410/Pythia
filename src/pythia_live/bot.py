"""
Pythia Telegram Bot — Async bot runner using python-telegram-bot>=21.0.

Primary interface is natural text routed through PythiaCompanion.
Slash commands are shortcuts only: /start, /watchlist, /proof, /settings.
"""

import logging
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .companion import PythiaCompanion
from .user_context import UserContextManager

logger = logging.getLogger(__name__)


class PythiaBot:
    """
    Async Telegram bot that routes all messages through PythiaCompanion.

    Args:
        token: Telegram Bot API token.
        companion: PythiaCompanion instance for generating responses.
    """

    def __init__(self, token: str, companion: PythiaCompanion):
        self.token = token
        self.companion = companion
        self._app: Optional[Application] = None

    def build(self) -> Application:
        """Build and configure the Telegram Application."""
        self._app = (
            Application.builder()
            .token(self.token)
            .build()
        )

        # Command shortcuts
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("watchlist", self._cmd_watchlist))
        self._app.add_handler(CommandHandler("proof", self._cmd_proof))
        self._app.add_handler(CommandHandler("settings", self._cmd_settings))

        # All other text goes to the conversational engine
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        return self._app

    def run(self) -> None:
        """Start polling for messages. Blocks until stopped."""
        app = self.build()
        logger.info("Pythia bot starting...")
        app.run_polling()

    # ------------------------------------------------------------------ #
    # Message handler — the main entry point
    # ------------------------------------------------------------------ #

    async def _handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Route any text message through the companion engine."""
        if not update.message or not update.message.text:
            return

        user_id = str(update.effective_user.id)
        text = update.message.text.strip()

        if not text:
            return

        try:
            response = await self.companion.respond(user_id, text)
            await update.message.reply_text(
                response, parse_mode="Markdown"
            )
        except Exception as e:
            logger.exception("Failed to respond to user %s: %s", user_id, e)
            await update.message.reply_text(
                "Something went wrong. Try again in a sec."
            )

    # ------------------------------------------------------------------ #
    # Command shortcuts
    # ------------------------------------------------------------------ #

    async def _cmd_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """/start — Welcome message."""
        user_id = str(update.effective_user.id)
        name = update.effective_user.first_name or "trader"
        await update.message.reply_text(
            f"Hey {name}. I'm Pythia.\n\n"
            "I watch prediction markets, congressional trades, Twitter "
            "velocity, rate signals, and 4 other data layers. When they "
            "converge, I flag it.\n\n"
            "Just talk to me naturally:\n"
            "\u2022 \"what's moving\" \u2014 active signals\n"
            "\u2022 \"fed\" / \"china\" / \"crypto\" \u2014 category filter\n"
            "\u2022 \"watch RTX\" \u2014 track an asset\n"
            "\u2022 \"regime\" \u2014 macro state\n"
            "\u2022 \"proof\" \u2014 my track record\n\n"
            "No slash commands needed. Just type.",
            parse_mode="Markdown",
        )

    async def _cmd_watchlist(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """/watchlist — Show active watches."""
        user_id = str(update.effective_user.id)
        response = await self.companion.respond(user_id, "watchlist")
        await update.message.reply_text(response, parse_mode="Markdown")

    async def _cmd_proof(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """/proof — Track record stats."""
        user_id = str(update.effective_user.id)
        response = await self.companion.respond(user_id, "proof")
        await update.message.reply_text(response, parse_mode="Markdown")

    async def _cmd_settings(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """/settings — User settings (placeholder)."""
        await update.message.reply_text(
            "\u2699\ufe0f **Settings**\n\n"
            "Alert threshold: 40% confluence\n"
            "Morning briefing: enabled\n"
            "Weekly digest: enabled\n\n"
            "Settings customisation coming soon. "
            "For now, just tell me what to watch.",
            parse_mode="Markdown",
        )

    # ------------------------------------------------------------------ #
    # Proactive push
    # ------------------------------------------------------------------ #

    async def send_proactive(self, chat_id: str, message: str) -> bool:
        """
        Push a proactive alert to a user.

        Args:
            chat_id: Telegram chat ID to send to.
            message: Markdown-formatted message.

        Returns:
            True if sent successfully.
        """
        if not self._app or not self._app.bot:
            logger.warning("Bot not initialised, cannot send proactive alert")
            return False

        try:
            await self._app.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="Markdown",
            )
            return True
        except Exception as e:
            logger.warning("Failed to send proactive alert to %s: %s", chat_id, e)
            return False
