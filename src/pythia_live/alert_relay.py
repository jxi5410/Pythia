"""
Pythia Alert Relay — writes signals to a file that OpenClaw picks up.
Avoids needing a separate Telegram bot.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from .detector import Signal

RELAY_FILE = Path("/Users/xj.ai/.openclaw/workspace/pythia_alerts.jsonl")


def relay_signal(signal: Signal, pattern_insight: str = "") -> bool:
    """Append signal to relay file for OpenClaw to pick up."""
    # Filter noise: skip penny markets and extreme prices
    price = signal.new_price or signal.old_price or 0
    if price < 0.05 or price > 0.95:
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
        print(f"Alert relay error: {e}")
        return False
