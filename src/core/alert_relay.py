"""
Pythia Alert Relay — writes signals to a file that OpenClaw picks up.
Avoids needing a separate Telegram bot.
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from .detector import Signal

logger = logging.getLogger(__name__)

RELAY_FILE = Path(os.environ.get(
    "PYTHIA_RELAY_FILE",
    str(Path(__file__).resolve().parent.parent.parent / "data" / "pythia_alerts.jsonl"),
))


def relay_signal(signal: Signal, pattern_insight: str = "") -> bool:
    """Append signal to relay file for OpenClaw to pick up."""
    # Filter noise
    price = signal.new_price or signal.old_price or 0
    if price < 0.05 or price > 0.95:
        return False
    # Skip non-tradeable categories (sports, entertainment, memes)
    skip_classes = {"general"}
    if signal.asset_class in skip_classes:
        return False
    title_lower = (signal.market_title or "").lower()
    noise_keywords = ["nba", "nfl", "nhl", "mlb", "stanley cup", "super bowl",
                      "finals?", "win the 2", "gta", "album", "grammy", "oscar",
                      "emmy", "bachelor", "love island", "squid game"]
    if any(kw in title_lower for kw in noise_keywords):
        return False
    try:
        entry = {
            "timestamp": signal.timestamp.isoformat(),
            "market_title": signal.market_title,
            "signal_type": signal.signal_type,
            "severity": signal.severity,
            "description": signal.description,
            "old_price": signal.old_price,
            "new_price": signal.new_price,
            "expected_return": signal.expected_return,
            "asset_class": signal.asset_class,
            "instruments": signal.instruments,
            "why_it_matters": signal.why_it_matters,
            "correlated_markets": signal.correlated_markets[:3] if signal.correlated_markets else [],
            "news_context": signal.news_context[:2] if signal.news_context else [],
            "pattern_insight": pattern_insight,
            "relayed": False
        }
        with open(RELAY_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
        return True
    except Exception as e:
        logger.error("Alert relay error: %s", e)
        return False
