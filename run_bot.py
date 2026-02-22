#!/usr/bin/env python3
"""
Pythia Telegram Bot Runner.

Loads PYTHIA_TELEGRAM_TOKEN from env, creates the companion engine
and bot, then starts polling.

Usage:
    PYTHIA_TELEGRAM_TOKEN=your_token python run_bot.py
"""

import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("pythia.bot")


def main() -> None:
    """Entry point: load token, create companion + bot, run."""
    token = os.environ.get("PYTHIA_TELEGRAM_TOKEN", "")
    if not token:
        logger.error("PYTHIA_TELEGRAM_TOKEN not set. Export it and retry.")
        sys.exit(1)

    from src.pythia_live.companion import PythiaCompanion
    from src.pythia_live.bot import PythiaBot

    companion = PythiaCompanion()
    bot = PythiaBot(token=token, companion=companion)

    logger.info("Starting Pythia bot...")
    bot.run()


if __name__ == "__main__":
    main()
